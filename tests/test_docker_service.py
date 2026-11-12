"""Unit tests for lock-free dynamic port retry, healthcheck readiness, and container capabilities."""

from __future__ import annotations

import http.server
import io
import shutil
import socket
import ssl
import subprocess
import sys
import tarfile
import threading
import urllib.error
import urllib.request
from typing import TYPE_CHECKING, Any
from unittest.mock import MagicMock

import pytest
from docker.errors import APIError, DockerException, ImageNotFound, NotFound

from pytest_databases import (
    ContainerService,
    copy_from_container,
    copy_to_container,
    create_s3_bucket,
    exec_container_command,
    send_http_request,
    should_keep_containers,
    wait_for_container_health,
)
from pytest_databases import helpers as helpers_mod
from pytest_databases._service import (
    _COMPLETED_SESSION_RUNS,
    _REGISTERED_ATEXIT_RUNS,
    _RUNTIME_STASH_KEY,
    SESSION_LOCK_DIR_ENV,
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
from pytest_databases.helpers import http_request
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
    basetemp: Path | None = None,
) -> ContainerService:
    """Construct a ContainerService instance with a mock client."""
    mock_session = MagicMock()
    mock_session.config.rootpath = tmp_path
    mock_session.config.getoption.side_effect = lambda opt, default=None: (
        keep_containers if opt == "--keep-containers" else default
    )
    mock_session.config._tmp_path_factory.getbasetemp.return_value = tmp_path if basetemp is None else basetemp
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
    """Ensure enterprise runtime kwargs including user, tmpfs, and extra_hosts are forwarded."""
    mock_client = MagicMock()
    mock_container = MagicMock()
    mock_container.status = "running"
    mock_container.ports = {"50000/tcp": [{"HostPort": "50000"}]}
    mock_client.containers.run.return_value = mock_container
    volumes = {"/host/wallet": {"bind": "/u01/app/oracle/wallets/tls_wallet", "mode": "rw"}}
    tmpfs = {"/run/scratch": "size=64m"}
    extra_hosts = {"db.internal": "127.0.0.1"}

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
        user="1001:1001",
        tmpfs=tmpfs,
        extra_hosts=extra_hosts,
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
    assert kwargs["user"] == "1001:1001"
    assert kwargs["tmpfs"] == tmpfs
    assert kwargs["extra_hosts"] == extra_hosts


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

    monkeypatch.setenv(SESSION_LOCK_DIR_ENV, str(tmp_path / "session_locks"))
    monkeypatch.setenv("PYTEST_XDIST_WORKER", "gw0")
    xdist_tmp = tmp_path / "xdist_run" / "gw0"
    xdist_tmp.mkdir(parents=True)
    xdist_service = make_service(xdist_tmp.parent, mock_client, basetemp=xdist_tmp)
    with xdist_service:
        assert (xdist_tmp.parent / "ctrl").exists()
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

    monkeypatch.setenv(SESSION_LOCK_DIR_ENV, str(tmp_path / "session_locks"))
    registered_fns: list[Any] = []
    monkeypatch.setattr("pytest_databases._service.atexit.register", registered_fns.append)
    _REGISTERED_ATEXIT_RUNS.discard(("atexit_owner", "run_1"))
    _COMPLETED_SESSION_RUNS.discard(("atexit_owner", "run_1"))
    _register_atexit_cleanup("atexit_owner", "run_1", runtime_cfg, req.session.config)
    _register_atexit_cleanup("atexit_owner", "run_1", runtime_cfg, req.session.config)
    assert len(registered_fns) == 1
    registered_fns[0]()


