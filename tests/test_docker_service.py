"""Unit tests for lock-free dynamic port retry, healthcheck readiness, and container capabilities."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any, Self
from unittest.mock import MagicMock

import pytest
from docker.errors import APIError, DockerException, ImageNotFound

from pytest_databases import ContainerService, should_keep_containers, wait_for_container_health
from pytest_databases._s3 import create_s3_bucket
from pytest_databases._service import (
    _COMPLETED_SESSION_OWNERS,
    _REGISTERED_ATEXIT_OWNERS,
    _RUNTIME_STASH_KEY,
    _check_container_alive,
    _cleanup_session_containers,
    _ensure_image,
    _get_base_tmp_path,
    _register_atexit_cleanup,
    _resolve_binding,
    _stop_single_container,
    _wait_for_readiness,
    container_client,
    container_runtime,
    container_service,
    docker_client,
    docker_service,
    get_docker_client,
    get_docker_host,
    pytest_sessionfinish,
    stop_all_containers,
    stop_owned_containers,
)
from pytest_databases.docker import DockerServiceRegistry, wait_until_responsive
from pytest_databases.runtime import ContainerRuntimeConfig, RuntimeResolutionError, RuntimeType
from pytest_databases.types import ServiceContainer
from tests.conftest import unwrap_fixture

if TYPE_CHECKING:
    from pathlib import Path


def make_service(
    tmp_path: Path,
    client: Any,
    *,
    keep_containers: bool = False,
) -> ContainerService:
    """Construct a ContainerService instance with a mock client."""
    mock_session = MagicMock()
    mock_session.config.rootpath = tmp_path
    mock_session.config.getoption.side_effect = lambda opt, default=None: (
        keep_containers if opt == "--keep-containers" else default
    )
    mock_session.config._tmp_path_factory.getbasetemp.return_value = tmp_path
    runtime_config = ContainerRuntimeConfig(RuntimeType.DOCKER, "unix:///docker.sock", "test")
    client.containers.list.return_value = []
    return ContainerService(
        client=client,
        tmp_path=tmp_path,
        session=mock_session,
        runtime_config=runtime_config,
        owner_id="0123456789ab",
    )


def test_no_global_creation_lock_attribute(tmp_path: Path) -> None:
    """Ensure ContainerService avoids any global creation lock."""
    service = make_service(tmp_path, MagicMock())
    assert not hasattr(service, "_creation_lock")


def test_dynamic_port_retry_succeeds_on_second_attempt(tmp_path: Path) -> None:
    """Ensure dynamic port allocation retries when encountering address already in use."""
    mock_client = MagicMock()
    mock_container = MagicMock(status="running", attrs={"State": {"Status": "running"}})
    mock_container.ports = {"5432/tcp": [{"HostPort": "32800"}]}

    port_error = APIError(
        "driver failed programming external connectivity: failed to bind host port: address already in use"
    )
    mock_client.containers.run.side_effect = [port_error, mock_container]

    service = make_service(tmp_path, mock_client)

    with service.run(
        image="postgres:latest",
        container_port=5432,
        name="retry_test",
        check=lambda _s: True,
    ) as s:
        assert s.port == 32800

    assert mock_client.containers.run.call_count == 2
    first_kwargs = mock_client.containers.run.call_args_list[0].kwargs
    assert first_kwargs["name"] == service.container_name("pytest_databases_retry_test")
    assert first_kwargs["labels"] == service.container_labels("pytest_databases_retry_test")
    mock_client.containers.get.assert_called_once_with(service.container_name("pytest_databases_retry_test"))


def test_pinned_port_does_not_retry_on_conflict(tmp_path: Path) -> None:
    """Ensure explicit host_port fails immediately without retry on port collision."""
    mock_client = MagicMock()
    port_error = APIError("failed to bind host port 0.0.0.0:15432/tcp: address already in use")
    mock_client.containers.run.side_effect = port_error

    service = make_service(tmp_path, mock_client)

    with (
        pytest.raises(APIError),
        service.run(
            image="postgres:latest",
            container_port=5432,
            name="pinned_conflict",
            host_port=15432,
            check=lambda _s: True,
        ),
    ):
        pass

    assert mock_client.containers.run.call_count == 1


def test_dynamic_port_retry_re_raises_after_three_failures(tmp_path: Path) -> None:
    """Ensure dynamic port allocation gives up after 3 consecutive collisions."""
    mock_client = MagicMock()
    port_error = APIError("listen tcp4 0.0.0.0:33000: bind: address already in use")
    mock_client.containers.run.side_effect = [port_error, port_error, port_error]

    service = make_service(tmp_path, mock_client)

    with (
        pytest.raises(APIError),
        service.run(
            image="postgres:latest",
            container_port=5432,
            name="three_failures",
            check=lambda _s: True,
        ),
    ):
        pass

    assert mock_client.containers.run.call_count == 3


def test_unrelated_apierror_does_not_retry(tmp_path: Path) -> None:
    """Ensure errors not involving port in use are raised immediately."""
    mock_client = MagicMock()
    disk_error = APIError("no space left on device")
    mock_client.containers.run.side_effect = disk_error

    service = make_service(tmp_path, mock_client)

    with (
        pytest.raises(APIError),
        service.run(
            image="postgres:latest",
            container_port=5432,
            name="disk_error",
            check=lambda _s: True,
        ),
    ):
        pass

    assert mock_client.containers.run.call_count == 1


def test_container_fast_fail_when_status_exited(tmp_path: Path) -> None:
    """Ensure readiness check raises RuntimeError immediately if container status is exited."""
    mock_client = MagicMock()
    mock_container = MagicMock()
    mock_container.status = "exited"
    mock_container.ports = {"5432/tcp": [{"HostPort": "32800"}]}
    mock_container.logs.return_value = b"FATAL: configuration error"
    mock_client.containers.run.return_value = mock_container

    service = make_service(tmp_path, mock_client)

    with (
        pytest.raises(RuntimeError, match="exited prematurely with status 'exited'"),
        service.run(
            image="postgres:latest",
            container_port=5432,
            name="fast_fail_test",
            check=lambda _s: False,
            timeout=10,
        ),
    ):
        pass


def test_resolve_port_extracts_mapped_host_port() -> None:
    """Ensure ContainerService.resolve_port extracts port binding."""
    mock_container = MagicMock()
    mock_container.ports = {"9020/tcp": [{"HostPort": "39020"}]}
    port = ContainerService.resolve_port(mock_container, 9020)
    assert port == 39020


def test_wait_for_health_succeeds_when_healthy(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Ensure wait_for_health=True keeps polling State.Health.Status while starting and returns once healthy."""
    mock_client = MagicMock()
    mock_container = MagicMock()
    mock_container.status = "running"
    mock_container.ports = {"5432/tcp": [{"HostPort": "32801"}]}
    sleeps: list[float] = []
    monkeypatch.setattr("pytest_databases._service.time.sleep", sleeps.append)

    starting = {"Status": "running", "Health": {"Status": "starting", "Log": []}}
    states = [
        starting,
        starting,
        starting,
        {"Status": "running", "Health": {"Status": "healthy", "Log": [{"ExitCode": 0, "Output": "ok"}]}},
    ]
    call_idx = 0

    def reload_side_effect() -> None:
        nonlocal call_idx
        idx = min(call_idx, len(states) - 1)
        mock_container.attrs = {"State": states[idx]}
        call_idx += 1

    mock_container.reload.side_effect = reload_side_effect
    mock_client.containers.run.return_value = mock_container

    service = make_service(tmp_path, mock_client)
    with service.run(
        image="postgres:latest",
        container_port=5432,
        name="health_ok",
        wait_for_health=True,
        pause=0.01,
    ) as s:
        assert s.port == 32801

    assert call_idx == len(states)
    assert sleeps == [0.01]


