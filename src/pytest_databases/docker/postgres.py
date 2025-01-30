from __future__ import annotations

import dataclasses
from contextlib import contextmanager
from typing import TYPE_CHECKING

import psycopg
import pytest

from pytest_databases.helpers import get_xdist_worker_num
from pytest_databases.types import ServiceContainer, XdistIsolationLevel

if TYPE_CHECKING:
    from collections.abc import Generator

    from pytest_databases._service import DockerService


def _make_connection_string(host: str, port: int, user: str, password: str, database: str) -> str:
    return f"dbname={database} user={user} host={host} port={port} password={password}"


@pytest.fixture(scope="session")
def xdist_postgres_isolation_level() -> XdistIsolationLevel:
    return "database"


@dataclasses.dataclass
class PostgresService(ServiceContainer):
    database: str
    password: str
    user: str


@contextmanager
def _provide_postgres_service(
    docker_service: DockerService,
    image: str,
    name: str,
    xdist_postgres_isolate: XdistIsolationLevel,
) -> Generator[PostgresService, None, None]:
    def check(_service: ServiceContainer) -> bool:
        try:
            with psycopg.connect(
                _make_connection_string(
                    host=_service.host,
                    port=_service.port,
                    user="postgres",
                    password="super-secret",
                    database="postgres",
                )
            ) as conn:
                db_open = conn.execute("SELECT 1").fetchone()
                return bool(db_open is not None and db_open[0] == 1)
        except Exception:  # noqa: BLE001
            return False

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
        container_port=5432,
        name=name,
        env={
            "POSTGRES_PASSWORD": "super-secret",
        },
        exec_after_start=f"psql -U postgres -d postgres -c 'CREATE DATABASE {db_name};'",
        transient=xdist_postgres_isolate == "server",
    ) as service:
        yield PostgresService(
            database=db_name,
            host=service.host,
            port=service.port,
            user="postgres",
            password="super-secret",
        )


@pytest.fixture(autouse=False, scope="session")
def postgres_11_service(
    docker_service: DockerService,
    xdist_postgres_isolation_level: XdistIsolationLevel,
) -> Generator[PostgresService, None, None]:
    with _provide_postgres_service(
        docker_service,
        image="postgres:11",
        name="postgres-11",
        xdist_postgres_isolate=xdist_postgres_isolation_level,
    ) as service:
        yield service


@pytest.fixture(autouse=False, scope="session")
def postgres_12_service(
    docker_service: DockerService,
    xdist_postgres_isolation_level: XdistIsolationLevel,
) -> Generator[PostgresService, None, None]:
    with _provide_postgres_service(
        docker_service,
        image="postgres:12",
        name="postgres-12",
        xdist_postgres_isolate=xdist_postgres_isolation_level,
    ) as service:
        yield service


@pytest.fixture(autouse=False, scope="session")
def postgres_13_service(
    docker_service: DockerService,
    xdist_postgres_isolation_level: XdistIsolationLevel,
) -> Generator[PostgresService, None, None]:
    with _provide_postgres_service(
        docker_service,
        image="postgres:13",
        name="postgres-13",
        xdist_postgres_isolate=xdist_postgres_isolation_level,
    ) as service:
        yield service


@pytest.fixture(autouse=False, scope="session")
def postgres_14_service(
    docker_service: DockerService,
    xdist_postgres_isolation_level: XdistIsolationLevel,
) -> Generator[PostgresService, None, None]:
    with _provide_postgres_service(
        docker_service,
        image="postgres:14",
        name="postgres-14",
        xdist_postgres_isolate=xdist_postgres_isolation_level,
    ) as service:
        yield service


@pytest.fixture(autouse=False, scope="session")
def postgres_15_service(
    docker_service: DockerService,
    xdist_postgres_isolation_level: XdistIsolationLevel,
) -> Generator[PostgresService, None, None]:
    with _provide_postgres_service(
        docker_service,
        image="postgres:15",
        name="postgres-15",
        xdist_postgres_isolate=xdist_postgres_isolation_level,
    ) as service:
        yield service


@pytest.fixture(autouse=False, scope="session")
def postgres_16_service(
    docker_service: DockerService,
    xdist_postgres_isolation_level: XdistIsolationLevel,
) -> Generator[PostgresService, None, None]:
    with _provide_postgres_service(
        docker_service,
        image="postgres:16",
        name="postgres-16",
        xdist_postgres_isolate=xdist_postgres_isolation_level,
    ) as service:
        yield service


