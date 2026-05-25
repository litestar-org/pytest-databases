from __future__ import annotations

import contextlib
import os
import time
from dataclasses import dataclass
from typing import TYPE_CHECKING

import pytest
from docker.errors import APIError, NotFound

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


@pytest.fixture(scope="session")
def dolt_user() -> str:
    return os.getenv("DOLT_USER", "app")


@pytest.fixture(scope="session")
def dolt_password() -> str:
    return os.getenv("DOLT_PASSWORD", "super-secret")


@pytest.fixture(scope="session")
def dolt_root_password() -> str:
    return os.getenv("DOLT_ROOT_PASSWORD", "super-secret")


@pytest.fixture(scope="session")
def dolt_database() -> str:
    return os.getenv("DOLT_DATABASE", "db")


@contextlib.contextmanager
def _provide_dolt_service(
    docker_service: DockerService,
    image: str,
    name: str,
    isolation_level: XdistIsolationLevel,
    platform: str,
    user: str,
    password: str,
    root_password: str,
    database: str,
) -> Generator[DoltService, None, None]:
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
        # Ensure the worker-specific database exists and permissions are correct.
        # Grant global privileges to the app user so tests can create databases
        # if needed, matching the MySQL/MariaDB pattern.
        container_name = f"pytest_databases_{name}"
        setup_sql = (
            f"CREATE DATABASE IF NOT EXISTS {db_name}; GRANT ALL PRIVILEGES ON *.* TO '{user}'@'%'; FLUSH PRIVILEGES;"
        )
        # Refetch the container on each attempt: with transient containers under
        # parallel xdist, the post-readiness window can race with auto-remove and
        # a handle cached above the loop would 404 on every retry.
        last_error: str | None = None
        for attempt in range(5):
            container = docker_service._get_container(container_name)
            if container is None:
                last_error = "container not found"
            else:
                try:
                    res = container.exec_run(["dolt", "sql", "-q", setup_sql])
                except NotFound:
                    last_error = "container removed mid-exec"
                except APIError as exc:
                    if exc.status_code not in {404, 409}:
                        raise
                    last_error = f"docker api {exc.status_code}"
                else:
                    if res.exit_code == 0:
                        break
                    raw = res.output if isinstance(res.output, bytes) else b""
                    last_error = f"exit {res.exit_code}: {raw.decode(errors='replace').strip()}"
            if attempt < 4:
                time.sleep(1)
        else:
            msg = f"Dolt setup SQL failed after 5 attempts: {last_error}"
            raise RuntimeError(msg)

        yield DoltService(
            host=service.host,
            port=service.port,
            container=service.container,
            db=db_name,
            user=user,
            password=password,
        )


@pytest.fixture(scope="session")
def dolt_service(
    docker_service: DockerService,
    xdist_dolt_isolation_level: XdistIsolationLevel,
    platform: str,
    dolt_user: str,
    dolt_password: str,
    dolt_root_password: str,
    dolt_database: str,
) -> Generator[DoltService, None, None]:
    with _provide_dolt_service(
        image="dolthub/dolt-sql-server:latest",
        name="dolt",
        docker_service=docker_service,
        isolation_level=xdist_dolt_isolation_level,
        platform=platform,
        user=dolt_user,
        password=dolt_password,
        root_password=dolt_root_password,
        database=dolt_database,
    ) as service:
        yield service
