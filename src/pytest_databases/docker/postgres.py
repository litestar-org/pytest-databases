from __future__ import annotations

import dataclasses
import os
import time
from contextlib import contextmanager
from typing import TYPE_CHECKING

import pytest

from pytest_databases.helpers import get_xdist_worker_num
from pytest_databases.types import ServiceContainer, XdistIsolationLevel

if TYPE_CHECKING:
    from collections.abc import Generator, Iterator

    from docker.models.containers import Container

    from pytest_databases._service import DockerService


def _make_connection_string(host: str, port: int, user: str, password: str, database: str) -> str:
    return f"dbname={database} user={user} host={host} port={port} password={password}"


def _output_to_bytes(output: bytes | str | Iterator[bytes]) -> bytes:
    if isinstance(output, bytes):
        return output
    if isinstance(output, str):
        return output.encode()
    return b"".join(output)


def _exec_psql(
    container: Container,
    *,
    user: str,
    password: str,
    database: str,
    sql: str,
    tuples_only: bool = False,
) -> tuple[int, bytes]:
    cmd = ["psql", "-v", "ON_ERROR_STOP=1", "-h", "localhost", "-p", "5432", "-U", user, "-d", database]
    if tuples_only:
        cmd.extend(["-tAc", sql])
    else:
        cmd.extend(["-c", sql])
    result = container.exec_run(cmd, environment={"PGPASSWORD": password})
    return result.exit_code if result.exit_code is not None else -1, _output_to_bytes(result.output)


def _create_worker_database(
    container: Container,
    *,
    user: str,
    password: str,
    db_name: str,
) -> None:
    last_output = b""
    for _ in range(10):
        exit_code, output = _exec_psql(
            container,
            user=user,
            password=password,
            database="postgres",
            sql=f"CREATE DATABASE {db_name};",
        )
        if exit_code == 0 or b"already exists" in output:
            break
        last_output = output
        time.sleep(0.5)
    else:
        message = (
            f"CREATE DATABASE {db_name!r} failed after 10 attempts: "
            f"{last_output.decode(errors='replace').strip()}"
        )
        raise RuntimeError(message)
    exit_code, output = _exec_psql(
        container,
        user=user,
        password=password,
        database=db_name,
        sql="SELECT 1",
        tuples_only=True,
    )
    if exit_code != 0 or output.strip() != b"1":
        message = (
            f"Verification SELECT against {db_name!r} failed: "
            f"{output.decode(errors='replace').strip()}"
        )
        raise RuntimeError(message)


@pytest.fixture(scope="session")
def xdist_postgres_isolation_level() -> XdistIsolationLevel:
    return "database"


@dataclasses.dataclass
class PostgresService(ServiceContainer):
    database: str
    password: str
    user: str


@pytest.fixture(autouse=False, scope="session")
def postgres_host() -> str:
    return os.environ.get("POSTGRES_HOST", "127.0.0.1")


@pytest.fixture(autouse=False, scope="session")
def postgres_password() -> str:
    return "super-secret"


@pytest.fixture(autouse=False, scope="session")
def postgres_user() -> str:
    return "postgres"


@pytest.fixture(autouse=False, scope="session")
def postgres_port() -> int | None:
    value = os.environ.get("POSTGRES_PORT")
    return int(value) if value else None


@pytest.fixture(autouse=False, scope="session")
def postgres_11_port() -> int | None:
    value = os.environ.get("POSTGRES_11_PORT")
    return int(value) if value else None


@pytest.fixture(autouse=False, scope="session")
def postgres_12_port() -> int | None:
    value = os.environ.get("POSTGRES_12_PORT")
    return int(value) if value else None


@pytest.fixture(autouse=False, scope="session")
def postgres_13_port() -> int | None:
    value = os.environ.get("POSTGRES_13_PORT")
    return int(value) if value else None


@pytest.fixture(autouse=False, scope="session")
def postgres_14_port() -> int | None:
    value = os.environ.get("POSTGRES_14_PORT")
    return int(value) if value else None


@pytest.fixture(autouse=False, scope="session")
def postgres_15_port() -> int | None:
    value = os.environ.get("POSTGRES_15_PORT")
    return int(value) if value else None


@pytest.fixture(autouse=False, scope="session")
def postgres_16_port() -> int | None:
    value = os.environ.get("POSTGRES_16_PORT")
    return int(value) if value else None


