"""MariaDB container service fixtures."""

from __future__ import annotations

import contextlib
import os
import time
from dataclasses import dataclass
from typing import TYPE_CHECKING

import pytest

from pytest_databases.helpers import exec_output_to_bytes, get_xdist_worker_num
from pytest_databases.types import ServiceContainer, XdistIsolationLevel

if TYPE_CHECKING:
    from collections.abc import Generator

    from pytest_databases._service import DockerService

__all__ = (
    "MariaDBService",
    "mariadb_113_service",
    "mariadb_114_service",
    "mariadb_118_service",
    "mariadb_122_service",
    "mariadb_123_service",
    "mariadb_130_service",
    "mariadb_database",
    "mariadb_password",
    "mariadb_root_password",
    "mariadb_service",
    "mariadb_user",
    "provide_mariadb_service",
    "xdist_mariadb_isolation_level",
)


@dataclass
class MariaDBService(ServiceContainer):
    """Service handle for a running MariaDB container."""

    db: str
    user: str
    password: str


@contextlib.contextmanager
def provide_mariadb_service(
    docker_service: DockerService,
    image: str,
    name: str,
    isolation_level: XdistIsolationLevel,
    user: str,
    password: str,
    root_password: str,
    database: str,
) -> Generator[MariaDBService, None, None]:
    """Start and manage a MariaDB container service with performance_schema enabled.

    Yields:
        Active MariaDBService instance.

    Raises:
        RuntimeError: If database and application user grants cannot be verified.
    """

    def check(_service: ServiceContainer) -> bool:
        res = _service.container.exec_run(
            ["mariadb", "--user=root", f"--password={root_password}", "-e", "SELECT 1"],
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
        setup_sql = (
            f"CREATE DATABASE IF NOT EXISTS {db_name}; GRANT ALL PRIVILEGES ON *.* TO '{user}'@'%'; FLUSH PRIVILEGES;"
        )
        verify_cmd = [
            "mariadb",
            f"--user={user}",
            f"--password={password}",
            db_name,
            "-e",
            "SELECT 1",
        ]
        last_err: bytes = b""
        for attempt in range(15):
            setup_res = service.container.exec_run(
                ["mariadb", "--user=root", f"--password={root_password}", "-e", setup_sql],
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
                f"MariaDB fixture {name!r}: user {user!r} could not reach database "
                f"{db_name!r} after 15 attempts. Last output: {last_err!r}"
            )
            raise RuntimeError(msg)

        yield MariaDBService(
            host=service.host,
            port=service.port,
            container=service.container,
            db=db_name,
            user=user,
            password=password,
        )


@pytest.fixture(scope="session")
def xdist_mariadb_isolation_level() -> XdistIsolationLevel:
    """Return the pytest-xdist isolation level for MariaDB."""
    return "database"


@pytest.fixture(scope="session")
def mariadb_user() -> str:
    """Return the MariaDB application user."""
    return os.getenv("MARIADB_USER", "app")


@pytest.fixture(scope="session")
def mariadb_password() -> str:
    """Return the MariaDB application password."""
    return os.getenv("MARIADB_PASSWORD", "super-secret")


@pytest.fixture(scope="session")
def mariadb_root_password() -> str:
    """Return the MariaDB root password."""
    return os.getenv("MARIADB_ROOT_PASSWORD", "super-secret")


@pytest.fixture(scope="session")
def mariadb_database() -> str:
    """Return the MariaDB database name."""
    return os.getenv("MARIADB_DATABASE", "db")


@pytest.fixture(autouse=False, scope="session")
def mariadb_113_service(
    docker_service: DockerService,
    xdist_mariadb_isolation_level: XdistIsolationLevel,
    mariadb_user: str,
    mariadb_password: str,
    mariadb_root_password: str,
    mariadb_database: str,
) -> Generator[MariaDBService, None, None]:
    """Provide a running MariaDB 11.3 container service.

    Yields:
        Active MariaDBService instance.
    """
    with provide_mariadb_service(
        docker_service=docker_service,
        image="mariadb:11.3",
        name="mariadb-11.3",
        isolation_level=xdist_mariadb_isolation_level,
        user=mariadb_user,
        password=mariadb_password,
        root_password=mariadb_root_password,
        database=mariadb_database,
    ) as service:
        yield service


@pytest.fixture(autouse=False, scope="session")
def mariadb_114_service(
    docker_service: DockerService,
    xdist_mariadb_isolation_level: XdistIsolationLevel,
    mariadb_user: str,
    mariadb_password: str,
    mariadb_root_password: str,
    mariadb_database: str,
) -> Generator[MariaDBService, None, None]:
    """Provide a running MariaDB 11.4 container service.

    Yields:
        Active MariaDBService instance.
    """
    with provide_mariadb_service(
        docker_service=docker_service,
        image="mariadb:11.4",
        name="mariadb-11.4",
        isolation_level=xdist_mariadb_isolation_level,
        user=mariadb_user,
        password=mariadb_password,
        root_password=mariadb_root_password,
        database=mariadb_database,
    ) as service:
        yield service


@pytest.fixture(autouse=False, scope="session")
def mariadb_118_service(
    docker_service: DockerService,
    xdist_mariadb_isolation_level: XdistIsolationLevel,
    mariadb_user: str,
    mariadb_password: str,
    mariadb_root_password: str,
    mariadb_database: str,
) -> Generator[MariaDBService, None, None]:
    """Provide a running MariaDB 11.8 LTS container service.

    Yields:
        Active MariaDBService instance.
    """
    with provide_mariadb_service(
        docker_service=docker_service,
        image="mariadb:11.8",
        name="mariadb-11.8",
        isolation_level=xdist_mariadb_isolation_level,
        user=mariadb_user,
        password=mariadb_password,
        root_password=mariadb_root_password,
        database=mariadb_database,
    ) as service:
        yield service


@pytest.fixture(autouse=False, scope="session")
def mariadb_122_service(
    docker_service: DockerService,
    xdist_mariadb_isolation_level: XdistIsolationLevel,
    mariadb_user: str,
    mariadb_password: str,
    mariadb_root_password: str,
    mariadb_database: str,
) -> Generator[MariaDBService, None, None]:
    """Provide a running MariaDB 12.2 container service.

    Yields:
        Active MariaDBService instance.
    """
    with provide_mariadb_service(
        docker_service=docker_service,
        image="mariadb:12.2",
        name="mariadb-12.2",
        isolation_level=xdist_mariadb_isolation_level,
        user=mariadb_user,
        password=mariadb_password,
        root_password=mariadb_root_password,
        database=mariadb_database,
    ) as service:
        yield service


@pytest.fixture(autouse=False, scope="session")
def mariadb_123_service(
    docker_service: DockerService,
    xdist_mariadb_isolation_level: XdistIsolationLevel,
    mariadb_user: str,
    mariadb_password: str,
    mariadb_root_password: str,
    mariadb_database: str,
) -> Generator[MariaDBService, None, None]:
    """Provide a running MariaDB 12.3 container service.

    Yields:
        Active MariaDBService instance.
    """
    with provide_mariadb_service(
        docker_service=docker_service,
        image="mariadb:12.3",
        name="mariadb-12.3",
        isolation_level=xdist_mariadb_isolation_level,
        user=mariadb_user,
        password=mariadb_password,
        root_password=mariadb_root_password,
        database=mariadb_database,
    ) as service:
        yield service


@pytest.fixture(autouse=False, scope="session")
def mariadb_130_service(
    docker_service: DockerService,
    xdist_mariadb_isolation_level: XdistIsolationLevel,
    mariadb_user: str,
    mariadb_password: str,
    mariadb_root_password: str,
    mariadb_database: str,
) -> Generator[MariaDBService, None, None]:
    """Provide a running MariaDB 13.0 container service.

    Yields:
        Active MariaDBService instance.
    """
    with provide_mariadb_service(
        docker_service=docker_service,
        image="mariadb:13.0",
        name="mariadb-13.0",
        isolation_level=xdist_mariadb_isolation_level,
        user=mariadb_user,
        password=mariadb_password,
        root_password=mariadb_root_password,
        database=mariadb_database,
    ) as service:
        yield service


@pytest.fixture(autouse=False, scope="session")
def mariadb_service(mariadb_114_service: MariaDBService) -> MariaDBService:
    """Provide the default MariaDB container service."""
    return mariadb_114_service
