"""Valkey container service fixtures."""

from __future__ import annotations

import dataclasses
from contextlib import contextmanager
from typing import TYPE_CHECKING

import pytest

from pytest_databases.helpers import exec_output_to_bytes, get_xdist_worker_num
from pytest_databases.types import ServiceContainer, XdistIsolationLevel

if TYPE_CHECKING:
    from collections.abc import Generator

    from docker.models.containers import Container

    from pytest_databases._service import DockerService

__all__ = (
    "ValkeyService",
    "provide_valkey_service",
    "valkey_host",
    "valkey_image",
    "valkey_port",
    "valkey_service",
    "xdist_valkey_isolation_level",
)


@dataclasses.dataclass
class ValkeyService(ServiceContainer):
    """Connection metadata for a running Valkey container service."""

    db: int


@contextmanager
def provide_valkey_service(
    docker_service: DockerService,
    image: str,
    isolation_level: XdistIsolationLevel,
) -> Generator[ValkeyService, None, None]:
    """Start and yield a Valkey service container.

    Args:
        docker_service: Docker service manager.
        image: Container image name.
        isolation_level: xdist isolation mode.

    Yields:
        A configured ``ValkeyService`` instance.
    """
    worker_num = get_xdist_worker_num()
    name = "valkey"
    db = 0
    if worker_num is not None:
        if isolation_level == "database":
            container_num = worker_num // 15
            if container_num > 0:
                name += f"_{container_num + 1}"
            db = worker_num % 15
        else:
            name += f"_{worker_num + 1}"

    def _responsive(_service: ServiceContainer) -> bool:
        exit_code, output = _exec_valkey_cli(_service.container, "PING")
        return exit_code == 0 and output.strip().endswith(b"PONG")

    with docker_service.run(
        image,
        check=_responsive,
        container_port=6379,
        name=name,
        transient=isolation_level == "server",
    ) as service:
        yield ValkeyService(
            host=service.host,
            port=service.port,
            container=service.container,
            db=db,
        )


@pytest.fixture(scope="session")
def xdist_valkey_isolation_level() -> XdistIsolationLevel:
    """Return the default pytest-xdist isolation level for Valkey fixtures."""
    return "database"


@pytest.fixture(autouse=False, scope="session")
def valkey_port(valkey_service: ValkeyService) -> int:
    """Return the bound host port for the Valkey service."""
    return valkey_service.port


@pytest.fixture(autouse=False, scope="session")
def valkey_host(valkey_service: ValkeyService) -> str:
    """Return the reachable host address for the Valkey service."""
    return valkey_service.host


@pytest.fixture(autouse=False, scope="session")
def valkey_image() -> str:
    """Return the container image tag for Valkey."""
    return "valkey/valkey:latest"


@pytest.fixture(autouse=False, scope="session")
def valkey_service(
    docker_service: DockerService,
    valkey_image: str,
    xdist_valkey_isolation_level: XdistIsolationLevel,
) -> Generator[ValkeyService, None, None]:
    """Start and yield a session-scoped Valkey service container.

    Yields:
        A running ``ValkeyService`` instance.
    """
    with provide_valkey_service(docker_service, valkey_image, xdist_valkey_isolation_level) as service:
        yield service


def _exec_valkey_cli(container: Container, *args: str, db: int = 0) -> tuple[int, bytes]:
    result = container.exec_run([
        "valkey-cli",
        "-h",
        "localhost",
        "-p",
        "6379",
        "-n",
        str(db),
        *args,
    ])
    return result.exit_code if result.exit_code is not None else -1, exec_output_to_bytes(result.output)
