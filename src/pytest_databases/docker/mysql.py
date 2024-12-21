from __future__ import annotations

import contextlib
from dataclasses import dataclass
from typing import TYPE_CHECKING

import pymysql
import pytest

from pytest_databases._service import DockerService, ServiceContainer
from pytest_databases.helpers import get_xdist_worker_num

if TYPE_CHECKING:
    from collections.abc import Generator

    from pytest_databases.types import XdistIsolationLevel


@dataclass
class MySQLService(ServiceContainer):
    db: str
    user: str
    password: str


@pytest.fixture(scope="session")
def xdist_mysql_isolation_level() -> XdistIsolationLevel:
    return "database"


@contextlib.contextmanager
def _provide_mysql_service(
    docker_service: DockerService,
    image: str,
    name: str,
    isolation_level: XdistIsolationLevel,
) -> Generator[MySQLService, None, None]:
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
            "MYSQL_ROOT_PASSWORD": root_password,
            "MYSQL_PASSWORD": password,
            "MYSQL_USER": user,
            "MYSQL_DATABASE": database,
            "MYSQL_ROOT_HOST": "%",
            "LANG": "C.UTF-8",
        },
        timeout=60,
        pause=0.5,
        exec_after_start=(
            f'mysql --user=root --password={root_password} -e "CREATE DATABASE {db_name};'
            f"GRANT ALL PRIVILEGES ON {db_name}.* TO '{user}'@'%'; "
            'FLUSH PRIVILEGES;"'
        ),
        transient=isolation_level == "server",
    ) as service:
        yield MySQLService(
            db=db_name,
            host=service.host,
            port=service.port,
            user=user,
            password=password,
        )


@pytest.fixture(autouse=False, scope="session")
def mysql_service(mysql8_service: MySQLService) -> MySQLService:
    return mysql8_service


@pytest.fixture(autouse=False, scope="session")
def mysql8_service(
    docker_service: DockerService,
    xdist_mysql_isolation_level: XdistIsolationLevel,
) -> Generator[MySQLService, None, None]:
    with _provide_mysql_service(
        image="mysql:8",
        name="mysql-8",
        docker_service=docker_service,
        isolation_level=xdist_mysql_isolation_level,
    ) as service:
        yield service


@pytest.fixture(autouse=False, scope="session")
def mysql57_service(
    docker_service: DockerService,
    xdist_mysql_isolation_level: XdistIsolationLevel,
) -> Generator[MySQLService, None, None]:
    with _provide_mysql_service(
        image="mysql:5.7",
        name="mysql-57",
        docker_service=docker_service,
        isolation_level=xdist_mysql_isolation_level,
    ) as service:
        yield service


@pytest.fixture(autouse=False, scope="session")
def mysql56_service(
    docker_service: DockerService,
    xdist_mysql_isolation_level: XdistIsolationLevel,
) -> Generator[MySQLService, None, None]:
    with _provide_mysql_service(
        image="mysql:5.6",
        name="mysql-56",
        docker_service=docker_service,
        isolation_level=xdist_mysql_isolation_level,
    ) as service:
        yield service


@pytest.fixture(autouse=False, scope="session")
def mysql8_startup_connection(mysql8_service: MySQLService) -> Generator[pymysql.Connection, None, None]:
    with pymysql.connect(
        host=mysql8_service.host,
        port=mysql8_service.port,
        user=mysql8_service.user,
        database=mysql8_service.db,
        password=mysql8_service.password,
    ) as conn:
        yield conn


@pytest.fixture(autouse=False, scope="session")
def mysql_startup_connection(mysql8_startup_connection: pymysql.Connection) -> pymysql.Connection:
    return mysql8_startup_connection


@pytest.fixture(autouse=False, scope="session")
def mysql56_startup_connection(
    mysql56_service: MySQLService,
) -> Generator[pymysql.Connection, None, None]:
    with pymysql.connect(
        host=mysql56_service.host,
        port=mysql56_service.port,
        user=mysql56_service.user,
        database=mysql56_service.db,
        password=mysql56_service.password,
    ) as conn:
        yield conn


@pytest.fixture(autouse=False, scope="session")
def mysql57_startup_connection(
    mysql57_service: MySQLService,
) -> Generator[pymysql.Connection, None, None]:
    with pymysql.connect(
        host=mysql57_service.host,
        port=mysql57_service.port,
        user=mysql57_service.user,
        database=mysql57_service.db,
        password=mysql57_service.password,
    ) as conn:
        yield conn
