from __future__ import annotations

import dataclasses
from typing import TYPE_CHECKING

import pytest

from pytest_databases.helpers import get_xdist_worker_num
from pytest_databases.types import ServiceContainer, XdistIsolationLevel

if TYPE_CHECKING:
    from collections.abc import Generator, Iterator

    from docker.models.containers import Container

    from pytest_databases._service import DockerService


def _output_to_bytes(output: bytes | str | Iterator[bytes]) -> bytes:
    if isinstance(output, bytes):
        return output
    if isinstance(output, str):
        return output.encode()
    return b"".join(output)


def _exec_gizmosql(container: Container, sql: str, *, user: str, password: str) -> tuple[int, bytes]:
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
    return result.exit_code if result.exit_code is not None else -1, _output_to_bytes(result.output)


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
        exit_code, output = _exec_gizmosql(
            _service.container,
            "SELECT 1",
            user=gizmosql_username,
            password=gizmosql_password,
        )
        return exit_code == 0 and b"1" in output

    worker_num = get_xdist_worker_num()
    name = "gizmosql"
    if worker_num is not None:
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
            container=service.container,
            username=gizmosql_username,
            password=gizmosql_password,
        )
