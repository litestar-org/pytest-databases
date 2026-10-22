"""Dolt container service fixtures."""

from __future__ import annotations

import contextlib
import os
import time
from dataclasses import dataclass
from typing import TYPE_CHECKING

import pytest
from docker.errors import APIError, NotFound

from pytest_databases.helpers import exec_output_to_bytes, get_xdist_worker_num
from pytest_databases.types import ServiceContainer, XdistIsolationLevel

if TYPE_CHECKING:
    from collections.abc import Generator

    from pytest_databases._service import DockerService

__all__ = (
    "DoltService",
    "dolt_database",
    "dolt_image",
    "dolt_password",
    "dolt_platform",
    "dolt_root_password",
    "dolt_service",
    "dolt_user",
    "platform",
    "provide_dolt_service",
    "xdist_dolt_isolation_level",
)


@dataclass
class DoltService(ServiceContainer):
    """Service handle for a running Dolt SQL container."""

    db: str
    user: str
    password: str


@contextlib.contextmanager
def provide_dolt_service(
    docker_service: DockerService,
    image: str,
    name: str,
    isolation_level: XdistIsolationLevel,
    platform: str | None,
    user: str,
    password: str,
    root_password: str,
    database: str,
) -> Generator[DoltService, None, None]:
    """Start and manage a Dolt SQL server container service.

    Yields:
        Active DoltService instance.

    Raises:
        RuntimeError: If database initialization SQL fails across retries.
    """

    def check(_service: ServiceContainer) -> bool:
        res = _service.container.exec_run(
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
        setup_sql = (
            f"CREATE DATABASE IF NOT EXISTS {db_name}; GRANT ALL PRIVILEGES ON *.* TO '{user}'@'%'; FLUSH PRIVILEGES;"
        )
        last_error: str | None = None
        for attempt in range(5):
            try:
                res = service.container.exec_run(["dolt", "sql", "-q", setup_sql])
            except NotFound:
                last_error = "container removed mid-exec"
            except APIError as exc:
                if exc.status_code not in {404, 409}:
                    raise
                last_error = f"docker api {exc.status_code}"
            else:
                if res.exit_code == 0:
                    break
                raw = exec_output_to_bytes(res.output)
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
def xdist_dolt_isolation_level() -> XdistIsolationLevel:
    """Return the pytest-xdist isolation level for Dolt.

    Returns:
        Default isolation level string.
    """
    return "database"


@pytest.fixture(scope="session")
def dolt_image() -> str:
    """Return the Dolt container image.

    Returns:
        Container image tag.
    """
    return "dolthub/dolt-sql-server:latest"


@pytest.fixture(scope="session")
def dolt_platform() -> str | None:
    """Return the target container platform for Dolt (None for native multi-arch).

    Returns:
        Optional platform string or None.
    """
    return None


@pytest.fixture(scope="session")
def platform(dolt_platform: str | None) -> str | None:
    """Backward-compatible platform fixture alias for Dolt.

    Returns:
        Optional platform string or None.
    """
    return dolt_platform


@pytest.fixture(scope="session")
def dolt_user() -> str:
    """Return the Dolt database user.

    Returns:
        Database username string.
    """
    return os.getenv("DOLT_USER", "app")


@pytest.fixture(scope="session")
def dolt_password() -> str:
    """Return the Dolt database user password.

    Returns:
        Database password string.
    """
    return os.getenv("DOLT_PASSWORD", "super-secret")


@pytest.fixture(scope="session")
def dolt_root_password() -> str:
    """Return the Dolt root password.

    Returns:
        Root password string.
    """
    return os.getenv("DOLT_ROOT_PASSWORD", "super-secret")


@pytest.fixture(scope="session")
def dolt_database() -> str:
    """Return the default Dolt database name.

    Returns:
        Database name string.
    """
    return os.getenv("DOLT_DATABASE", "db")


@pytest.fixture(scope="session")
def dolt_service(
    docker_service: DockerService,
    xdist_dolt_isolation_level: XdistIsolationLevel,
    dolt_image: str,
    dolt_platform: str | None,
    dolt_user: str,
    dolt_password: str,
    dolt_root_password: str,
    dolt_database: str,
) -> Generator[DoltService, None, None]:
    """Provide a running Dolt SQL container service.

    Yields:
        Active DoltService instance.
    """
    with provide_dolt_service(
        image=dolt_image,
        name="dolt",
        docker_service=docker_service,
        isolation_level=xdist_dolt_isolation_level,
        platform=dolt_platform,
        user=dolt_user,
        password=dolt_password,
        root_password=dolt_root_password,
        database=dolt_database,
    ) as service:
        yield service