@pytest.fixture(autouse=False, scope="session")
def postgres_17_port() -> int | None:
    value = os.environ.get("POSTGRES_17_PORT")
    return int(value) if value else None


@pytest.fixture(autouse=False, scope="session")
def postgres_18_port() -> int | None:
    value = os.environ.get("POSTGRES_18_PORT")
    return int(value) if value else None


@contextmanager
def _provide_postgres_service(
    docker_service: DockerService,
    image: str,
    name: str,
    host: str,
    user: str,
    password: str,
    xdist_postgres_isolate: XdistIsolationLevel,
    host_port: int | None = None,
) -> Generator[PostgresService, None, None]:
    def check(_service: ServiceContainer) -> bool:
        exit_code, output = _exec_psql(
            _service.container,
            user=user,
            password=password,
            database="postgres",
            sql="SELECT 1",
            tuples_only=True,
        )
        return exit_code == 0 and output.strip() == b"1"

    worker_num = get_xdist_worker_num()
    db_name = "pytest_databases"
    if worker_num is not None:
        suffix = f"_{worker_num}"
        if xdist_postgres_isolate == "server":
            name += suffix
        else:
            db_name += suffix

    with docker_service.run(
        image=image,
        check=check,
        container_host=host,
        container_port=5432,
        name=name,
        env={
            "POSTGRES_PASSWORD": password,
        },
        transient=xdist_postgres_isolate == "server",
        host_port=host_port,
    ) as service:
        _create_worker_database(
            service.container,
            user=user,
            password=password,
            db_name=db_name,
        )
        yield PostgresService(
            host=service.host,
            port=service.port,
            container=service.container,
            database=db_name,
            user=user,
            password=password,
        )


@pytest.fixture(autouse=False, scope="session")
def postgres_11_service(
    docker_service: DockerService,
    xdist_postgres_isolation_level: XdistIsolationLevel,
    postgres_host: str,
    postgres_user: str,
    postgres_password: str,
    postgres_11_port: int | None,
) -> Generator[PostgresService, None, None]:
    with _provide_postgres_service(
        docker_service,
        image="postgres:11",
        name="postgres-11",
        xdist_postgres_isolate=xdist_postgres_isolation_level,
        host=postgres_host,
        user=postgres_user,
        password=postgres_password,
        host_port=postgres_11_port,
    ) as service:
        yield service


@pytest.fixture(autouse=False, scope="session")
def postgres_12_service(
    docker_service: DockerService,
    xdist_postgres_isolation_level: XdistIsolationLevel,
    postgres_host: str,
    postgres_user: str,
    postgres_password: str,
    postgres_12_port: int | None,
) -> Generator[PostgresService, None, None]:
    with _provide_postgres_service(
        docker_service,
        image="postgres:12",
        name="postgres-12",
        xdist_postgres_isolate=xdist_postgres_isolation_level,
        host=postgres_host,
        user=postgres_user,
        password=postgres_password,
        host_port=postgres_12_port,
    ) as service:
        yield service


@pytest.fixture(autouse=False, scope="session")
def postgres_13_service(
    docker_service: DockerService,
    xdist_postgres_isolation_level: XdistIsolationLevel,
    postgres_host: str,
    postgres_user: str,
    postgres_password: str,
    postgres_13_port: int | None,
) -> Generator[PostgresService, None, None]:
    with _provide_postgres_service(
        docker_service,
        image="postgres:13",
        name="postgres-13",
        xdist_postgres_isolate=xdist_postgres_isolation_level,
        host=postgres_host,
        user=postgres_user,
        password=postgres_password,
        host_port=postgres_13_port,
    ) as service:
        yield service


@pytest.fixture(autouse=False, scope="session")
def postgres_14_service(
    docker_service: DockerService,
    xdist_postgres_isolation_level: XdistIsolationLevel,
    postgres_host: str,
    postgres_user: str,
    postgres_password: str,
    postgres_14_port: int | None,
) -> Generator[PostgresService, None, None]:
    with _provide_postgres_service(
        docker_service,
        image="postgres:14",
        name="postgres-14",
        xdist_postgres_isolate=xdist_postgres_isolation_level,
        host=postgres_host,
        user=postgres_user,
        password=postgres_password,
        host_port=postgres_14_port,
    ) as service:
        yield service


