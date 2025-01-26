from __future__ import annotations

import contextlib
import traceback
from dataclasses import dataclass
from typing import TYPE_CHECKING, Generator

import mariadb
import pytest

from pytest_databases.helpers import get_xdist_worker_num
from pytest_databases.types import ServiceContainer, XdistIsolationLevel

if TYPE_CHECKING:
    from collections.abc import Generator

    from pytest_databases._service import DockerService


@dataclass
class MariaDBService(ServiceContainer):
    db: str
    user: str
    password: str


@pytest.fixture(scope="session")
def xdist_mariadb_isolation_level() -> XdistIsolationLevel:
    return "database"


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
            conn = mariadb.connect(
                host=_service.host,
                port=_service.port,
                user=user,
                database=database,
                password=password,
            )
        except Exception:  # noqa: BLE001
            traceback.print_exc()
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
            f"GRANT ALL PRIVILEGES ON *.* TO '{user}'@'%'; "
            'FLUSH PRIVILEGES;"'
        ),
        transient=isolation_level == "server",
    ) as service:
        yield MariaDBService(
            db=db_name,
            host=service.host,
            port=service.port,
            user=user,
            password=password,
        )


@pytest.fixture(autouse=False, scope="session")
def mariadb_113_service(
    docker_service: DockerService,
    xdist_mariadb_isolation_level: XdistIsolationLevel,
) -> Generator[MariaDBService, None, None]:
    with _provide_mysql_service(
        docker_service=docker_service,
        image="mariadb:11.3",
        name="mariadb-11.3",
        isolation_level=xdist_mariadb_isolation_level,
    ) as service:
        yield service


@pytest.fixture(autouse=False, scope="session")
def mariadb_service(mariadb_113_service: MariaDBService) -> MariaDBService:
    return mariadb_113_service


@pytest.fixture(autouse=False, scope="session")
def mariadb_113_connection(mariadb_113_service: MariaDBService) -> Generator[mariadb.Connection, None, None]:
    with mariadb.connect(
        host=mariadb_113_service.host,
        port=mariadb_113_service.port,
        user=mariadb_113_service.user,
        database=mariadb_113_service.db,
        password=mariadb_113_service.password,
    ) as conn:
        yield conn


@pytest.fixture(autouse=False, scope="session")
def mariadb_connection(mariadb_113_connection: mariadb.Connection) -> mariadb.Connection:
    return mariadb_113_connection
