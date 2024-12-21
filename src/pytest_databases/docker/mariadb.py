from __future__ import annotations

import contextlib
from dataclasses import dataclass
from typing import TYPE_CHECKING, Generator

import pymysql
import pytest

from pytest_databases.helpers import get_xdist_worker_num
from pytest_databases.types import ServiceContainer, XdistIsolationLevel

if TYPE_CHECKING:
    from collections.abc import Generator

    from pytest_databases._service import DockerService


@pytest.fixture(scope="session")
def xdist_mariadb_isolate() -> XdistIsolationLevel:
    return "database"


@dataclass
class MariaDBService(ServiceContainer):
    db: str
    user: str
    password: str


@contextlib.contextmanager
def _provide_mysql_service(
    docker_service: DockerService,
    image: str,
    name: str,
    isolation_level: XdistIsolationLevel,
) -> Generator[MariaDBService, None, None]:
    user = "app"
    password = "super-secret"
    root_password = "super-secret"
    database = "db"

    def check(_service: ServiceContainer) -> bool:
        try:
            conn = pymysql.connect(
                host=_service.host,
                port=_service.port,
                user=user,
                database=database,
                password=password,
            )
        except Exception:  # noqa: BLE001
            return False

        try:
            with conn.cursor() as cursor:
                cursor.execute("select 1 as is_available")
                resp = cursor.fetchone()
                return resp is not None and resp[0] == 1
        finally:
            with contextlib.suppress(Exception):
                conn.close()

    worker_num = get_xdist_worker_num()
    db_name = f"pytest_{worker_num + 1}"
    if isolation_level == "server":
        name = f"{name}_{worker_num}"

    with docker_service.run(
        image=image,
        check=check,
        container_port=3306,
        name=name,
        env={
            "MARIADB_ROOT_PASSWORD": root_password,
            "MARIADB_PASSWORD": password,
            "MARIADB_USER": user,
            "MARIADB_DATABASE": database,
            "MARIADB_ROOT_HOST": "%",
            "LANG": "C.UTF-8",
        },
        timeout=60,
        pause=0.5,
        exec_after_start=(
            f'mariadb --user=root --password={root_password} -e "CREATE DATABASE {db_name};'
            f"GRANT ALL PRIVILEGES ON {db_name}.* TO '{user}'@'%'; "
            'FLUSH PRIVILEGES;"'
        ),
    ) as service:
        yield MariaDBService(
            db=db_name,
            host=service.host,
            port=service.port,
            user=user,
            password=password,
        )


@pytest.fixture(autouse=False, scope="session")
def mariadb113_service(
    docker_service: DockerService,
    xdist_mariadb_isolate: XdistIsolationLevel,
) -> Generator[MariaDBService, None, None]:
    with _provide_mysql_service(
        docker_service=docker_service,
        image="mariadb:11.3",
        name="mariadb-11.3",
        isolation_level=xdist_mariadb_isolate,
    ) as service:
        yield service


@pytest.fixture(autouse=False, scope="session")
def mariadb_service(mariadb113_service: MariaDBService) -> MariaDBService:
    return mariadb113_service


@pytest.fixture(autouse=False, scope="session")
def mariadb113_startup_connection(mariadb_service: MariaDBService) -> Generator[pymysql.Connection, None, None]:
    with pymysql.connect(
        host=mariadb_service.host,
        port=mariadb_service.port,
        user=mariadb_service.user,
        database=mariadb_service.db,
        password=mariadb_service.password,
    ) as conn:
        yield conn


@pytest.fixture(autouse=False, scope="session")
def mariadb_startup_connection(mariadb113_startup_connection: pymysql.Connection) -> pymysql.Connection:
    return mariadb113_startup_connection