@pytest.fixture(autouse=False, scope="session")
def postgres_15_service(
    docker_service: DockerService,
    xdist_postgres_isolation_level: XdistIsolationLevel,
    postgres_host: str,
    postgres_user: str,
    postgres_password: str,
    postgres_15_port: int | None,
) -> Generator[PostgresService, None, None]:
    with _provide_postgres_service(
        docker_service,
        image="postgres:15",
        name="postgres-15",
        xdist_postgres_isolate=xdist_postgres_isolation_level,
        host=postgres_host,
        user=postgres_user,
        password=postgres_password,
        host_port=postgres_15_port,
    ) as service:
        yield service


@pytest.fixture(autouse=False, scope="session")
def postgres_16_service(
    docker_service: DockerService,
    xdist_postgres_isolation_level: XdistIsolationLevel,
    postgres_host: str,
    postgres_user: str,
    postgres_password: str,
    postgres_16_port: int | None,
) -> Generator[PostgresService, None, None]:
    with _provide_postgres_service(
        docker_service,
        image="postgres:16",
        name="postgres-16",
        xdist_postgres_isolate=xdist_postgres_isolation_level,
        host=postgres_host,
        user=postgres_user,
        password=postgres_password,
        host_port=postgres_16_port,
    ) as service:
        yield service


@pytest.fixture(autouse=False, scope="session")
def postgres_17_service(
    docker_service: DockerService,
    xdist_postgres_isolation_level: XdistIsolationLevel,
    postgres_host: str,
    postgres_user: str,
    postgres_password: str,
    postgres_17_port: int | None,
) -> Generator[PostgresService, None, None]:
    with _provide_postgres_service(
        docker_service,
        image="postgres:17",
        name="postgres-17",
        xdist_postgres_isolate=xdist_postgres_isolation_level,
        host=postgres_host,
        user=postgres_user,
        password=postgres_password,
        host_port=postgres_17_port,
    ) as service:
        yield service


@pytest.fixture(autouse=False, scope="session")
def postgres_18_service(
    docker_service: DockerService,
    xdist_postgres_isolation_level: XdistIsolationLevel,
    postgres_host: str,
    postgres_user: str,
    postgres_password: str,
    postgres_18_port: int | None,
) -> Generator[PostgresService, None, None]:
    with _provide_postgres_service(
        docker_service,
        image="postgres:18",
        name="postgres-18",
        xdist_postgres_isolate=xdist_postgres_isolation_level,
        host=postgres_host,
        user=postgres_user,
        password=postgres_password,
        host_port=postgres_18_port,
    ) as service:
        yield service


@pytest.fixture(autouse=False, scope="session")
def postgres_image() -> str:
    return "postgres:18"


@pytest.fixture(autouse=False, scope="session")
def postgres_service(
    docker_service: DockerService,
    postgres_image: str,
    xdist_postgres_isolation_level: XdistIsolationLevel,
    postgres_host: str,
    postgres_user: str,
    postgres_password: str,
    postgres_port: int | None,
) -> Generator[PostgresService, None, None]:
    with _provide_postgres_service(
        docker_service,
        image=postgres_image,
        name="postgres",
        xdist_postgres_isolate=xdist_postgres_isolation_level,
        host=postgres_host,
        user=postgres_user,
        password=postgres_password,
        host_port=postgres_port,
    ) as service:
        yield service


@pytest.fixture(autouse=False, scope="session")
def pgvector_image() -> str:
    return "pgvector/pgvector:pg18"


@pytest.fixture(autouse=False, scope="session")
def pgvector_port() -> int | None:
    value = os.environ.get("PGVECTOR_PORT")
    return int(value) if value else None


@pytest.fixture(autouse=False, scope="session")
def pgvector_13_port() -> int | None:
    value = os.environ.get("PGVECTOR_13_PORT")
    return int(value) if value else None


@pytest.fixture(autouse=False, scope="session")
def pgvector_14_port() -> int | None:
    value = os.environ.get("PGVECTOR_14_PORT")
    return int(value) if value else None


@pytest.fixture(autouse=False, scope="session")
def pgvector_15_port() -> int | None:
    value = os.environ.get("PGVECTOR_15_PORT")
    return int(value) if value else None


@pytest.fixture(autouse=False, scope="session")
def pgvector_16_port() -> int | None:
    value = os.environ.get("PGVECTOR_16_PORT")
    return int(value) if value else None


@pytest.fixture(autouse=False, scope="session")
def pgvector_17_port() -> int | None:
    value = os.environ.get("PGVECTOR_17_PORT")
    return int(value) if value else None


