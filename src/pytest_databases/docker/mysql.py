"""MySQL container service fixtures."""

from __future__ import annotations

import contextlib
import os
import time
from dataclasses import dataclass
from typing import TYPE_CHECKING

import pytest

from pytest_databases._service import DockerService, ServiceContainer
from pytest_databases.helpers import exec_output_to_bytes, get_xdist_worker_num

if TYPE_CHECKING:
    from collections.abc import Generator

    from pytest_databases.types import XdistIsolationLevel

__all__ = [
    "MySQLService",
    "mysql_8_service",
    "mysql_56_service",
    "mysql_57_service",
    "mysql_84_service",
    "mysql_96_service",
    "mysql_97_service",
    "mysql_database",
    "mysql_password",
    "mysql_root_password",
    "mysql_service",
    "mysql_user",
    "platform",
    "provide_mysql_service",
    "xdist_mysql_isolation_level",
]


@dataclass
class MySQLService(ServiceContainer):
    """Service handle for a running MySQL container."""

    db: str
    user: str
    password: str


@contextlib.contextmanager
def provide_mysql_service(
    docker_service: DockerService,
    image: str,
    name: str,
    isolation_level: XdistIsolationLevel,
    platform: str | None,
    user: str,
    password: str,
    root_password: str,
    database: str,
) -> Generator[MySQLService, None, None]:
    """Start and manage a MySQL container service with performance_schema enabled.

    Yields:
        Active MySQLService instance.

    Raises:
        RuntimeError: If database and application user grants cannot be verified.
    """

    def check(_service: ServiceContainer) -> bool:
        res = _service.container.exec_run(
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
        command="--performance-schema=ON",
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
        setup_sql = (
            f"CREATE DATABASE IF NOT EXISTS {db_name}; GRANT ALL PRIVILEGES ON *.* TO '{user}'@'%'; FLUSH PRIVILEGES;"
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
            setup_res = service.container.exec_run(
                ["mysql", "--user=root", f"--password={root_password}", "-e", setup_sql],
            )
            if setup_res.exit_code == 0:
                verify_res = service.container.exec_run(verify_cmd)
                if verify_res.exit_code == 0:
                    break
                last_err = exec_output_to_bytes(verify_res.output)
            else:
                last_err = exec_output_to_bytes(setup_res.output)
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
def xdist_mysql_isolation_level() -> XdistIsolationLevel:
    """Return the pytest-xdist isolation level for MySQL.

    Returns:
        Default isolation level string.
    """
    return "database"


@pytest.fixture(scope="session")
def platform() -> str:
    """Return the legacy x86_64 platform string used by MySQL 5.6 and 5.7.

    Returns:
        Platform string.
    """
    return "linux/x86_64"


@pytest.fixture(scope="session")
def mysql_user() -> str:
    """Return the MySQL application user.

    Returns:
        Username string.
    """
    return os.getenv("MYSQL_USER", "app")


@pytest.fixture(scope="session")
def mysql_password() -> str:
    """Return the MySQL application password.

    Returns:
        Password string.
    """
    return os.getenv("MYSQL_PASSWORD", "super-secret")


@pytest.fixture(scope="session")
def mysql_root_password() -> str:
    """Return the MySQL root password.

    Returns:
        Root password string.
    """
    return os.getenv("MYSQL_ROOT_PASSWORD", "super-secret")


@pytest.fixture(scope="session")
def mysql_database() -> str:
    """Return the MySQL database name.

    Returns:
        Database name string.
    """
    return os.getenv("MYSQL_DATABASE", "db")


@pytest.fixture(scope="session")
def mysql_service(mysql_84_service: MySQLService) -> MySQLService:
    """Provide the default MySQL container service.

    Returns:
        Active MySQLService instance.
    """
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
    """Provide a running MySQL 5.6 container service.

    Yields:
        Active MySQLService instance.
    """
    with provide_mysql_service(
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
    """Provide a running MySQL 5.7 container service.

    Yields:
        Active MySQLService instance.
    """
    with provide_mysql_service(
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
    mysql_user: str,
    mysql_password: str,
    mysql_root_password: str,
    mysql_database: str,
) -> Generator[MySQLService, None, None]:
    """Provide a running MySQL 8 container service.

    Yields:
        Active MySQLService instance.
    """
    with provide_mysql_service(
        image="mysql:8",
        name="mysql-8",
        docker_service=docker_service,
        isolation_level=xdist_mysql_isolation_level,
        platform=None,
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
    mysql_user: str,
    mysql_password: str,
    mysql_root_password: str,
    mysql_database: str,
) -> Generator[MySQLService, None, None]:
    """Provide a running MySQL 8.4 LTS container service.

    Yields:
        Active MySQLService instance.
    """
    with provide_mysql_service(
        image="mysql:8.4",
        name="mysql-8.4",
        docker_service=docker_service,
        isolation_level=xdist_mysql_isolation_level,
        platform=None,
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
    mysql_user: str,
    mysql_password: str,
    mysql_root_password: str,
    mysql_database: str,
) -> Generator[MySQLService, None, None]:
    """Provide a running MySQL 9.6 container service.

    Yields:
        Active MySQLService instance.
    """
    with provide_mysql_service(
        image="mysql:9.6",
        name="mysql-9.6",
        docker_service=docker_service,
        isolation_level=xdist_mysql_isolation_level,
        platform=None,
        user=mysql_user,
        password=mysql_password,
        root_password=mysql_root_password,
        database=mysql_database,
    ) as service:
        yield service


@pytest.fixture(scope="session")
def mysql_97_service(
    docker_service: DockerService,
    xdist_mysql_isolation_level: XdistIsolationLevel,
    mysql_user: str,
    mysql_password: str,
    mysql_root_password: str,
    mysql_database: str,
) -> Generator[MySQLService, None, None]:
    """Provide a running MySQL 9.7 container service.

    Yields:
        Active MySQLService instance.
    """
    with provide_mysql_service(
        image="mysql:9.7",
        name="mysql-9.7",
        docker_service=docker_service,
        isolation_level=xdist_mysql_isolation_level,
        platform=None,
        user=mysql_user,
        password=mysql_password,
        root_password=mysql_root_password,
        database=mysql_database,
    ) as service:
        yield service