def test_wait_for_health_times_out_while_starting(monkeypatch: pytest.MonkeyPatch) -> None:
    """Ensure a container that stays in the starting state fails after the timeout."""
    clock = iter(range(100))
    monkeypatch.setattr("pytest_databases._service.time.time", lambda: float(next(clock)))
    monkeypatch.setattr("pytest_databases._service.time.sleep", lambda _pause: None)
    mock_container = MagicMock(status="running")
    mock_container.attrs = {"State": {"Status": "running", "Health": {"Status": "starting", "Log": []}}}

    with pytest.raises(RuntimeError, match=r"did not become healthy within 3s \(last status: 'starting'\)"):
        wait_for_container_health(mock_container, "pytest_databases_slow", timeout=3, pause=0.01)


def test_wait_for_health_fails_immediately_without_healthcheck(monkeypatch: pytest.MonkeyPatch) -> None:
    """Ensure wait_for_health on an image without HEALTHCHECK fails at once instead of waiting for the timeout."""
    sleeps: list[float] = []
    monkeypatch.setattr("pytest_databases._service.time.sleep", sleeps.append)
    mock_container = MagicMock(status="running")
    mock_container.attrs = {"State": {"Status": "running"}, "Config": {"Image": "postgres:18"}}

    with pytest.raises(RuntimeError, match=r"image 'postgres:18' defines no HEALTHCHECK"):
        wait_for_container_health(mock_container, "pytest_databases_plain", timeout=60, pause=1)
    assert sleeps == []