@pytest.fixture(autouse=False, scope="session")
def pgvector_18_port() -> int | None:
    value = os.environ.get("PGVECTOR_18_PORT")
    return int(value) if value else None


@pytest.fixture(autouse=False, scope="session")
def pgvector_service(
    docker_service: DockerService,
    pgvector_image: str,
    xdist_postgres_isolation_level: XdistIsolationLevel,
    postgres_host: str,
    postgres_user: str,
    postgres_password: str,
    pgvector_port: int | None,
) -> Generator[PostgresService, None, None]:
    with _provide_postgres_service(
        docker_service,
        image=pgvector_image,
        name="pgvector",
        xdist_postgres_isolate=xdist_postgres_isolation_level,
        host=postgres_host,
        user=postgres_user,
        password=postgres_password,
        host_port=pgvector_port,
    ) as service:
        yield service


@pytest.fixture(autouse=False, scope="session")
def pgvector_13_service(
    docker_service: DockerService,
    xdist_postgres_isolation_level: XdistIsolationLevel,
    postgres_host: str,
    postgres_user: str,
    postgres_password: str,
    pgvector_13_port: int | None,
) -> Generator[PostgresService, None, None]:
    with _provide_postgres_service(
        docker_service,
        image="pgvector/pgvector:pg13",
        name="pgvector-13",
        xdist_postgres_isolate=xdist_postgres_isolation_level,
        host=postgres_host,
        user=postgres_user,
        password=postgres_password,
        host_port=pgvector_13_port,
    ) as service:
        yield service


@pytest.fixture(autouse=False, scope="session")
def pgvector_14_service(
    docker_service: DockerService,
    xdist_postgres_isolation_level: XdistIsolationLevel,
    postgres_host: str,
    postgres_user: str,
    postgres_password: str,
    pgvector_14_port: int | None,
) -> Generator[PostgresService, None, None]:
    with _provide_postgres_service(
        docker_service,
        image="pgvector/pgvector:pg14",
        name="pgvector-14",
        xdist_postgres_isolate=xdist_postgres_isolation_level,
        host=postgres_host,
        user=postgres_user,
        password=postgres_password,
        host_port=pgvector_14_port,
    ) as service:
        yield service


@pytest.fixture(autouse=False, scope="session")
def pgvector_15_service(
    docker_service: DockerService,
    xdist_postgres_isolation_level: XdistIsolationLevel,
    postgres_host: str,
    postgres_user: str,
    postgres_password: str,
    pgvector_15_port: int | None,
) -> Generator[PostgresService, None, None]:
    with _provide_postgres_service(
        docker_service,
        image="pgvector/pgvector:pg15",
        name="pgvector-15",
        xdist_postgres_isolate=xdist_postgres_isolation_level,
        host=postgres_host,
        user=postgres_user,
        password=postgres_password,
        host_port=pgvector_15_port,
    ) as service:
        yield service


@pytest.fixture(autouse=False, scope="session")
def pgvector_16_service(
    docker_service: DockerService,
    xdist_postgres_isolation_level: XdistIsolationLevel,
    postgres_host: str,
    postgres_user: str,
    postgres_password: str,
    pgvector_16_port: int | None,
) -> Generator[PostgresService, None, None]:
    with _provide_postgres_service(
        docker_service,
        image="pgvector/pgvector:pg16",
        name="pgvector-16",
        xdist_postgres_isolate=xdist_postgres_isolation_level,
        host=postgres_host,
        user=postgres_user,
        password=postgres_password,
        host_port=pgvector_16_port,
    ) as service:
        yield service


@pytest.fixture(autouse=False, scope="session")
def pgvector_17_service(
    docker_service: DockerService,
    xdist_postgres_isolation_level: XdistIsolationLevel,
    postgres_host: str,
    postgres_user: str,
    postgres_password: str,
    pgvector_17_port: int | None,
) -> Generator[PostgresService, None, None]:
    with _provide_postgres_service(
        docker_service,
        image="pgvector/pgvector:pg17",
        name="pgvector-17",
        xdist_postgres_isolate=xdist_postgres_isolation_level,
        host=postgres_host,
        user=postgres_user,
        password=postgres_password,
        host_port=pgvector_17_port,
    ) as service:
        yield service


