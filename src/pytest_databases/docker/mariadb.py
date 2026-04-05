from __future__ import annotations

import contextlib
import os
import warnings
from collections.abc import Generator
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

import pytest

from pytest_databases.helpers import get_xdist_worker_num
from pytest_databases.types import ServiceContainer, XdistIsolationLevel

if TYPE_CHECKING:
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
def _provide_mariadb_service(
    docker_service: DockerService,
    image: str,
    name: str,
    isolation_level: XdistIsolationLevel,
) -> Generator[MariaDBService, None, None]:
    user = os.getenv("MARIADB_USER", "app")
    password = os.getenv("MARIADB_PASSWORD", "super-secret")
    root_password = os.getenv("MARIADB_ROOT_PASSWORD", "super-secret")
    database = os.getenv("MARIADB_DATABASE", "db")

    def check(_service: ServiceContainer) -> bool:
        container_name = f"pytest_databases_{name}"
        container = docker_service._get_container(container_name)
        if not container:
            return False

        # Attempt to run a simple SELECT 1 to ensure the server is fully ready
        res = container.exec_run(
            ["mariadb", f"--user=root", f"--password={root_password}", "-e", "SELECT 1"],
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
            "MARIADB_ROOT_PASSWORD": root_password,
            "MARIADB_PASSWORD": password,
            "MARIADB_USER": user,
            "MARIADB_DATABASE": database,
            "MARIADB_ROOT_HOST": "%",
            "LANG": "C.UTF-8",
        },
        timeout=120,
        pause=1.0,
        transient=isolation_level == "server",
    ) as service:
        # Final setup: ensure the worker-specific database exists and permissions are correct
        container_name = f"pytest_databases_{name}"
        container = docker_service._get_container(container_name)
        if container:
            setup_sql = (
                f"CREATE DATABASE IF NOT EXISTS {db_name}; "
                f"GRANT ALL PRIVILEGES ON *.* TO '{user}'@'%'; "
                "FLUSH PRIVILEGES;"
            )
            # Retry setup a few times if it fails
            for _ in range(5):
                res = container.exec_run(
                    ["mariadb", f"--user=root", f"--password={root_password}", "-e", setup_sql],
                )
                if res.exit_code == 0:
                    break
                import time
                time.sleep(1)

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
    with _provide_mariadb_service(
        docker_service=docker_service,
        image="mariadb:11.3",
        name="mariadb-11.3",
        isolation_level=xdist_mariadb_isolation_level,
    ) as service:
        yield service


@pytest.fixture(autouse=False, scope="session")
def mariadb_114_service(
    docker_service: DockerService,
    xdist_mariadb_isolation_level: XdistIsolationLevel,
) -> Generator[MariaDBService, None, None]:
    with _provide_mariadb_service(
        docker_service=docker_service,
        image="mariadb:11.4",
        name="mariadb-11.4",
        isolation_level=xdist_mariadb_isolation_level,
    ) as service:
        yield service


@pytest.fixture(autouse=False, scope="session")
def mariadb_122_service(
    docker_service: DockerService,
    xdist_mariadb_isolation_level: XdistIsolationLevel,
) -> Generator[MariaDBService, None, None]:
    with _provide_mariadb_service(
        docker_service=docker_service,
        image="mariadb:12.2",
        name="mariadb-12.2",
        isolation_level=xdist_mariadb_isolation_level,
    ) as service:
        yield service


@pytest.fixture(autouse=False, scope="session")
def mariadb_service(mariadb_114_service: MariaDBService) -> MariaDBService:
    return mariadb_114_service


@pytest.fixture(autouse=False, scope="session")
def mariadb_113_connection(mariadb_113_service: MariaDBService) -> Generator[Any, None, None]:
    warnings.warn(
        "The 'mariadb_113_connection' fixture is deprecated and will be removed in a future release. "
        "To recreate this connection, you can use the following snippet:\n\n"
        "import mariadb\n\n"
        "@pytest.fixture(scope=\"session\")\n"
        "def my_mariadb_connection(mariadb_113_service):\n"
        "    with mariadb.connect(\n"
        "        host=mariadb_113_service.host,\n"
        "        port=mariadb_113_service.port,\n"
        "        user=mariadb_113_service.user,\n"
        "        database=mariadb_113_service.db,\n"
        "        password=mariadb_113_service.password,\n"
        "    ) as conn:\n"
        "        yield conn",
        DeprecationWarning,
        stacklevel=2,
    )
    import mariadb
    with mariadb.connect(
        host=mariadb_113_service.host,
        port=mariadb_113_service.port,
        user=mariadb_113_service.user,
        database=mariadb_113_service.db,
        password=mariadb_113_service.password,
    ) as conn:
        yield conn


@pytest.fixture(autouse=False, scope="session")
def mariadb_114_connection(mariadb_114_service: MariaDBService) -> Generator[Any, None, None]:
    warnings.warn(
        "The 'mariadb_114_connection' fixture is deprecated and will be removed in a future release. "
        "To recreate this connection, you can use the following snippet:\n\n"
        "import mariadb\n\n"
        "@pytest.fixture(scope=\"session\")\n"
        "def my_mariadb_connection(mariadb_114_service):\n"
        "    with mariadb.connect(\n"
        "        host=mariadb_114_service.host,\n"
        "        port=mariadb_114_service.port,\n"
        "        user=mariadb_114_service.user,\n"
        "        database=mariadb_114_service.db,\n"
        "        password=mariadb_114_service.password,\n"
        "    ) as conn:\n"
        "        yield conn",
        DeprecationWarning,
        stacklevel=2,
    )
    import mariadb
    with mariadb.connect(
        host=mariadb_114_service.host,
        port=mariadb_114_service.port,
        user=mariadb_114_service.user,
        database=mariadb_114_service.db,
        password=mariadb_114_service.password,
    ) as conn:
        yield conn


@pytest.fixture(autouse=False, scope="session")
def mariadb_122_connection(mariadb_122_service: MariaDBService) -> Generator[Any, None, None]:
    warnings.warn(
        "The 'mariadb_122_connection' fixture is deprecated and will be removed in a future release. "
        "To recreate this connection, you can use the following snippet:\n\n"
        "import mariadb\n\n"
        "@pytest.fixture(scope=\"session\")\n"
        "def my_mariadb_connection(mariadb_122_service):\n"
        "    with mariadb.connect(\n"
        "        host=mariadb_122_service.host,\n"
        "        port=mariadb_122_service.port,\n"
        "        user=mariadb_122_service.user,\n"
        "        database=mariadb_122_service.db,\n"
        "        password=mariadb_122_service.password,\n"
        "    ) as conn:\n"
        "        yield conn",
        DeprecationWarning,
        stacklevel=2,
    )
    import mariadb
    with mariadb.connect(
        host=mariadb_122_service.host,
        port=mariadb_122_service.port,
        user=mariadb_122_service.user,
        database=mariadb_122_service.db,
        password=mariadb_122_service.password,
    ) as conn:
        yield conn


@pytest.fixture(autouse=False, scope="session")
def mariadb_connection(mariadb_114_connection: Any) -> Any:
    return mariadb_114_connection
