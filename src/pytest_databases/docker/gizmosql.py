"""GizmoSQL (Apache Arrow Flight SQL with DuckDB/SQLite backends) container service fixtures."""

from __future__ import annotations

import contextlib
import dataclasses
import importlib
import warnings
from typing import TYPE_CHECKING, Any, Literal

import pytest

from pytest_databases.helpers import exec_output_to_bytes, get_xdist_worker_num
from pytest_databases.types import ServiceContainer, XdistIsolationLevel

if TYPE_CHECKING:
    from collections.abc import Generator

    from docker.models.containers import Container

    from pytest_databases._service import DockerService

__all__ = (
    "TLS_SKIP_VERIFY_OPTION",
    "GizmoSQLBackend",
    "GizmoSQLService",
    "exec_gizmosql",
    "gizmosql_connection",
    "gizmosql_duckdb_service",
    "gizmosql_image",
    "gizmosql_password",
    "gizmosql_service",
    "gizmosql_sqlite_service",
    "gizmosql_username",
    "provide_deprecated_gizmosql_connection",
    "provide_gizmosql_service",
    "xdist_gizmosql_isolation_level",
)

GizmoSQLBackend = Literal["duckdb", "sqlite"]
TLS_SKIP_VERIFY_OPTION = "adbc.flight.sql.client_option.tls_skip_verify"


@dataclasses.dataclass
class GizmoSQLService(ServiceContainer):
    """Service container for GizmoSQL database.

    GizmoSQL is a high-performance SQL server built on Apache Arrow Flight SQL
    with DuckDB/SQLite backends. The server always runs with TLS enabled using
    auto-generated self-signed certificates.
    """

    username: str
    password: str
    backend: GizmoSQLBackend = "duckdb"

    @property
    def uri(self) -> str:
        """The gRPC+TLS URI for connecting to the service."""
        return f"grpc+tls://{self.host}:{self.port}"

    @property
    def connection_kwargs(self) -> dict[str, str]:
        """Standard ADBC Flight SQL ``db_kwargs`` for connecting to the service."""
        return {
            "username": self.username,
            "password": self.password,
            TLS_SKIP_VERIFY_OPTION: "true",
        }


def exec_gizmosql(container: Container, sql: str, *, user: str, password: str) -> tuple[int, bytes]:
    """Execute a SQL statement inside a GizmoSQL container using ``gizmosql_client``.

    Args:
        container: Running GizmoSQL container.
        sql: SQL statement to execute.
        user: Username for Flight SQL authentication.
        password: Password for Flight SQL authentication.

    Returns:
        Tuple of ``(exit_code, raw_output_bytes)``.
    """
    result = container.exec_run(
        [
            "gizmosql_client",
            "--host",
            "localhost",
            "--port",
            "31337",
            "--username",
            user,
            "--tls",
            "--tls-skip-verify",
            "--command",
            sql,
        ],
        environment={"GIZMOSQL_PASSWORD": password},
    )
    return result.exit_code if result.exit_code is not None else -1, exec_output_to_bytes(result.output)


@contextlib.contextmanager
def provide_gizmosql_service(
    docker_service: DockerService,
    isolation_level: XdistIsolationLevel,
    image: str,
    username: str,
    password: str,
    backend: GizmoSQLBackend,
) -> Generator[GizmoSQLService, None, None]:
    """Start and yield a GizmoSQL container configured for a specific backend.

    Args:
        docker_service: Container lifecycle manager.
        isolation_level: ``pytest-xdist`` isolation level.
        image: Container image tag.
        username: Flight SQL username.
        password: Flight SQL password.
        backend: Embedded storage backend (``"duckdb"`` or ``"sqlite"``).

    Yields:
        A running ``GizmoSQLService`` instance.
    """

    def check(_service: ServiceContainer) -> bool:
        exit_code, output = exec_gizmosql(
            _service.container,
            "SELECT 1",
            user=username,
            password=password,
        )
        return exit_code == 0 and b"1" in output

    worker_num = get_xdist_worker_num()
    name = f"gizmosql-{backend}"
    if worker_num is not None and isolation_level == "server":
        name += f"_{worker_num}"

    env: dict[str, str] = {
        "DATABASE_BACKEND": backend,
        "GIZMOSQL_PASSWORD": password,
        "GIZMOSQL_USERNAME": username,
    }

    with docker_service.run(
        image=image,
        check=check,
        container_port=31337,
        name=name,
        env=env,
        timeout=90,
        pause=1.0,
        transient=isolation_level == "server",
    ) as service:
        yield GizmoSQLService(
            host=service.host,
            port=service.port,
            container=service.container,
            username=username,
            password=password,
            backend=backend,
        )


