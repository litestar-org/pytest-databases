from __future__ import annotations

import contextlib
import os
import time
import warnings
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

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


@pytest.fixture(scope="session")
def platform() -> str:
    return "linux/x86_64"


@contextlib.contextmanager
def _provide_mysql_service(
    docker_service: DockerService,
    image: str,
    name: str,
    isolation_level: XdistIsolationLevel,
    platform: str,
) -> Generator[MySQLService, None, None]:
    user = os.getenv("MYSQL_USER", "app")
    password = os.getenv("MYSQL_PASSWORD", "super-secret")
    root_password = os.getenv("MYSQL_ROOT_PASSWORD", "super-secret")
    database = os.getenv("MYSQL_DATABASE", "db")

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
                last_err = verify_res.output
            else:
                last_err = setup_res.output
            time.sleep(1 + attempt * 0.5)
        else:
            msg = (
                f"MySQL fixture {name!r}: user {user!r} could not reach database "
                f"{db_name!r} after 15 attempts. Last output: {last_err!r}"
            )
            raise RuntimeError(msg)

        yield MySQLService(
            db=db_name,
            host=service.host,
            port=service.port,
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
) -> Generator[MySQLService, None, None]:
    with _provide_mysql_service(
        image="mysql:5.6",
        name="mysql-56",
        docker_service=docker_service,
        isolation_level=xdist_mysql_isolation_level,
        platform=platform,
    ) as service:
        yield service


@pytest.fixture(scope="session")
def mysql_57_service(
    docker_service: DockerService,
    xdist_mysql_isolation_level: XdistIsolationLevel,
    platform: str,
) -> Generator[MySQLService, None, None]:
    with _provide_mysql_service(
        image="mysql:5.7",
        name="mysql-57",
        docker_service=docker_service,
        isolation_level=xdist_mysql_isolation_level,
        platform=platform,
    ) as service:
        yield service


@pytest.fixture(scope="session")
def mysql_8_service(
    docker_service: DockerService,
    xdist_mysql_isolation_level: XdistIsolationLevel,
    platform: str,
) -> Generator[MySQLService, None, None]:
    with _provide_mysql_service(
        image="mysql:8",
        name="mysql-8",
        docker_service=docker_service,
        isolation_level=xdist_mysql_isolation_level,
        platform=platform,
    ) as service:
        yield service


@pytest.fixture(scope="session")
def mysql_84_service(
    docker_service: DockerService,
    xdist_mysql_isolation_level: XdistIsolationLevel,
    platform: str,
) -> Generator[MySQLService, None, None]:
    with _provide_mysql_service(
        image="mysql:8.4",
        name="mysql-8.4",
        docker_service=docker_service,
        isolation_level=xdist_mysql_isolation_level,
        platform=platform,
    ) as service:
        yield service


@pytest.fixture(scope="session")
def mysql_96_service(
    docker_service: DockerService,
    xdist_mysql_isolation_level: XdistIsolationLevel,
    platform: str,
) -> Generator[MySQLService, None, None]:
    with _provide_mysql_service(
        image="mysql:9.6",
        name="mysql-9.6",
        docker_service=docker_service,
        isolation_level=xdist_mysql_isolation_level,
        platform=platform,
    ) as service:
        yield service


@pytest.fixture(scope="session")
def mysql_56_connection(mysql_56_service: MySQLService) -> Generator[Any, None, None]:
    warnings.warn(
        "The 'mysql_56_connection' fixture is deprecated and will be removed in a future release. "
        "To recreate this connection, you can use the following snippet:\n\n"
        "import mysql.connector\n\n"
        '@pytest.fixture(scope="session")\n'
        "def my_mysql_connection(mysql_56_service):\n"
        "    with mysql.connector.connect(\n"
        "        host=mysql_56_service.host,\n"
        "        port=mysql_56_service.port,\n"
        "        user=mysql_56_service.user,\n"
        "        database=mysql_56_service.db,\n"
        "        password=mysql_56_service.password,\n"
        "    ) as conn:\n"
        "        yield conn",
        DeprecationWarning,
        stacklevel=2,
    )
    import mysql.connector  # noqa: PLC0415
    with mysql.connector.connect(
        host=mysql_56_service.host,
        port=mysql_56_service.port,
        user=mysql_56_service.user,
        database=mysql_56_service.db,
        password=mysql_56_service.password,
    ) as conn:
        yield conn


