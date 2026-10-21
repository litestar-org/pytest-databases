"""Unit tests for lock-free dynamic port retry and container creation."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any
from unittest.mock import MagicMock

import pytest
from docker.errors import APIError

from pytest_databases import ContainerService
from pytest_databases.runtime import ContainerRuntimeConfig, RuntimeType

if TYPE_CHECKING:
    from pathlib import Path


def make_service(tmp_path: Path, client: Any) -> ContainerService:
    """Construct a ContainerService instance with a mock client."""
    mock_session = MagicMock()
    mock_session.config.rootpath = tmp_path
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

    with pytest.raises(RuntimeError, match="exited prematurely with status 'exited'"), service.run(
        image="postgres:latest",
        container_port=5432,
        name="fast_fail_test",
        check=lambda _s: False,
        timeout=10,
    ):
        pass


def test_resolve_port_extracts_mapped_host_port(tmp_path: Path) -> None:
    """Ensure ContainerService.resolve_port extracts port binding."""
    mock_container = MagicMock()
    mock_container.ports = {"9020/tcp": [{"HostPort": "39020"}]}
    port = ContainerService.resolve_port(mock_container, 9020)
    assert port == 39020
