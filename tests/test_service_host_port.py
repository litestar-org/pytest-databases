"""Tests for the ``host_port`` kwarg on ``DockerService.run`` (gh-131)."""

from __future__ import annotations

import socket
from typing import TYPE_CHECKING

import pytest
from docker.errors import APIError

if TYPE_CHECKING:
    from pytest_databases._service import DockerService


CONTAINER_IMAGE = "busybox:latest"
CONTAINER_PORT = 1234
COMMAND = f"sh -c 'nc -lk -p {CONTAINER_PORT}'"


def _pick_free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.bind(("127.0.0.1", 0))
        return sock.getsockname()[1]


def _tcp_open(_service: object) -> bool:
    host = _service.host  # type: ignore[attr-defined]
    port = _service.port  # type: ignore[attr-defined]
    try:
        with socket.create_connection((host, port), timeout=1):
            return True
    except OSError:
        return False


def test_host_port_none_uses_dynamic(docker_service: DockerService) -> None:
    with docker_service.run(
        image=CONTAINER_IMAGE,
        container_port=CONTAINER_PORT,
        name="host_port_dynamic",
        command=COMMAND,
        check=_tcp_open,
        timeout=15,
        pause=0.2,
        transient=True,
    ) as service:
        assert service.port > 0
        assert service.port != CONTAINER_PORT


def test_host_port_pinned_binds_exact(docker_service: DockerService) -> None:
    requested = _pick_free_port()
    with docker_service.run(
        image=CONTAINER_IMAGE,
        container_port=CONTAINER_PORT,
        name="host_port_pinned",
        command=COMMAND,
        check=_tcp_open,
        timeout=15,
        pause=0.2,
        transient=True,
        host_port=requested,
    ) as service:
        assert service.port == requested


def test_host_port_pinned_conflict_raises(docker_service: DockerService) -> None:
    blocker = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    blocker.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 0)
    blocker.bind(("127.0.0.1", 0))
    bound_port = blocker.getsockname()[1]
    blocker.listen(1)
    try:
        with (
            pytest.raises(APIError),
            docker_service.run(
                image=CONTAINER_IMAGE,
                container_port=CONTAINER_PORT,
                name="host_port_conflict",
                command=COMMAND,
                check=_tcp_open,
                timeout=5,
                pause=0.2,
                transient=True,
                host_port=bound_port,
            ),
        ):
            pytest.fail("DockerService.run should have raised APIError for bound host port")
    finally:
        blocker.close()
