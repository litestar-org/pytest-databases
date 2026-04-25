from __future__ import annotations

import contextlib
import os
import time
from dataclasses import dataclass
from typing import TYPE_CHECKING

import pytest

from pytest_databases.helpers import get_xdist_worker_num
from pytest_databases.types import ServiceContainer, XdistIsolationLevel

if TYPE_CHECKING:
    from collections.abc import Generator

    from pytest_databases._service import DockerService


@dataclass
class DoltService(ServiceContainer):
    db: str
    user: str
    password: str


@pytest.fixture(scope="session")
def xdist_dolt_isolation_level() -> XdistIsolationLevel:
    return "database"


@pytest.fixture(scope="session")
def platform() -> str:
    return "linux/x86_64"


@contextlib.contextmanager
def _provide_dolt_service(
    docker_service: DockerService,
    image: str,
    name: str,
    isolation_level: XdistIsolationLevel,
    platform: str,
) -> Generator[DoltService, None, None]:
    user = os.getenv("DOLT_USER", "app")
    password = os.getenv("DOLT_PASSWORD", "super-secret")
    root_password = os.getenv("DOLT_ROOT_PASSWORD", "super-secret")
    database = os.getenv("DOLT_DATABASE", "db")

    def check(_service: ServiceContainer) -> bool:
        container_name = f"pytest_databases_{name}"
        container = docker_service._get_container(container_name)
        if not container:
            return False

        # Attempt to run a simple SELECT 1 to ensure the server is fully ready
        res = container.exec_run(
            ["dolt", "sql", "-q", "SELECT 1"],
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
            "DOLT_ROOT_PASSWORD": root_password,
            "DOLT_ROOT_HOST": "%",
            "DOLT_PASSWORD": password,
            "DOLT_USER": user,
            "DOLT_DATABASE": database,
        },
        timeout=120,
        pause=1.0,
        transient=isolation_level == "server",
        platform=platform,
    ) as service:
        # Final setup: ensure the worker-specific database exists and permissions are correct
        container_name = f"pytest_databases_{name}"
        container = docker_service._get_container(container_name)
        if container:
            # Dolt SQL setup for database and user permissions
            # We grant global privileges to the app user so they can create databases in tests if needed,
            # matching the MySQL/MariaDB pattern.
            setup_sql = (
                f"CREATE DATABASE IF NOT EXISTS {db_name}; "
                f"GRANT ALL PRIVILEGES ON *.* TO '{user}'@'%'; "
                "FLUSH PRIVILEGES;"
            )
            # Retry setup a few times if it fails
            for _ in range(5):
                res = container.exec_run(
                    ["dolt", "sql", "-q", setup_sql],
                )
                if res.exit_code == 0:
                    break
                time.sleep(1)

        yield DoltService(
            db=db_name,
            host=service.host,
            port=service.port,
            user=user,
            password=password,
        )


@pytest.fixture(scope="session")
def dolt_service(
    docker_service: DockerService,
    xdist_dolt_isolation_level: XdistIsolationLevel,
    platform: str,
) -> Generator[DoltService, None, None]:
    with _provide_dolt_service(
        image="dolthub/dolt-sql-server:latest",
        name="dolt",
        docker_service=docker_service,
        isolation_level=xdist_dolt_isolation_level,
        platform=platform,
    ) as service:
        yield service