@pytest.fixture(scope="session")
def mysql_57_connection(mysql_57_service: MySQLService) -> Generator[Any, None, None]:
    warnings.warn(
        "The 'mysql_57_connection' fixture is deprecated and will be removed in a future release. "
        "To recreate this connection, you can use the following snippet:\n\n"
        "import mysql.connector\n\n"
        '@pytest.fixture(scope="session")\n'
        "def my_mysql_connection(mysql_57_service):\n"
        "    with mysql.connector.connect(\n"
        "        host=mysql_57_service.host,\n"
        "        port=mysql_57_service.port,\n"
        "        user=mysql_57_service.user,\n"
        "        database=mysql_57_service.db,\n"
        "        password=mysql_57_service.password,\n"
        "    ) as conn:\n"
        "        yield conn",
        DeprecationWarning,
        stacklevel=2,
    )
    import mysql.connector  # noqa: PLC0415
    with mysql.connector.connect(
        host=mysql_57_service.host,
        port=mysql_57_service.port,
        user=mysql_57_service.user,
        database=mysql_57_service.db,
        password=mysql_57_service.password,
    ) as conn:
        yield conn


@pytest.fixture(scope="session")
def mysql_connection(mysql_84_connection: Any) -> Any:
    return mysql_84_connection


@pytest.fixture(scope="session")
def mysql_8_connection(mysql_8_service: MySQLService) -> Generator[Any, None, None]:
    warnings.warn(
        "The 'mysql_8_connection' fixture is deprecated and will be removed in a future release. "
        "To recreate this connection, you can use the following snippet:\n\n"
        "import mysql.connector\n\n"
        '@pytest.fixture(scope="session")\n'
        "def my_mysql_connection(mysql_8_service):\n"
        "    with mysql.connector.connect(\n"
        "        host=mysql_8_service.host,\n"
        "        port=mysql_8_service.port,\n"
        "        user=mysql_8_service.user,\n"
        "        database=mysql_8_service.db,\n"
        "        password=mysql_8_service.password,\n"
        "    ) as conn:\n"
        "        yield conn",
        DeprecationWarning,
        stacklevel=2,
    )
    import mysql.connector  # noqa: PLC0415
    with mysql.connector.connect(
        host=mysql_8_service.host,
        port=mysql_8_service.port,
        user=mysql_8_service.user,
        database=mysql_8_service.db,
        password=mysql_8_service.password,
    ) as conn:
        yield conn


@pytest.fixture(scope="session")
def mysql_84_connection(mysql_84_service: MySQLService) -> Generator[Any, None, None]:
    warnings.warn(
        "The 'mysql_84_connection' fixture is deprecated and will be removed in a future release. "
        "To recreate this connection, you can use the following snippet:\n\n"
        "import mysql.connector\n\n"
        '@pytest.fixture(scope="session")\n'
        "def my_mysql_connection(mysql_84_service):\n"
        "    with mysql.connector.connect(\n"
        "        host=mysql_84_service.host,\n"
        "        port=mysql_84_service.port,\n"
        "        user=mysql_84_service.user,\n"
        "        database=mysql_84_service.db,\n"
        "        password=mysql_84_service.password,\n"
        "    ) as conn:\n"
        "        yield conn",
        DeprecationWarning,
        stacklevel=2,
    )
    import mysql.connector  # noqa: PLC0415
    with mysql.connector.connect(
        host=mysql_84_service.host,
        port=mysql_84_service.port,
        user=mysql_84_service.user,
        database=mysql_84_service.db,
        password=mysql_84_service.password,
    ) as conn:
        yield conn


@pytest.fixture(scope="session")
def mysql_96_connection(mysql_96_service: MySQLService) -> Generator[Any, None, None]:
    warnings.warn(
        "The 'mysql_96_connection' fixture is deprecated and will be removed in a future release. "
        "To recreate this connection, you can use the following snippet:\n\n"
        "import mysql.connector\n\n"
        '@pytest.fixture(scope="session")\n'
        "def my_mysql_connection(mysql_96_service):\n"
        "    with mysql.connector.connect(\n"
        "        host=mysql_96_service.host,\n"
        "        port=mysql_96_service.port,\n"
        "        user=mysql_96_service.user,\n"
        "        database=mysql_96_service.db,\n"
        "        password=mysql_96_service.password,\n"
        "    ) as conn:\n"
        "        yield conn",
        DeprecationWarning,
        stacklevel=2,
    )
    import mysql.connector  # noqa: PLC0415
    with mysql.connector.connect(
        host=mysql_96_service.host,
        port=mysql_96_service.port,
        user=mysql_96_service.user,
        database=mysql_96_service.db,
        password=mysql_96_service.password,
    ) as conn:
        yield conn