@pytest.fixture(autouse=False, scope="session")
def pgvector_18_service(
    docker_service: DockerService,
    xdist_postgres_isolation_level: XdistIsolationLevel,
    postgres_host: str,
    postgres_user: str,
    postgres_password: str,
    pgvector_18_port: int | None,
) -> Generator[PostgresService, None, None]:
    with _provide_postgres_service(
        docker_service,
        image="pgvector/pgvector:pg18",
        name="pgvector-18",
        xdist_postgres_isolate=xdist_postgres_isolation_level,
        host=postgres_host,
        user=postgres_user,
        password=postgres_password,
        host_port=pgvector_18_port,
    ) as service:
        yield service


@pytest.fixture(autouse=False, scope="session")
def paradedb_image() -> str:
    return "paradedb/paradedb:latest-pg18"


@pytest.fixture(autouse=False, scope="session")
def paradedb_port() -> int | None:
    value = os.environ.get("PARADEDB_PORT")
    return int(value) if value else None


@pytest.fixture(autouse=False, scope="session")
def paradedb_15_port() -> int | None:
    value = os.environ.get("PARADEDB_15_PORT")
    return int(value) if value else None


@pytest.fixture(autouse=False, scope="session")
def paradedb_16_port() -> int | None:
    value = os.environ.get("PARADEDB_16_PORT")
    return int(value) if value else None


@pytest.fixture(autouse=False, scope="session")
def paradedb_17_port() -> int | None:
    value = os.environ.get("PARADEDB_17_PORT")
    return int(value) if value else None


@pytest.fixture(autouse=False, scope="session")
def paradedb_18_port() -> int | None:
    value = os.environ.get("PARADEDB_18_PORT")
    return int(value) if value else None


@pytest.fixture(autouse=False, scope="session")
def paradedb_service(
    docker_service: DockerService,
    paradedb_image: str,
    xdist_postgres_isolation_level: XdistIsolationLevel,
    postgres_host: str,
    postgres_user: str,
    postgres_password: str,
    paradedb_port: int | None,
) -> Generator[PostgresService, None, None]:
    with _provide_postgres_service(
        docker_service,
        image=paradedb_image,
        name="paradedb",
        xdist_postgres_isolate=xdist_postgres_isolation_level,
        host=postgres_host,
        user=postgres_user,
        password=postgres_password,
        host_port=paradedb_port,
    ) as service:
        yield service


@pytest.fixture(autouse=False, scope="session")
def paradedb_15_service(
    docker_service: DockerService,
    xdist_postgres_isolation_level: XdistIsolationLevel,
    postgres_host: str,
    postgres_user: str,
    postgres_password: str,
    paradedb_15_port: int | None,
) -> Generator[PostgresService, None, None]:
    with _provide_postgres_service(
        docker_service,
        image="paradedb/paradedb:latest-pg15",
        name="paradedb-15",
        xdist_postgres_isolate=xdist_postgres_isolation_level,
        host=postgres_host,
        user=postgres_user,
        password=postgres_password,
        host_port=paradedb_15_port,
    ) as service:
        yield service


@pytest.fixture(autouse=False, scope="session")
def paradedb_16_service(
    docker_service: DockerService,
    xdist_postgres_isolation_level: XdistIsolationLevel,
    postgres_host: str,
    postgres_user: str,
    postgres_password: str,
    paradedb_16_port: int | None,
) -> Generator[PostgresService, None, None]:
    with _provide_postgres_service(
        docker_service,
        image="paradedb/paradedb:latest-pg16",
        name="paradedb-16",
        xdist_postgres_isolate=xdist_postgres_isolation_level,
        host=postgres_host,
        user=postgres_user,
        password=postgres_password,
        host_port=paradedb_16_port,
    ) as service:
        yield service


@pytest.fixture(autouse=False, scope="session")
def paradedb_17_service(
    docker_service: DockerService,
    xdist_postgres_isolation_level: XdistIsolationLevel,
    postgres_host: str,
    postgres_user: str,
    postgres_password: str,
    paradedb_17_port: int | None,
) -> Generator[PostgresService, None, None]:
    with _provide_postgres_service(
        docker_service,
        image="paradedb/paradedb:latest-pg17",
        name="paradedb-17",
        xdist_postgres_isolate=xdist_postgres_isolation_level,
        host=postgres_host,
        user=postgres_user,
        password=postgres_password,
        host_port=paradedb_17_port,
    ) as service:
        yield service


