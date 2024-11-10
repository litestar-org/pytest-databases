from __future__ import annotations

import dataclasses
from contextlib import contextmanager
from typing import TYPE_CHECKING

import psycopg
import pytest

from pytest_databases.helpers import get_xdist_worker_num
from pytest_databases.types import ServiceContainer

if TYPE_CHECKING:
    from collections.abc import Generator

    from pytest_databases._service import DockerService


def _make_connection_string(host: str, port: int, user: str, password: str, database: str) -> str:
    return f"dbname={database} user={user} host={host} port={port} password={password}"


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
    db_name = f"pytest_{worker_num + 1}"
    with docker_service.run(
        image=image,
        check=check,
        container_port=5432,
        name=name,
        env={
            "POSTGRES_PASSWORD": "super-secret",
        },
        exec_after_start=f"psql -U postgres -d postgres -c 'CREATE DATABASE {db_name};'",
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
) -> Generator[PostgresService, None, None]:
    with _provide_postgres_service(docker_service, image="postgres:11", name="postgres-11") as service:
        yield service


@pytest.fixture(autouse=False, scope="session")
def postgres_12_service(
    docker_service: DockerService,
) -> Generator[PostgresService, None, None]:
    with _provide_postgres_service(docker_service, image="postgres:12", name="postgres-12") as service:
        yield service


@pytest.fixture(autouse=False, scope="session")
def postgres_13_service(
    docker_service: DockerService,
) -> Generator[PostgresService, None, None]:
    with _provide_postgres_service(docker_service, image="postgres:13", name="postgres-13") as service:
        yield service


@pytest.fixture(autouse=False, scope="session")
def postgres_14_service(
    docker_service: DockerService,
) -> Generator[PostgresService, None, None]:
    with _provide_postgres_service(docker_service, image="postgres:14", name="postgres-14") as service:
        yield service


@pytest.fixture(autouse=False, scope="session")
def postgres_15_service(
    docker_service: DockerService,
) -> Generator[PostgresService, None, None]:
    with _provide_postgres_service(docker_service, image="postgres:15", name="postgres-15") as service:
        yield service


@pytest.fixture(autouse=False, scope="session")
def postgres_16_service(
    docker_service: DockerService,
) -> Generator[PostgresService, None, None]:
    with _provide_postgres_service(docker_service, image="postgres:16", name="postgres-16") as service:
        yield service


@pytest.fixture(autouse=False, scope="session")
def postgres_17_service(
    docker_service: DockerService,
) -> Generator[PostgresService, None, None]:
    with _provide_postgres_service(docker_service, image="postgres:17", name="postgres-17") as service:
        yield service


@pytest.fixture(autouse=False, scope="session")
def postgres_service(postgres_17_service: PostgresService) -> PostgresService:
    return postgres_17_service


@pytest.fixture(autouse=False, scope="session")
def postgres_startup_connection(
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
def postgres11_startup_connection(
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
def postgres12_startup_connection(
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
def postgres13_startup_connection(
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
def postgres14_startup_connection(
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
def postgres15_startup_connection(
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
def postgres16_startup_connection(
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
def postgres17_startup_connection(
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
