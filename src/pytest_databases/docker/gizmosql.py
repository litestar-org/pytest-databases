from __future__ import annotations

import dataclasses
from typing import TYPE_CHECKING

import pytest
from adbc_driver_flightsql import DatabaseOptions
from adbc_driver_flightsql import dbapi as flightsql

from pytest_databases.helpers import get_xdist_worker_num
from pytest_databases.types import ServiceContainer, XdistIsolationLevel

if TYPE_CHECKING:
    from collections.abc import Generator

    from pytest_databases._service import DockerService


@dataclasses.dataclass
class GizmoSQLService(ServiceContainer):
    """Service container for GizmoSQL database.

    GizmoSQL is a high-performance SQL server built on Apache Arrow Flight SQL
    with DuckDB/SQLite backends. The server always runs with TLS enabled using
    auto-generated self-signed certificates.
    """

    username: str
    password: str

    @property
    def uri(self) -> str:
        """Return the gRPC+TLS URI for connecting to the service.

        GizmoSQL always runs with TLS enabled.
        """
        return f"grpc+tls://{self.host}:{self.port}"


def _make_connection_kwargs(
    username: str,
    password: str,
) -> dict[str, str]:
    """Build the db_kwargs dictionary for ADBC Flight SQL connection.

    Always includes TLS_SKIP_VERIFY since GizmoSQL uses self-signed certificates.
    """
    return {
        "username": username,
        "password": password,
        DatabaseOptions.TLS_SKIP_VERIFY.value: "true",
    }


@pytest.fixture(scope="session")
def xdist_gizmosql_isolation_level() -> XdistIsolationLevel:
    """Xdist isolation level for GizmoSQL.

    Note: For xdist parallel testing, only 'server' isolation is recommended
    because DuckDB/SQLite backends don't support multiple databases per instance.
    Override this fixture to return 'server' when using pytest-xdist.
    """
    return "database"


@pytest.fixture(scope="session")
def gizmosql_image() -> str:
    """Docker image for GizmoSQL."""
    return "gizmodata/gizmosql:latest"


@pytest.fixture(scope="session")
def gizmosql_username() -> str:
    """Default username for GizmoSQL."""
    return "gizmosql_username"


@pytest.fixture(scope="session")
def gizmosql_password() -> str:
    """Default password for GizmoSQL."""
    return "gizmosql_password"


@pytest.fixture(autouse=False, scope="session")
def gizmosql_service(
    docker_service: DockerService,
    xdist_gizmosql_isolation_level: XdistIsolationLevel,
    gizmosql_image: str,
    gizmosql_username: str,
    gizmosql_password: str,
) -> Generator[GizmoSQLService, None, None]:
    def check(_service: ServiceContainer) -> bool:
        """Health check using ADBC Flight SQL connection."""
        try:
            uri = f"grpc+tls://{_service.host}:{_service.port}"
            db_kwargs = _make_connection_kwargs(gizmosql_username, gizmosql_password)

            with flightsql.connect(uri=uri, db_kwargs=db_kwargs, autocommit=True) as conn, conn.cursor() as cur:
                cur.execute("SELECT 1")
                result = cur.fetchone()
                return result is not None and result[0] == 1
        except Exception:  # noqa: BLE001
            return False

    worker_num = get_xdist_worker_num()
    name = "gizmosql"
    if worker_num is not None:
        # Only server isolation is supported for GizmoSQL (DuckDB doesn't support multiple DBs)
        name += f"_{worker_num}"

    env: dict[str, str] = {
        "GIZMOSQL_PASSWORD": gizmosql_password,
        "GIZMOSQL_USERNAME": gizmosql_username,
    }

    with docker_service.run(
        image=gizmosql_image,
        check=check,
        container_port=31337,
        name=name,
        env=env,
        timeout=90,
        pause=1.0,
        transient=xdist_gizmosql_isolation_level == "server",
    ) as service:
        yield GizmoSQLService(
            host=service.host,
            port=service.port,
            username=gizmosql_username,
            password=gizmosql_password,
        )


@pytest.fixture(autouse=False, scope="session")
def gizmosql_connection(
    gizmosql_service: GizmoSQLService,
) -> Generator[flightsql.Connection, None, None]:
    db_kwargs = _make_connection_kwargs(
        gizmosql_service.username,
        gizmosql_service.password,
    )
    with flightsql.connect(
        uri=gizmosql_service.uri,
        db_kwargs=db_kwargs,
        autocommit=True,
    ) as conn:
        yield conn
