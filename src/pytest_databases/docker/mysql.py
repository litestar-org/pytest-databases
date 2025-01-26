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
    db_name = "pytest_databases"
    if worker_num is not None:
        suffix = f"_{worker_num}"
        if isolation_level == "server":
            name += suffix
        else:
            db_name += suffix

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
            f"GRANT ALL PRIVILEGES ON *.* TO '{user}'@'%'; "
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
def mysql_service(mysql_8_service: MySQLService) -> MySQLService:
    return mysql_8_service


@pytest.fixture(autouse=False, scope="session")
def mysql_56_service(
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
def mysql_57_service(
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
def mysql_8_service(
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
def mysql_56_connection(
    mysql_56_service: MySQLService,
) -> Generator[pymysql.Connection, None, None]:
    with pymysql.connect(
        host=mysql_56_service.host,
        port=mysql_56_service.port,
        user=mysql_56_service.user,
        database=mysql_56_service.db,
        password=mysql_56_service.password,
    ) as conn:
        yield conn


@pytest.fixture(autouse=False, scope="session")
def mysql_57_connection(
    mysql_57_service: MySQLService,
) -> Generator[pymysql.Connection, None, None]:
    with pymysql.connect(
        host=mysql_57_service.host,
        port=mysql_57_service.port,
        user=mysql_57_service.user,
        database=mysql_57_service.db,
        password=mysql_57_service.password,
    ) as conn:
        yield conn


@pytest.fixture(autouse=False, scope="session")
def mysql_connection(mysql_8_connection: pymysql.Connection) -> pymysql.Connection:
    return mysql_8_connection


@pytest.fixture(autouse=False, scope="session")
def mysql_8_connection(mysql_8_service: MySQLService) -> Generator[pymysql.Connection, None, None]:
    with pymysql.connect(
        host=mysql_8_service.host,
        port=mysql_8_service.port,
        user=mysql_8_service.user,
        database=mysql_8_service.db,
        password=mysql_8_service.password,
    ) as conn:
        yield conn
