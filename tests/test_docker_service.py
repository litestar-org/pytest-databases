"""Unit tests for lock-free dynamic port retry, healthcheck readiness, and container capabilities."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any
from unittest.mock import MagicMock

import pytest
from docker.errors import APIError

from pytest_databases import ContainerService, should_keep_containers, wait_for_container_health
from pytest_databases.runtime import ContainerRuntimeConfig, RuntimeType

if TYPE_CHECKING:
    from pathlib import Path

    from _pytest.monkeypatch import MonkeyPatch


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
    mock_container = MagicMock()
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


def test_wait_for_health_succeeds_when_healthy(tmp_path: Path) -> None:
    """Ensure wait_for_health=True polls State.Health.Status until healthy."""
    mock_client = MagicMock()
    mock_container = MagicMock()
    mock_container.status = "running"
    mock_container.ports = {"5432/tcp": [{"HostPort": "32801"}]}

    states = [
        {"Status": "running", "Health": {"Status": "starting", "Log": []}},
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
    """Ensure shm_size, entrypoint, privileged, ipc_mode, cap_add, devices, and hostname are forwarded."""
    mock_client = MagicMock()
    mock_container = MagicMock()
    mock_container.status = "running"
    mock_container.ports = {"50000/tcp": [{"HostPort": "50000"}]}
    mock_client.containers.run.return_value = mock_container

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


def test_should_keep_containers_respects_env_and_cli(tmp_path: Path, monkeypatch: MonkeyPatch) -> None:
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