@pytest.fixture(autouse=False, scope="session")
def paradedb_18_service(
    docker_service: DockerService,
    xdist_postgres_isolation_level: XdistIsolationLevel,
    postgres_host: str,
    postgres_user: str,
    postgres_password: str,
    paradedb_18_port: int | None,
) -> Generator[PostgresService, None, None]:
    with _provide_postgres_service(
        docker_service,
        image="paradedb/paradedb:latest-pg18",
        name="paradedb-18",
        xdist_postgres_isolate=xdist_postgres_isolation_level,
        host=postgres_host,
        user=postgres_user,
        password=postgres_password,
        host_port=paradedb_18_port,
    ) as service:
        yield service


@pytest.fixture(autouse=False, scope="session")
def alloydb_omni_image() -> str:
    return "google/alloydbomni:17"


@pytest.fixture(autouse=False, scope="session")
def alloydb_omni_port() -> int | None:
    value = os.environ.get("ALLOYDB_OMNI_PORT")
    return int(value) if value else None


@pytest.fixture(autouse=False, scope="session")
def alloydb_omni_15_port() -> int | None:
    value = os.environ.get("ALLOYDB_OMNI_15_PORT")
    return int(value) if value else None


@pytest.fixture(autouse=False, scope="session")
def alloydb_omni_16_port() -> int | None:
    value = os.environ.get("ALLOYDB_OMNI_16_PORT")
    return int(value) if value else None


@pytest.fixture(autouse=False, scope="session")
def alloydb_omni_17_port() -> int | None:
    value = os.environ.get("ALLOYDB_OMNI_17_PORT")
    return int(value) if value else None


@pytest.fixture(autouse=False, scope="session")
def alloydb_omni_service(
    docker_service: DockerService,
    alloydb_omni_image: str,
    xdist_postgres_isolation_level: XdistIsolationLevel,
    postgres_host: str,
    postgres_user: str,
    postgres_password: str,
    alloydb_omni_port: int | None,
) -> Generator[PostgresService, None, None]:
    with _provide_postgres_service(
        docker_service,
        image=alloydb_omni_image,
        name="alloydb-omni",
        xdist_postgres_isolate=xdist_postgres_isolation_level,
        host=postgres_host,
        user=postgres_user,
        password=postgres_password,
        host_port=alloydb_omni_port,
    ) as service:
        yield service


@pytest.fixture(autouse=False, scope="session")
def alloydb_omni_15_service(
    docker_service: DockerService,
    xdist_postgres_isolation_level: XdistIsolationLevel,
    postgres_host: str,
    postgres_user: str,
    postgres_password: str,
    alloydb_omni_15_port: int | None,
) -> Generator[PostgresService, None, None]:
    with _provide_postgres_service(
        docker_service,
        image="google/alloydbomni:15",
        name="alloydb-omni-15",
        xdist_postgres_isolate=xdist_postgres_isolation_level,
        host=postgres_host,
        user=postgres_user,
        password=postgres_password,
        host_port=alloydb_omni_15_port,
    ) as service:
        yield service


@pytest.fixture(autouse=False, scope="session")
def alloydb_omni_16_service(
    docker_service: DockerService,
    xdist_postgres_isolation_level: XdistIsolationLevel,
    postgres_host: str,
    postgres_user: str,
    postgres_password: str,
    alloydb_omni_16_port: int | None,
) -> Generator[PostgresService, None, None]:
    with _provide_postgres_service(
        docker_service,
        image="google/alloydbomni:16",
        name="alloydb-omni-16",
        xdist_postgres_isolate=xdist_postgres_isolation_level,
        host=postgres_host,
        user=postgres_user,
        password=postgres_password,
        host_port=alloydb_omni_16_port,
    ) as service:
        yield service


@pytest.fixture(autouse=False, scope="session")
def alloydb_omni_17_service(
    docker_service: DockerService,
    xdist_postgres_isolation_level: XdistIsolationLevel,
    postgres_host: str,
    postgres_user: str,
    postgres_password: str,
    alloydb_omni_17_port: int | None,
) -> Generator[PostgresService, None, None]:
    with _provide_postgres_service(
        docker_service,
        image="google/alloydbomni:17",
        name="alloydb-omni-17",
        xdist_postgres_isolate=xdist_postgres_isolation_level,
        host=postgres_host,
        user=postgres_user,
        password=postgres_password,
        host_port=alloydb_omni_17_port,
    ) as service:
        yield service
