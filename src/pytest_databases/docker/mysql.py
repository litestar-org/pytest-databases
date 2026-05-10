from __future__ import annotations

import contextlib
import os
import time
from dataclasses import dataclass
from typing import TYPE_CHECKING

import pytest

from pytest_databases._service import DockerService, ServiceContainer
from pytest_databases.helpers import get_xdist_worker_num

if TYPE_CHECKING:
    from collections.abc import Generator, Iterator

    from pytest_databases.types import XdistIsolationLevel


def _output_to_bytes(output: bytes | Iterator[bytes]) -> bytes:
    if isinstance(output, bytes):
        return output
    return b"".join(output)


@dataclass
class MySQLService(ServiceContainer):
    db: str
    user: str
    password: str


@pytest.fixture(scope="session")
def xdist_mysql_isolation_level() -> XdistIsolationLevel:
    return "database"


@pytest.fixture(scope="session")
def platform() -> str:
    return "linux/x86_64"


@pytest.fixture(scope="session")
def mysql_user() -> str:
    return os.getenv("MYSQL_USER", "app")


@pytest.fixture(scope="session")
def mysql_password() -> str:
    return os.getenv("MYSQL_PASSWORD", "super-secret")


@pytest.fixture(scope="session")
def mysql_root_password() -> str:
    return os.getenv("MYSQL_ROOT_PASSWORD", "super-secret")


@pytest.fixture(scope="session")
def mysql_database() -> str:
    return os.getenv("MYSQL_DATABASE", "db")


@contextlib.contextmanager
def _provide_mysql_service(
    docker_service: DockerService,
    image: str,
    name: str,
    isolation_level: XdistIsolationLevel,
    platform: str,
    user: str,
    password: str,
    root_password: str,
    database: str,
) -> Generator[MySQLService, None, None]:
    def check(_service: ServiceContainer) -> bool:
        container_name = f"pytest_databases_{name}"
        container = docker_service._get_container(container_name)
        if not container:
            return False

        # Attempt to run a simple SELECT 1 to ensure the server is fully ready
        res = container.exec_run(
            ["mysql", "--user=root", f"--password={root_password}", "-e", "SELECT 1"],
        )
        return res.exit_code == 0

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
        timeout=120,
        pause=1.0,
        transient=isolation_level == "server",
        platform=platform,
    ) as service:
        # The check() above only verifies root can SELECT 1; that signal is true
        # before mysql has finished provisioning the app user and applying our
        # post-start grants. Verify the app user can actually reach db_name
        # before yielding so tests don't race the fixture into 'access denied'.
        container_name = f"pytest_databases_{name}"
        container = docker_service._get_container(container_name)
        if container is None:
            msg = f"MySQL container {container_name!r} disappeared after startup"
            raise RuntimeError(msg)

        setup_sql = (
            f"CREATE DATABASE IF NOT EXISTS {db_name}; "
            f"GRANT ALL PRIVILEGES ON *.* TO '{user}'@'%'; "
            "FLUSH PRIVILEGES;"
        )
        verify_cmd = [
            "mysql",
            f"--user={user}",
            f"--password={password}",
            db_name,
            "-e",
            "SELECT 1",
        ]
        last_err: bytes = b""
        for attempt in range(15):
            setup_res = container.exec_run(
                ["mysql", "--user=root", f"--password={root_password}", "-e", setup_sql],
            )
            if setup_res.exit_code == 0:
                verify_res = container.exec_run(verify_cmd)
                if verify_res.exit_code == 0:
                    break
                last_err = _output_to_bytes(verify_res.output)
            else:
                last_err = _output_to_bytes(setup_res.output)
            time.sleep(1 + attempt * 0.5)
        else:
            msg = (
                f"MySQL fixture {name!r}: user {user!r} could not reach database "
                f"{db_name!r} after 15 attempts. Last output: {last_err!r}"
            )
            raise RuntimeError(msg)

        yield MySQLService(
            host=service.host,
            port=service.port,
            container=service.container,
            db=db_name,
            user=user,
            password=password,
        )


@pytest.fixture(scope="session")
def mysql_service(mysql_84_service: MySQLService) -> MySQLService:
    return mysql_84_service


@pytest.fixture(scope="session")
def mysql_56_service(
    docker_service: DockerService,
    xdist_mysql_isolation_level: XdistIsolationLevel,
    platform: str,
    mysql_user: str,
    mysql_password: str,
    mysql_root_password: str,
    mysql_database: str,
) -> Generator[MySQLService, None, None]:
    with _provide_mysql_service(
        image="mysql:5.6",
        name="mysql-56",
        docker_service=docker_service,
        isolation_level=xdist_mysql_isolation_level,
        platform=platform,
        user=mysql_user,
        password=mysql_password,
        root_password=mysql_root_password,
        database=mysql_database,
    ) as service:
        yield service


@pytest.fixture(scope="session")
def mysql_57_service(
    docker_service: DockerService,
    xdist_mysql_isolation_level: XdistIsolationLevel,
    platform: str,
    mysql_user: str,
    mysql_password: str,
    mysql_root_password: str,
    mysql_database: str,
) -> Generator[MySQLService, None, None]:
    with _provide_mysql_service(
        image="mysql:5.7",
        name="mysql-57",
        docker_service=docker_service,
        isolation_level=xdist_mysql_isolation_level,
        platform=platform,
        user=mysql_user,
        password=mysql_password,
        root_password=mysql_root_password,
        database=mysql_database,
    ) as service:
        yield service


@pytest.fixture(scope="session")
def mysql_8_service(
    docker_service: DockerService,
    xdist_mysql_isolation_level: XdistIsolationLevel,
    platform: str,
    mysql_user: str,
    mysql_password: str,
    mysql_root_password: str,
    mysql_database: str,
) -> Generator[MySQLService, None, None]:
    with _provide_mysql_service(
        image="mysql:8",
        name="mysql-8",
        docker_service=docker_service,
        isolation_level=xdist_mysql_isolation_level,
        platform=platform,
        user=mysql_user,
        password=mysql_password,
        root_password=mysql_root_password,
        database=mysql_database,
    ) as service:
        yield service


@pytest.fixture(scope="session")
def mysql_84_service(
    docker_service: DockerService,
    xdist_mysql_isolation_level: XdistIsolationLevel,
    platform: str,
    mysql_user: str,
    mysql_password: str,
    mysql_root_password: str,
    mysql_database: str,
) -> Generator[MySQLService, None, None]:
    with _provide_mysql_service(
        image="mysql:8.4",
        name="mysql-8.4",
        docker_service=docker_service,
        isolation_level=xdist_mysql_isolation_level,
        platform=platform,
        user=mysql_user,
        password=mysql_password,
        root_password=mysql_root_password,
        database=mysql_database,
    ) as service:
        yield service


@pytest.fixture(scope="session")
def mysql_96_service(
    docker_service: DockerService,
    xdist_mysql_isolation_level: XdistIsolationLevel,
    platform: str,
    mysql_user: str,
    mysql_password: str,
    mysql_root_password: str,
    mysql_database: str,
) -> Generator[MySQLService, None, None]:
    with _provide_mysql_service(
        image="mysql:9.6",
        name="mysql-9.6",
        docker_service=docker_service,
        isolation_level=xdist_mysql_isolation_level,
        platform=platform,
        user=mysql_user,
        password=mysql_password,
        root_password=mysql_root_password,
        database=mysql_database,
    ) as service:
        yield service