def provide_deprecated_gizmosql_connection(
    service: GizmoSQLService,
) -> Generator[Any, None, None]:
    """Yield a deprecated ADBC Flight SQL connection while emitting a ``DeprecationWarning``.

    Args:
        service: Running ``GizmoSQLService`` instance.

    Yields:
        An active ADBC Flight SQL DBAPI connection.
    """
    warnings.warn(
        "The 'gizmosql_connection' fixture is deprecated and will be removed in a future release. "
        "Use 'gizmosql_service' (or 'gizmosql_duckdb_service' / 'gizmosql_sqlite_service') instead.",
        DeprecationWarning,
        stacklevel=2,
    )
    flightsql = importlib.import_module("adbc_driver_flightsql.dbapi")
    with flightsql.connect(
        uri=service.uri,
        db_kwargs=service.connection_kwargs,
        autocommit=True,
    ) as conn:
        yield conn


@pytest.fixture(scope="session")
def xdist_gizmosql_isolation_level() -> XdistIsolationLevel:
    """Return the default pytest-xdist isolation level for GizmoSQL."""
    return "database"


@pytest.fixture(scope="session")
def gizmosql_image() -> str:
    """Return the container image tag for GizmoSQL."""
    return "gizmodata/gizmosql:latest"


@pytest.fixture(scope="session")
def gizmosql_username() -> str:
    """Return the default username for GizmoSQL."""
    return "gizmosql_username"


@pytest.fixture(scope="session")
def gizmosql_password() -> str:
    """Return the default password for GizmoSQL."""
    return "gizmosql_password"


@pytest.fixture(autouse=False, scope="session")
def gizmosql_duckdb_service(
    docker_service: DockerService,
    xdist_gizmosql_isolation_level: XdistIsolationLevel,
    gizmosql_image: str,
    gizmosql_username: str,
    gizmosql_password: str,
) -> Generator[GizmoSQLService, None, None]:
    """Provide a GizmoSQL service configured with the DuckDB backend.

    Yields:
        A DuckDB-backed ``GizmoSQLService``.
    """
    with provide_gizmosql_service(
        docker_service=docker_service,
        isolation_level=xdist_gizmosql_isolation_level,
        image=gizmosql_image,
        username=gizmosql_username,
        password=gizmosql_password,
        backend="duckdb",
    ) as service:
        yield service


@pytest.fixture(autouse=False, scope="session")
def gizmosql_sqlite_service(
    docker_service: DockerService,
    xdist_gizmosql_isolation_level: XdistIsolationLevel,
    gizmosql_image: str,
    gizmosql_username: str,
    gizmosql_password: str,
) -> Generator[GizmoSQLService, None, None]:
    """Provide a GizmoSQL service configured with the SQLite backend.

    Yields:
        A SQLite-backed ``GizmoSQLService``.
    """
    with provide_gizmosql_service(
        docker_service=docker_service,
        isolation_level=xdist_gizmosql_isolation_level,
        image=gizmosql_image,
        username=gizmosql_username,
        password=gizmosql_password,
        backend="sqlite",
    ) as service:
        yield service


@pytest.fixture(autouse=False, scope="session")
def gizmosql_service(gizmosql_duckdb_service: GizmoSQLService) -> GizmoSQLService:
    """Provide the default DuckDB-backed GizmoSQL service."""
    return gizmosql_duckdb_service


@pytest.fixture(autouse=False, scope="session")
def gizmosql_connection(gizmosql_service: GizmoSQLService) -> Generator[Any, None, None]:
    """Yield a deprecated ADBC Flight SQL connection connected to ``gizmosql_service``.

    Yields:
        An active ADBC Flight SQL DBAPI connection.
    """
    yield from provide_deprecated_gizmosql_connection(gizmosql_service)