@pytest.fixture(autouse=False, scope="session")
def postgres_17_service(
    docker_service: DockerService,
    xdist_postgres_isolation_level: XdistIsolationLevel,
) -> Generator[PostgresService, None, None]:
    with _provide_postgres_service(
        docker_service,
        image="postgres:17",
        name="postgres-17",
        xdist_postgres_isolate=xdist_postgres_isolation_level,
    ) as service:
        yield service


@pytest.fixture(autouse=False, scope="session")
def postgres_service(postgres_17_service: PostgresService) -> PostgresService:
    return postgres_17_service


@pytest.fixture(autouse=False, scope="session")
def postgres_connection(
    postgres_service: PostgresService,
) -> Generator[psycopg.Connection, None, None]:
    with psycopg.connect(
        _make_connection_string(
            host=postgres_service.host,
            port=postgres_service.port,
            user=postgres_service.user,
            password=postgres_service.password,
            database=postgres_service.database,
        ),
    ) as conn:
        yield conn


@pytest.fixture(autouse=False, scope="session")
def postgres_11_connection(
    postgres_11_service: PostgresService,
) -> Generator[psycopg.Connection, None, None]:
    with psycopg.connect(
        _make_connection_string(
            host=postgres_11_service.host,
            port=postgres_11_service.port,
            user=postgres_11_service.user,
            password=postgres_11_service.password,
            database=postgres_11_service.database,
        ),
    ) as conn:
        yield conn


@pytest.fixture(autouse=False, scope="session")
def postgres_12_connection(
    postgres_12_service: PostgresService,
) -> Generator[psycopg.Connection, None, None]:
    with psycopg.connect(
        _make_connection_string(
            host=postgres_12_service.host,
            port=postgres_12_service.port,
            user=postgres_12_service.user,
            password=postgres_12_service.password,
            database=postgres_12_service.database,
        ),
    ) as conn:
        yield conn


@pytest.fixture(autouse=False, scope="session")
def postgres_13_connection(
    postgres_13_service: PostgresService,
) -> Generator[psycopg.Connection, None, None]:
    with psycopg.connect(
        _make_connection_string(
            host=postgres_13_service.host,
            port=postgres_13_service.port,
            user=postgres_13_service.user,
            password=postgres_13_service.password,
            database=postgres_13_service.database,
        ),
    ) as conn:
        yield conn


@pytest.fixture(autouse=False, scope="session")
def postgres_14_connection(
    postgres_14_service: PostgresService,
) -> Generator[psycopg.Connection, None, None]:
    with psycopg.connect(
        _make_connection_string(
            host=postgres_14_service.host,
            port=postgres_14_service.port,
            user=postgres_14_service.user,
            password=postgres_14_service.password,
            database=postgres_14_service.database,
        ),
    ) as conn:
        yield conn


@pytest.fixture(autouse=False, scope="session")
def postgres_15_connection(
    postgres_15_service: PostgresService,
) -> Generator[psycopg.Connection, None, None]:
    with psycopg.connect(
        _make_connection_string(
            host=postgres_15_service.host,
            port=postgres_15_service.port,
            user=postgres_15_service.user,
            password=postgres_15_service.password,
            database=postgres_15_service.database,
        ),
    ) as conn:
        yield conn


@pytest.fixture(autouse=False, scope="session")
def postgres_16_connection(
    postgres_16_service: PostgresService,
) -> Generator[psycopg.Connection, None, None]:
    with psycopg.connect(
        _make_connection_string(
            host=postgres_16_service.host,
            port=postgres_16_service.port,
            user=postgres_16_service.user,
            password=postgres_16_service.password,
            database=postgres_16_service.database,
        ),
    ) as conn:
        yield conn


@pytest.fixture(autouse=False, scope="session")
def postgres_17_connection(
    postgres_17_service: PostgresService,
) -> Generator[psycopg.Connection, None, None]:
    with psycopg.connect(
        _make_connection_string(
            host=postgres_17_service.host,
            port=postgres_17_service.port,
            user=postgres_17_service.user,
            password=postgres_17_service.password,
            database=postgres_17_service.database,
        ),
    ) as conn:
        yield conn
