"""Hardcharger (DuckDB analytics server speaking Chargewire) container service fixtures."""

from __future__ import annotations

import contextlib
import dataclasses
from typing import TYPE_CHECKING

import pytest
from docker.errors import APIError, NotFound

from pytest_databases.helpers import exec_output_to_bytes, get_xdist_worker_num, tcp_port_open
from pytest_databases.types import ServiceContainer, XdistIsolationLevel

if TYPE_CHECKING:
    from collections.abc import Generator

    from docker.models.containers import Container

    from pytest_databases._service import DockerService

__all__ = (
    "HARDCHARGER_PORT",
    "HardchargerService",
    "exec_hardcharger",
    "hardcharger_image",
    "hardcharger_password",
    "hardcharger_service",
    "hardcharger_username",
    "provide_hardcharger_service",
    "xdist_hardcharger_isolation_level",
)

HARDCHARGER_PORT = 31337
"""The port the Hardcharger server listens on inside the container."""


@dataclasses.dataclass
class HardchargerService(ServiceContainer):
    """Service container for Hardcharger.

    Hardcharger is an analytics server built on DuckDB. Clients talk to it over Chargewire, an HTTP protocol that
    carries results as Apache Arrow. The container serves plain HTTP (no TLS) and keeps its database in memory, so
    every new container starts empty.
    """

    username: str
    password: str

    @property
    def uri(self) -> str:
        """The ``hardcharger://`` URI for connecting to the service without TLS."""
        return f"hardcharger://{self.host}:{self.port}?tls=false"

    @property
    def connection_kwargs(self) -> dict[str, str]:
        """ADBC ``db_kwargs`` (the administrator's user name and password) for connecting to the service."""
        return {
            "username": self.username,
            "password": self.password,
        }


def exec_hardcharger(container: Container, sql: str, *, user: str, password: str) -> tuple[int, bytes]:
    """Execute SQL inside a Hardcharger container using the bundled ``hardcharger`` command-line client.

    The client prints results as CSV with a header row and exits non-zero when a statement fails.

    Args:
        container: Running Hardcharger container.
        sql: SQL to execute; several statements may be separated by semicolons.
        user: User name to sign in with.
        password: Password to sign in with.

    Returns:
        Tuple of ``(exit_code, raw_output_bytes)``. The exit code is ``-1`` when the command could not be started.
    """
    try:
        result = container.exec_run(
            [
                "hardcharger",
                "--host",
                "127.0.0.1",
                "--port",
                str(HARDCHARGER_PORT),
                "--no-tls",
                "--username",
                user,
                "--no-init",
                "--quiet",
                "--csv",
                "--command",
                sql,
            ],
            environment={"HARDCHARGER_PASSWORD": password},
        )
    except (APIError, NotFound) as exc:
        return -1, str(exc).encode()
    exit_code = result.exit_code if result.exit_code is not None else -1
    return exit_code, exec_output_to_bytes(result.output)


@contextlib.contextmanager
def provide_hardcharger_service(
    docker_service: DockerService,
    isolation_level: XdistIsolationLevel,
    image: str,
    username: str,
    password: str,
) -> Generator[HardchargerService, None, None]:
    """Start and yield a Hardcharger container.

    The server's in-memory DuckDB database cannot be split into independent databases per worker, so under
    ``pytest-xdist`` every worker gets its own container regardless of ``isolation_level``. ``isolation_level`` only
    decides whether the container is removed when the fixture is torn down (``server``) or kept until the session's
    containers are cleaned up (``database``).

    Args:
        docker_service: Container lifecycle manager.
        isolation_level: ``pytest-xdist`` isolation level.
        image: Container image tag.
        username: The administrator's user name.
        password: The administrator's password.

    Yields:
        A running ``HardchargerService`` instance.
    """

    def check(_service: ServiceContainer) -> bool:
        exit_code, output = exec_hardcharger(
            container=_service.container,
            sql="SELECT 4242 AS probe",
            user=username,
            password=password,
        )
        return exit_code == 0 and b"4242" in output.split() and tcp_port_open(host=_service.host, port=_service.port)

    worker_num = get_xdist_worker_num()
    name = "hardcharger"
    if worker_num is not None:
        name += f"_{worker_num}"

    with docker_service.run(
        image=image,
        check=check,
        container_port=HARDCHARGER_PORT,
        name=name,
        env={
            "HARDCHARGER_ADMIN_USERNAME": username,
            "HARDCHARGER_ADMIN_PASSWORD": password,
        },
        timeout=60,
        pause=0.5,
        transient=isolation_level == "server",
    ) as service:
        yield HardchargerService(
            host=service.host,
            port=service.port,
            container=service.container,
            username=username,
            password=password,
        )


@pytest.fixture(scope="session")
def xdist_hardcharger_isolation_level() -> XdistIsolationLevel:
    """Return the default pytest-xdist isolation level for Hardcharger."""
    return "database"


@pytest.fixture(scope="session")
def hardcharger_image() -> str:
    """Return the container image tag for Hardcharger."""
    return "ghcr.io/gizmodata/hardcharger:latest"


@pytest.fixture(scope="session")
def hardcharger_username() -> str:
    """Return the default administrator user name for Hardcharger."""
    return "hardcharger_username"


@pytest.fixture(scope="session")
def hardcharger_password() -> str:
    """Return the default administrator password for Hardcharger."""
    return "hardcharger_password"


@pytest.fixture(autouse=False, scope="session")
def hardcharger_service(
    docker_service: DockerService,
    xdist_hardcharger_isolation_level: XdistIsolationLevel,
    hardcharger_image: str,
    hardcharger_username: str,
    hardcharger_password: str,
) -> Generator[HardchargerService, None, None]:
    """Provide a running Hardcharger service.

    Yields:
        A ``HardchargerService`` instance.
    """
    with provide_hardcharger_service(
        docker_service=docker_service,
        isolation_level=xdist_hardcharger_isolation_level,
        image=hardcharger_image,
        username=hardcharger_username,
        password=hardcharger_password,
    ) as service:
        yield service