def test_wait_for_health_fails_fast_when_unhealthy() -> None:
    """Ensure wait_for_container_health raises RuntimeError with logs when unhealthy."""
    mock_container = MagicMock()
    mock_container.status = "running"
    mock_container.attrs = {
        "State": {
            "Status": "running",
            "Health": {
                "Status": "unhealthy",
                "Log": [{"ExitCode": 1, "Output": "database readiness probe failed"}],
            },
        }
    }

    with pytest.raises(RuntimeError, match="database readiness probe failed"):
        wait_for_container_health(mock_container, "pytest_databases_broken", timeout=2, pause=0.01)


def test_enterprise_container_capabilities_forwarded(tmp_path: Path) -> None:
    """Ensure shm_size, entrypoint, privileged, ipc_mode, cap_add, devices, hostname, and volumes are forwarded."""
    mock_client = MagicMock()
    mock_container = MagicMock()
    mock_container.status = "running"
    mock_container.ports = {"50000/tcp": [{"HostPort": "50000"}]}
    mock_client.containers.run.return_value = mock_container
    volumes = {"/host/wallet": {"bind": "/u01/app/oracle/wallets/tls_wallet", "mode": "rw"}}

    service = make_service(tmp_path, mock_client)
    with service.run(
        image="icr.io/db2_community/db2:latest",
        container_port=50000,
        name="db2_cap_test",
        command=["/bin/sh", "-c", "echo ok"],
        entrypoint=["/entrypoint.sh"],
        shm_size="2g",
        privileged=True,
        ipc_mode="host",
        cap_add=["SYS_ADMIN", "IPC_LOCK"],
        devices=["/dev/fuse"],
        hostname="my-adb.adb.us-ashburn-1.oraclecloud.com",
        volumes=volumes,
        check=lambda _s: True,
    ):
        pass

    _, kwargs = mock_client.containers.run.call_args
    assert kwargs["shm_size"] == "2g"
    assert kwargs["entrypoint"] == ["/entrypoint.sh"]
    assert kwargs["privileged"] is True
    assert kwargs["ipc_mode"] == "host"
    assert kwargs["cap_add"] == ["SYS_ADMIN", "IPC_LOCK"]
    assert kwargs["devices"] == ["/dev/fuse"]
    assert kwargs["hostname"] == "my-adb.adb.us-ashburn-1.oraclecloud.com"
    assert kwargs["volumes"] == volumes


@pytest.mark.parametrize(
    ("value", "expected"), [("1", True), ("on", True), ("enabled", True), ("0", False), ("", False)]
)
def test_should_keep_containers_reads_truthy_env_values(
    monkeypatch: pytest.MonkeyPatch, value: str, expected: bool
) -> None:
    """Verify PYTEST_DATABASES_KEEP_CONTAINERS accepts the shared truthy values."""
    monkeypatch.setenv("PYTEST_DATABASES_KEEP_CONTAINERS", value)
    assert should_keep_containers() is expected