def test_exec_after_start_runs_once_across_xdist_workers_and_checks_exit_code(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    """Verify exec_after_start runs once per container across xdist workers and rejects non-zero exit status."""
    monkeypatch.setenv(SESSION_LOCK_DIR_ENV, str(tmp_path / "session_locks"))
    shared_container = MagicMock(id="abcdef0123456789", status="running", ports={"5432/tcp": [{"HostPort": "35432"}]})
    shared_container.exec_run.return_value = (0, b"bootstrapped")
    mock_client = MagicMock()
    mock_client.containers.list.return_value = [shared_container]

    shared_base = tmp_path / "xdist_shared"
    shared_base.mkdir()
    monkeypatch.setenv("PYTEST_XDIST_WORKER", "gw0")
    worker_0 = make_service(shared_base, mock_client)
    monkeypatch.setenv("PYTEST_XDIST_WORKER", "gw1")
    worker_1 = make_service(shared_base, mock_client)
    mock_client.containers.list.return_value = [shared_container]

    with worker_0.run(
        "postgres:latest",
        5432,
        "pg_shared",
        exec_after_start=["sh", "-c", "init.sh"],
        check=lambda _s: True,
    ):
        pass
    with worker_1.run(
        "postgres:latest",
        5432,
        "pg_shared",
        exec_after_start=["sh", "-c", "init.sh"],
        check=lambda _s: True,
    ):
        pass

    shared_container.exec_run.assert_called_once_with(["sh", "-c", "init.sh"])

    failing_container = MagicMock(id="fail000011112222", status="running", ports={"5432/tcp": [{"HostPort": "35433"}]})
    failing_container.exec_run.return_value = (2, b"permission denied")
    mock_client.containers.list.return_value = [failing_container]
    with (
        pytest.raises(RuntimeError, match="exec_after_start failed with exit code 2: permission denied"),
        worker_0.run(
            "postgres:latest",
            5432,
            "pg_fail",
            exec_after_start=["sh", "-c", "fail.sh"],
            check=lambda _s: True,
        ),
    ):
        pass


def test_copy_to_container_and_service_container_helpers(tmp_path: Path) -> None:
    """Verify copy_to_container, mkdir retry on NotFound, uid/gid/mode overrides, and exec_command."""
    script = tmp_path / "collect.sh"
    script.write_text("#!/bin/sh\necho ok\n", encoding="utf-8")

    uploaded: list[tuple[str, bytes]] = []
    mock_container = MagicMock()
    calls = 0

    def _put_archive(dest: str, data: bytes) -> bool:
        nonlocal calls
        calls += 1
        if calls == 1:
            missing_msg = "missing"
            raise NotFound(missing_msg)
        uploaded.append((dest, data))
        return True

    mock_container.put_archive.side_effect = _put_archive
    mock_container.exec_run.side_effect = [
        (0, b""),
        (0, iter([b"line1\n", b"line2\n"])),
        (0, b""),
    ]

    svc = ServiceContainer(container=mock_container, host="127.0.0.1", port=5432)
    svc.copy_to(script, "/opt/scripts", arcname="sub/run.sh", mode=0o750, uid=1000, gid=1000)

    mock_container.exec_run.assert_called_once_with(["mkdir", "-p", "/opt/scripts"])
    assert len(uploaded) == 1
    assert uploaded[0][0] == "/opt/scripts"
    with tarfile.open(fileobj=io.BytesIO(uploaded[0][1]), mode="r:*") as tar:
        member = tar.getmember("sub/run.sh")
        assert member.mode & 0o777 == 0o750
        assert member.uid == 1000
        assert member.gid == 1000
        assert member.uname == ""
        assert member.gname == ""
        extracted = tar.extractfile(member)
        assert extracted is not None
        assert extracted.read() == b"#!/bin/sh\necho ok\n"

    exit_code, output = svc.exec_command(
        ["/opt/scripts/sub/run.sh"],
        user="postgres",
        workdir="/opt/work",
        env={"A": "1"},
    )
    assert exit_code == 0
    assert output == b"line1\nline2\n"
    assert mock_container.exec_run.call_args.kwargs == {
        "user": "postgres",
        "workdir": "/opt/work",
        "environment": {"A": "1"},
    }
    assert exec_container_command(mock_container, "true") == (0, b"")


@pytest.mark.parametrize(
    ("bad_arcname", "expected_match"),
    [
        ("", "non-empty relative path"),
        ("/etc/passwd", "non-empty relative path"),
        ("../escape.sh", "parent traversal"),
        ("nested/../../escape.sh", "parent traversal"),
    ],
)
def test_copy_to_container_validation_and_error_branches(
    tmp_path: Path,
    bad_arcname: str,
    expected_match: str,
) -> None:
    """Verify copy_to_container rejects invalid paths, missing sources, mkdir failures, and rejected uploads."""
    src = tmp_path / "data.txt"
    src.write_text("payload", encoding="utf-8")
    mock_container = MagicMock()

    with pytest.raises(ValueError, match=expected_match):
        copy_to_container(mock_container, src, "/opt/work", arcname=bad_arcname)

    with pytest.raises(FileNotFoundError, match="does not exist"):
        copy_to_container(mock_container, tmp_path / "missing.txt", "/opt/work")

    with pytest.raises(ValueError, match="destination_dir"):
        copy_to_container(mock_container, src, "   ")

    mock_container.put_archive.return_value = False
    with pytest.raises(RuntimeError, match="rejected archive upload"):
        copy_to_container(mock_container, src, "/opt/work")

    mock_container.put_archive.side_effect = NotFound("missing")
    mock_container.exec_run.return_value = (1, b"read-only fs")
    with pytest.raises(RuntimeError, match="Failed to create container directory"):
        copy_to_container(mock_container, src, "/ro/dir")


def _build_test_tar(entries: list[tuple[tarfile.TarInfo, bytes | None]]) -> bytes:
    buf = io.BytesIO()
    with tarfile.open(fileobj=buf, mode="w") as tar:
        for info, data in entries:
            if data is not None:
                info.size = len(data)
                tar.addfile(info, io.BytesIO(data))
            else:
                tar.addfile(info)
    return buf.getvalue()


def test_copy_from_container_extracts_trees_and_strips_components(tmp_path: Path) -> None:
    """Verify copy_from_container extracts files, nested directories, safe relative symlinks, and strip_components."""
    dir_info = tarfile.TarInfo(name="results/")
    dir_info.type = tarfile.DIRTYPE
    file_info = tarfile.TarInfo(name="results/summary.json")
    file_info.mode = 0o640
    sub_info = tarfile.TarInfo(name="results/sub/run.sh")
    sub_info.mode = 0o755
    sym_info = tarfile.TarInfo(name="results/latest.json")
    sym_info.type = tarfile.SYMTYPE
    sym_info.linkname = "summary.json"
    archive = _build_test_tar([
        (dir_info, None),
        (file_info, b'{"ok":true}'),
        (sub_info, b"#!/bin/sh\n"),
        (sym_info, None),
    ])

    mock_container = MagicMock()
    mock_container.get_archive.return_value = (iter([archive]), {})
    svc = ServiceContainer(container=mock_container, host="127.0.0.1", port=5432)

    kept_dest = svc.copy_from("/opt/results", tmp_path / "kept", strip_components=False)
    assert (kept_dest / "results" / "summary.json").read_text(encoding="utf-8") == '{"ok":true}'
    assert (kept_dest / "results" / "latest.json").is_symlink()

    mock_container.get_archive.return_value = (iter([archive]), {})
    stripped_dest = copy_from_container(mock_container, "/opt/results", tmp_path / "stripped", strip_components=True)
    assert (stripped_dest / "summary.json").read_text(encoding="utf-8") == '{"ok":true}'
    assert ((stripped_dest / "sub" / "run.sh").stat().st_mode & 0o111) != 0


@pytest.mark.parametrize(
    ("member_name", "member_type", "linkname", "expected_match"),
    [
        ("../outside.txt", tarfile.REGTYPE, "", "traversal"),
        ("/etc/shadow", tarfile.REGTYPE, "", "absolute"),
        ("dir/../../escape.txt", tarfile.REGTYPE, "", "traversal"),
        ("safe/link", tarfile.SYMTYPE, "/etc/passwd", "absolute link target"),
        ("safe/link", tarfile.SYMTYPE, "../../outside.txt", "escaping destination"),
        ("safe/fifo", tarfile.FIFOTYPE, "", "Unsupported special archive entry"),
    ],
)
def test_copy_from_container_rejects_unsafe_members(
    tmp_path: Path,
    member_name: str,
    member_type: bytes,
    linkname: str,
    expected_match: str,
) -> None:
    """Verify copy_from_container rejects traversal paths, escaping links, and special archive entries."""
    info = tarfile.TarInfo(name=member_name)
    info.type = member_type
    info.linkname = linkname
    payload = b"bad" if member_type == tarfile.REGTYPE else None
    mock_container = MagicMock()
    mock_container.get_archive.return_value = ([_build_test_tar([(info, payload)])], {})

    with pytest.raises(ValueError, match=expected_match):
        copy_from_container(mock_container, "/opt/out", tmp_path / "extract")


def _start_loopback_http_server(
    responses: list[tuple[int, dict[str, str], bytes]],
    *,
    ssl_context: ssl.SSLContext | None = None,
) -> tuple[http.server.ThreadingHTTPServer, list[tuple[str, str, dict[str, str]]]]:
    recorded: list[tuple[str, str, dict[str, str]]] = []
    remaining = list(responses)

    class _Handler(http.server.BaseHTTPRequestHandler):
        def _handle(self) -> None:
            length = int(self.headers.get("Content-Length", "0"))
            if length:
                self.rfile.read(length)
            recorded.append((self.command, self.path, dict(self.headers.items())))
            status, headers, body = remaining.pop(0) if remaining else (200, {}, b"")
            self.send_response(status)
            for key, value in headers.items():
                self.send_header(key, value)
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            if body:
                self.wfile.write(body)

        def do_GET(self) -> None:
            self._handle()

        def do_PUT(self) -> None:
            self._handle()

        def log_request(self, code: int | str = "-", size: int | str = "-") -> None:
            return

    server = http.server.ThreadingHTTPServer(("127.0.0.1", 0), _Handler)
    if ssl_context is not None:
        server.socket = ssl_context.wrap_socket(server.socket, server_side=True)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    return server, recorded


def _create_self_signed_tls_context(tmp_path: Path) -> ssl.SSLContext:
    cert_path = tmp_path / "cert.pem"
    key_path = tmp_path / "key.pem"
    openssl_bin = shutil.which("openssl")
    assert openssl_bin is not None
    subprocess.run(
        [
            openssl_bin,
            "req",
            "-x509",
            "-newkey",
            "rsa:2048",
            "-nodes",
            "-keyout",
            str(key_path),
            "-out",
            str(cert_path),
            "-days",
            "1",
            "-subj",
            "/CN=127.0.0.1",
        ],
        check=True,
        capture_output=True,
    )
    server_ctx = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
    server_ctx.load_cert_chain(certfile=str(cert_path), keyfile=str(key_path))
    return server_ctx


def _unused_loopback_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.bind(("127.0.0.1", 0))
        return int(sock.getsockname()[1])


def test_s3_ensure_bucket_status_retry_and_error(monkeypatch: pytest.MonkeyPatch) -> None:
    """Verify create_s3_bucket retries HTTP 503 responses and raises RuntimeError on unexpected status."""
    monkeypatch.setenv("HTTP_PROXY", "http://127.0.0.1:1")
    monkeypatch.setattr("pytest_databases.helpers.time.sleep", lambda _s: None)
    server, recorded = _start_loopback_http_server([
        (503, {}, b""),
        (200, {}, b""),
        (500, {}, b""),
    ])
    try:
        endpoint = f"http://127.0.0.1:{server.server_address[1]}"
        assert (
            create_s3_bucket(
                endpoint,
                "mybucket",
                access_key="ak",
                secret_key="sk",
            )
            is True
        )
        assert len(recorded) == 2

        with pytest.raises(RuntimeError, match="HTTP 500"):
            create_s3_bucket(
                endpoint,
                "mybucket",
                access_key="ak",
                secret_key="sk",
            )
    finally:
        server.shutdown()
        server.server_close()


def test_send_http_request_bypasses_proxies_and_preserves_headers(monkeypatch: pytest.MonkeyPatch) -> None:
    """Verify send_http_request ignores ambient proxies, captures error headers, and preserves Request instances."""
    monkeypatch.setenv("HTTP_PROXY", "http://127.0.0.1:1")
    monkeypatch.setenv("HTTPS_PROXY", "http://127.0.0.1:1")
    monkeypatch.setenv("ALL_PROXY", "http://127.0.0.1:1")
    server, recorded = _start_loopback_http_server([
        (200, {"X-Probe": "ok"}, b"ready"),
        (409, {"x-ms-error-code": "ContainerAlreadyExists"}, b"<Error/>"),
    ])
    try:
        port = server.server_address[1]
        status, headers, body = send_http_request(f"http://127.0.0.1:{port}/ping")
        assert status == 200
        assert {k.lower(): v for k, v in headers.items()}["x-probe"] == "ok"
        assert body == b"ready"

        req = urllib.request.Request(
            f"http://127.0.0.1:{port}/c1?restype=container",
            method="PUT",
            headers={"Content-Length": "0"},
        )
        err_status, err_headers, err_body = send_http_request(req)
        assert err_status == 409
        assert {k.lower(): v for k, v in err_headers.items()}["x-ms-error-code"] == "ContainerAlreadyExists"
        assert err_body == b"<Error/>"
        lower_headers = {k.lower(): v for k, v in recorded[1][2].items()}
        assert lower_headers.get("content-length") == "0"
        assert "content-type" not in lower_headers
    finally:
        server.shutdown()
        server.server_close()


def test_http_request_custom_ssl_context_bypasses_https_proxy(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    """Verify http_request honors ssl_context over HTTPS while ignoring HTTPS_PROXY."""
    monkeypatch.setenv("HTTPS_PROXY", "http://127.0.0.1:1")
    server_ctx = _create_self_signed_tls_context(tmp_path)
    server, _recorded = _start_loopback_http_server([(200, {}, b"tls-ok")], ssl_context=server_ctx)
    client_ctx = ssl.create_default_context()
    client_ctx.check_hostname = False
    client_ctx.verify_mode = ssl.CERT_NONE
    try:
        port = server.server_address[1]
        status, body = http_request(f"https://127.0.0.1:{port}/health", ssl_context=client_ctx)
        assert (status, body) == (200, b"tls-ok")
    finally:
        server.shutdown()
        server.server_close()


@pytest.mark.parametrize(
    ("raw_url", "wrap_request", "override_ftp", "kwargs"),
    [
        ("ftp://example.com/resource", False, False, {}),
        ("http://127.0.0.1:9/p", True, False, {"headers": {"X": "1"}}),
        ("http://127.0.0.1:9/p", True, False, {"data": b"payload"}),
        ("http://127.0.0.1:9/p", True, True, {}),
    ],
)
def test_send_http_request_validation_errors(
    raw_url: str, wrap_request: bool, override_ftp: bool, kwargs: dict[str, Any]
) -> None:
    """Verify send_http_request rejects non-HTTP schemes and Request + override kwargs."""
    if wrap_request:
        req = urllib.request.Request("http://127.0.0.1:9/p")
        if override_ftp:
            req.full_url = "ftp://example.com/resource"
        target: str | urllib.request.Request = req
    else:
        target = raw_url
    with pytest.raises(ValueError):
        send_http_request(target, **kwargs)


def test_send_http_request_propagates_transport_errors(monkeypatch: pytest.MonkeyPatch) -> None:
    """Verify connection failures propagate from send_http_request without being swallowed."""
    monkeypatch.setenv("HTTP_PROXY", "http://127.0.0.1:1")
    closed_port = _unused_loopback_port()
    with pytest.raises((urllib.error.URLError, OSError)):
        send_http_request(f"http://127.0.0.1:{closed_port}/ping", timeout=1.0)


@pytest.mark.parametrize("first_module", ["pytest_databases", "pytest_databases.helpers"])
def test_public_http_and_s3_exports_acyclic(first_module: str) -> None:
    """Verify send_http_request and create_s3_bucket export identically without circular imports."""
    assert create_s3_bucket is helpers_mod.create_s3_bucket
    assert send_http_request is helpers_mod.send_http_request
    assert "create_s3_bucket" in helpers_mod.__all__
    assert "send_http_request" in helpers_mod.__all__

    script = (
        f"import {first_module}, pytest_databases, pytest_databases.helpers; "
        "assert pytest_databases.create_s3_bucket is pytest_databases.helpers.create_s3_bucket; "
        "assert pytest_databases.send_http_request is pytest_databases.helpers.send_http_request"
    )
    proc = subprocess.run([sys.executable, "-c", script], check=False, capture_output=True, text=True)
    assert proc.returncode == 0, proc.stderr