def test_should_keep_containers_respects_env_and_cli(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Verify should_keep_containers honors environment variable and CLI flag and skips teardown."""
    monkeypatch.delenv("PYTEST_DATABASES_KEEP_CONTAINERS", raising=False)
    assert should_keep_containers() is False

    monkeypatch.setenv("PYTEST_DATABASES_KEEP_CONTAINERS", "1")
    assert should_keep_containers() is True

    monkeypatch.delenv("PYTEST_DATABASES_KEEP_CONTAINERS", raising=False)
    mock_client = MagicMock()
    mock_container = MagicMock()
    mock_container.status = "running"
    mock_container.ports = {"5432/tcp": [{"HostPort": "32802"}]}
    mock_client.containers.run.return_value = mock_container

    service = make_service(tmp_path, mock_client, keep_containers=True)
    with (
        service,
        service.run(
            image="postgres:latest",
            container_port=5432,
            name="keep_test",
            transient=True,
            check=lambda _s: True,
        ),
    ):
        pass

    mock_container.stop.assert_not_called()
    mock_container.kill.assert_not_called()


def test_wait_until_responsive_retries_and_times_out(monkeypatch: pytest.MonkeyPatch) -> None:
    """Verify wait_until_responsive retries until check returns True and raises RuntimeError on timeout."""
    monkeypatch.setattr("pytest_databases.docker.time.sleep", lambda _s: None)
    attempts = 0

    def _eventual_ok(expected: int) -> bool:
        nonlocal attempts
        attempts += 1
        return attempts >= expected

    wait_until_responsive(_eventual_ok, timeout=1.0, pause=0.01, expected=2)
    assert attempts == 2

    ticks = iter([0.0, 0.5, 1.5])
    monkeypatch.setattr("pytest_databases.docker.timeit.default_timer", lambda: next(ticks))
    with pytest.raises(RuntimeError, match="Timeout reached while waiting on service!"):
        wait_until_responsive(lambda: False, timeout=1.0, pause=0.01)


@pytest.mark.parametrize(
    ("docker_host", "expected_ip", "raises"),
    [
        ("", "127.0.0.1", False),
        ("unix:///var/run/docker.sock", "127.0.0.1", False),
        ("tcp://192.168.99.100:2376", "192.168.99.100", False),
        ("http://invalid-host", "", True),
    ],
)
def test_docker_service_registry_get_docker_ip(
    monkeypatch: pytest.MonkeyPatch,
    docker_host: str,
    expected_ip: str,
    raises: bool,
) -> None:
    """Verify DockerServiceRegistry._get_docker_ip parses empty, unix://, tcp://, and rejects invalid hosts."""
    if docker_host:
        monkeypatch.setenv("DOCKER_HOST", docker_host)
    else:
        monkeypatch.delenv("DOCKER_HOST", raising=False)

    if raises:
        with pytest.raises(ValueError, match="Invalid value for DOCKER_HOST"):
            DockerServiceRegistry._get_docker_ip()
    else:
        assert DockerServiceRegistry._get_docker_ip() == expected_ip


@pytest.mark.parametrize("skip_compose", [False, True])
def test_docker_service_registry_lifecycle(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    skip_compose: bool,
) -> None:
    """Verify DockerServiceRegistry start, stop, down, before_start callbacks, and SKIP_DOCKER_COMPOSE."""
    monkeypatch.delenv("DOCKER_HOST", raising=False)
    monkeypatch.setattr("pytest_databases.docker.SKIP_DOCKER_COMPOSE", skip_compose)
    commands: list[list[str]] = []
    monkeypatch.setattr(
        "pytest_databases.docker.subprocess.run",
        lambda cmd, **_kw: commands.append(list(cmd)),
    )
    callback_calls: list[str] = []
    compose_file = tmp_path / "docker-compose.yml"
    compose_file.write_text("services: {}")

    with (
        pytest.deprecated_call(match="DockerServiceRegistry is deprecated"),
        DockerServiceRegistry(
            "gw0",
            compose_project_name="testproj",
            before_start=[lambda: callback_calls.append("ran")],
        ) as registry,
    ):
        registry.start(
            "postgres",
            [compose_file],
            check=lambda host, port: host == "127.0.0.1" and port == 5432,
            timeout=1.0,
            pause=0.01,
            port=5432,
        )
        registry.start(
            "postgres",
            [compose_file],
            check=lambda host: host == "127.0.0.1",
            timeout=1.0,
            pause=0.01,
        )
        registry.stop("postgres")

    assert callback_calls == ["ran", "ran"]
    if skip_compose:
        assert len(commands) == 1
        assert commands[0][-4:] == ["down", "--volumes", "-t", "10", "postgres"][-4:]
    else:
        assert any("up" in cmd for cmd in commands)
        assert any("down" in cmd for cmd in commands)


def test_container_service_lifecycle_and_helper_branches(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    """Verify ContainerService xdist enter, network IP, image pull retry, port resolution, and cleanup branches."""
    monkeypatch.setattr("pytest_databases._service.time.sleep", lambda _s: None)
    mock_client = MagicMock()
    mock_client.containers.list.return_value = []
    service = make_service(tmp_path, mock_client)
    assert service.owner_id == "0123456789ab"
    assert service.resolve_service_host("10.1.2.3") == "10.1.2.3"
    service._runtime_config = None
    assert service.resolve_service_host() == "127.0.0.1"

    monkeypatch.setenv("PYTEST_XDIST_WORKER", "gw0")
    xdist_service = make_service(tmp_path, mock_client)
    with xdist_service:
        assert (tmp_path.parent / "ctrl").exists() or (tmp_path / "ctrl").exists()
    monkeypatch.delenv("PYTEST_XDIST_WORKER", raising=False)

    net_container = MagicMock(name="c1")
    net_container.attrs = {"NetworkSettings": {"Networks": {}}}
    with pytest.raises(RuntimeError, match="no network settings"):
        ContainerService.get_internal_network_ip(net_container)

    net_container.attrs = {
        "NetworkSettings": {
            "Networks": {
                "custom": {"IPAddress": "172.18.0.5"},
                "bridge": {"IPAddress": "172.17.0.2"},
            }
        }
    }
    assert ContainerService.get_internal_network_ip(net_container, "custom") == "172.18.0.5"
    assert ContainerService.get_internal_network_ip(net_container, "missing") == "172.18.0.5"

    net_container.attrs = {"NetworkSettings": {"Networks": {"bridge": {"IPAddress": ""}}}}
    with pytest.raises(RuntimeError, match="no assigned IP address"):
        ContainerService.get_internal_network_ip(net_container)

    with (
        pytest.raises(ValueError, match="Must set at least check"),
        service.run("postgres:latest", 5432, "invalid_args"),
    ):
        pass

    no_port_container = MagicMock(status="running", ports={})
    mock_client.containers.run.return_value = no_port_container
    with (
        pytest.raises(ValueError, match="failed to create container"),
        service.run("postgres:latest", 5432, "no_ports", check=lambda _s: True),
    ):
        pass

    existing_container = MagicMock(status="running", ports={"5432/tcp": [{"HostPort": "35432"}]})
    mock_client.containers.list.return_value = [existing_container]
    with service.run(
        "postgres:latest",
        5432,
        "existing_svc",
        platform="linux/amd64",
        extra_ports={8080: None},
        exec_after_start=["echo", "ok"],
        transient=True,
        check=lambda _s: True,
    ) as svc_handle:
        assert svc_handle.port == 35432
    existing_container.exec_run.assert_called_once_with(["echo", "ok"])
    existing_container.stop.assert_called_once()

    resp_404 = MagicMock(status_code=404)
    existing_container.stop.side_effect = APIError("gone", response=resp_404)
    with service.run("postgres:latest", 5432, "transient_404", transient=True, check=lambda _s: True):
        pass

    resp_500 = MagicMock(status_code=500)
    existing_container.stop.side_effect = APIError("boom", response=resp_500)
    with (
        pytest.raises(APIError),
        service.run("postgres:latest", 5432, "transient_500", transient=True, check=lambda _s: True),
    ):
        pass

    mock_client.containers.list.return_value = [existing_container, existing_container]
    with pytest.raises(ValueError, match="More than one running container"):
        service._get_container("dup")


def test_service_helpers_and_readiness(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Verify _ensure_image, _resolve_binding, _wait_for_readiness, and stop helpers."""
    monkeypatch.setattr("pytest_databases._service.time.sleep", lambda _s: None)
    mock_client = MagicMock()
    mock_client.images.get.side_effect = ImageNotFound("missing")
    mock_client.images.pull.side_effect = [APIError("transient"), MagicMock()]
    _ensure_image(mock_client, "postgres:16", {"platform": "linux/amd64"})
    assert mock_client.images.pull.call_count == 2

    mock_client.images.pull.side_effect = ImageNotFound("still missing")
    with pytest.raises(ImageNotFound):
        _ensure_image(mock_client, "postgres:16", {})

    c_ports = MagicMock(ports={"5432/udp": [{"HostPort": "45432"}]})
    assert _resolve_binding(c_ports, 5432, "both") == 45432
    with pytest.raises(ValueError, match="Invalid protocol"):
        _resolve_binding(c_ports, 5432, "sctp")
    with pytest.raises(RuntimeError, match="not found in exposed ports"):
        _resolve_binding(c_ports, 9999, "tcp")

    dead_c = MagicMock(status="exited")
    dead_c.reload.side_effect = DockerException("reload err")
    _check_container_alive(dead_c, "svc")
    dead_c.reload.side_effect = None
    dead_c.logs.side_effect = DockerException("log err")
    with pytest.raises(RuntimeError, match="<no logs available>"):
        _check_container_alive(dead_c, "svc")

    ready_c = MagicMock(status="running")
    ready_c.logs.return_value = b"server ready"
    svc_obj = ServiceContainer(container=ready_c, host="127.0.0.1", port=5432)
    _wait_for_readiness(svc_obj, "svc", "server ready", lambda _s: True, timeout=1, pause=0.01)

    ready_c.logs.return_value = b"starting..."
    ticks = iter([0.0, 0.2, 2.0])
    monkeypatch.setattr("pytest_databases._service.time.time", lambda: next(ticks))
    with pytest.raises(ValueError, match="failed to come online"):
        _wait_for_readiness(svc_obj, "svc", "server ready", None, timeout=1, pause=0.01)

    ticks2 = iter([0.0, 0.2, 2.0])
    monkeypatch.setattr("pytest_databases._service.time.time", lambda: next(ticks2))
    with pytest.raises(ValueError, match="failed to come online"):
        _wait_for_readiness(svc_obj, "svc", None, lambda _s: False, timeout=1, pause=0.01)

    c_stopped = MagicMock(status="stopped")
    _stop_single_container(c_stopped)
    c_stopped.remove.assert_called_once()
    c_paused = MagicMock(status="paused")
    with pytest.raises(RuntimeError, match="Cannot handle container in state paused"):
        _stop_single_container(c_paused)

    resp_404 = MagicMock(status_code=404)
    c_err = MagicMock(status="running")
    c_err.kill.side_effect = APIError("gone", response=resp_404)
    mock_client.containers.list.return_value = [c_err]
    stop_owned_containers(mock_client, "owner1")
    stop_all_containers(mock_client)


def test_service_session_fixtures_and_atexit(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    """Verify session runtime/client/service fixtures and atexit/sessionfinish cleanup."""
    mock_client = MagicMock()
    runtime_cfg = ContainerRuntimeConfig(RuntimeType.DOCKER, "unix:///var/run/docker.sock", "test")
    monkeypatch.setattr("pytest_databases._service.resolve_container_runtime", lambda *_a, **_kw: runtime_cfg)
    monkeypatch.setattr(ContainerRuntimeConfig, "create_client", lambda _self: mock_client)
    assert get_docker_host() == "unix:///var/run/docker.sock"
    assert get_docker_client() is mock_client

    req = MagicMock()
    req.config.stash = {}
    req.config.getoption.return_value = None
    req.config.getini.return_value = None
    req.session.config.rootpath = tmp_path
    req.session.config.getoption.return_value = False
    req.session.config._tmp_path_factory.getbasetemp.return_value = tmp_path
    rt = unwrap_fixture(container_runtime)(req)
    assert rt is runtime_cfg
    client_gen = unwrap_fixture(container_client)(rt)
    assert next(client_gen) is mock_client
    with pytest.raises(StopIteration):
        next(client_gen)
    dclient_gen = unwrap_fixture(docker_client)(mock_client)
    assert next(dclient_gen) is mock_client

    tpf = MagicMock()
    tpf.getbasetemp.return_value = tmp_path / "gw0"
    monkeypatch.setenv("PYTEST_XDIST_WORKER", "gw0")
    assert _get_base_tmp_path(tpf) == tmp_path
    monkeypatch.delenv("PYTEST_XDIST_WORKER", raising=False)

    svc_gen = unwrap_fixture(container_service)(mock_client, rt, tpf, req)
    svc_inst = next(svc_gen)
    dsvc_gen = unwrap_fixture(docker_service)(svc_inst)
    assert next(dsvc_gen) is svc_inst
    with pytest.raises(StopIteration):
        next(svc_gen)

    ctrl = tmp_path / "gw0" / "ctrl"
    ctrl.parent.mkdir(parents=True, exist_ok=True)
    ctrl.write_text("owner1", encoding="utf-8")
    req.session.config.stash = {_RUNTIME_STASH_KEY: runtime_cfg}
    del req.session.config.workerinput
    hook_gen = pytest_sessionfinish(req.session, 0)
    next(hook_gen)
    with pytest.raises(StopIteration):
        hook_gen.send(None)

    def _bad_resolve(*_a: object, **_kw: object) -> None:
        msg = "no runtime"
        raise RuntimeResolutionError(msg)

    req.session.config.stash = {}
    monkeypatch.setattr("pytest_databases._service.resolve_container_runtime", _bad_resolve)
    with pytest.warns(RuntimeWarning, match="could not clean up session containers"):
        _cleanup_session_containers(req.session, ctrl)

    registered_fns: list[Any] = []
    monkeypatch.setattr("pytest_databases._service.atexit.register", registered_fns.append)
    _REGISTERED_ATEXIT_OWNERS.discard("atexit_owner")
    _COMPLETED_SESSION_OWNERS.discard("atexit_owner")
    _register_atexit_cleanup("atexit_owner", runtime_cfg, req.session.config)
    _register_atexit_cleanup("atexit_owner", runtime_cfg, req.session.config)
    assert len(registered_fns) == 1
    registered_fns[0]()


def test_s3_ensure_bucket_status_retry_and_error(monkeypatch: pytest.MonkeyPatch) -> None:
    """Verify ensure_bucket retries HTTP 503 response status and raises RuntimeError on unexpected status."""
    monkeypatch.setattr("pytest_databases._s3.time.sleep", lambda _s: None)
    statuses = iter([503, 200])

    class _FakeResp:
        def __init__(self, status: int) -> None:
            self.status = status

        def __enter__(self) -> Self:
            return self

        def __exit__(self, *_a: object) -> None:
            pass

    monkeypatch.setattr("pytest_databases._s3.urlopen", lambda *_a, **_kw: _FakeResp(next(statuses)))
    create_s3_bucket(
        "http://127.0.0.1:9000",
        "mybucket",
        access_key="ak",
        secret_key="sk",
    )

    monkeypatch.setattr("pytest_databases._s3.urlopen", lambda *_a, **_kw: _FakeResp(500))
    with pytest.raises(RuntimeError, match="HTTP 500"):
        create_s3_bucket(
            "http://127.0.0.1:9000",
            "mybucket",
            access_key="ak",
            secret_key="sk",
        )
