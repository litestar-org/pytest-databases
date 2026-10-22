"""CockroachDB container service fixtures."""

from __future__ import annotations

import contextlib
import dataclasses
import importlib
import time
import warnings
from typing import TYPE_CHECKING, Any

import pytest

from pytest_databases.helpers import exec_output_to_bytes, get_xdist_worker_num
from pytest_databases.types import ServiceContainer

if TYPE_CHECKING:
    from collections.abc import Generator

    from docker.models.containers import Container

    from pytest_databases._service import DockerService
    from pytest_databases.types import XdistIsolationLevel

__all__ = (
    "COCKROACHDB_DATABASE",
    "COCKROACHDB_USER",
    "CockroachDBService",
    "cockroachdb_connection",
    "cockroachdb_driver_opts",
    "cockroachdb_image",
    "cockroachdb_service",
    "cockroachdb_startup_connection",
    "open_cockroachdb_connection",
    "provide_cockroachdb_service",
    "xdist_cockroachdb_isolation_level",
)

COCKROACHDB_USER = "root"
COCKROACHDB_DATABASE = "pytest_databases"


@dataclasses.dataclass
class CockroachDBService(ServiceContainer):
    """Service handle for a running CockroachDB container."""

    database: str
    driver_opts: dict[str, str] = dataclasses.field(default_factory=lambda: {"sslmode": "disable"})


@contextlib.contextmanager
def provide_cockroachdb_service(
    docker_service: DockerService,
    isolation_level: XdistIsolationLevel,
    driver_opts: dict[str, str],
    image: str,
) -> Generator[CockroachDBService, None, None]:
    """Start and manage a CockroachDB container service.

    Yields:
        Active CockroachDBService instance.
    """

    def check(_service: ServiceContainer) -> bool:
        exit_code, _ = _exec_cockroach_sql(_service.container, "SELECT 1")
        return exit_code == 0

    container_name = "cockroachdb"
    db_name = COCKROACHDB_DATABASE
    worker_num = get_xdist_worker_num()
    if worker_num is not None:
        suffix = f"_{worker_num}"
        if isolation_level == "server":
            container_name += suffix
        else:
            db_name += suffix

    with docker_service.run(
        image=image,
        container_port=26257,
        check=check,
        name=container_name,
        command="start-single-node --insecure",
        transient=isolation_level == "server",
    ) as service:
        _prepare_database(service.container, db_name)

        yield CockroachDBService(
            host=service.host,
            port=service.port,
            container=service.container,
            database=db_name,
            driver_opts=driver_opts,
        )


@contextlib.contextmanager
def open_cockroachdb_connection(
    service: CockroachDBService,
    driver_opts: dict[str, str],
    *,
    fixture_name: str = "open_cockroachdb_connection",
) -> Generator[Any, None, None]:
    """Emit a DeprecationWarning and open a psycopg connection to CockroachDB.

    Yields:
        Active psycopg connection.
    """
    warnings.warn(
        f"'{fixture_name}' is deprecated and will be removed in a future release. "
        "Use 'cockroachdb_service' and instantiate your psycopg client directly.",
        DeprecationWarning,
        stacklevel=2,
    )
    psycopg = importlib.import_module("psycopg")
    opts = "&".join(f"{k}={v}" for k, v in driver_opts.items()) if driver_opts else ""
    conn_str = f"postgresql://{COCKROACHDB_USER}@{service.host}:{service.port}/{service.database}"
    if opts:
        conn_str = f"{conn_str}?{opts}"
    with psycopg.connect(conn_str) as conn:
        yield conn


@pytest.fixture(scope="session")
def xdist_cockroachdb_isolation_level() -> XdistIsolationLevel:
    """Return the pytest-xdist isolation level for CockroachDB.

    Returns:
        Default isolation level string.
    """
    return "database"


@pytest.fixture(scope="session")
def cockroachdb_driver_opts() -> dict[str, str]:
    """Return default PostgreSQL wire-protocol driver options for CockroachDB.

    Returns:
        Dictionary of connection option key-value pairs.
    """
    return {"sslmode": "disable"}


@pytest.fixture(scope="session")
def cockroachdb_image() -> str:
    """Return the CockroachDB container image.

    Returns:
        Container image tag.
    """
    return "cockroachdb/cockroach:latest"


@pytest.fixture(scope="session")
def cockroachdb_service(
    docker_service: DockerService,
    xdist_cockroachdb_isolation_level: XdistIsolationLevel,
    cockroachdb_driver_opts: dict[str, str],
    cockroachdb_image: str,
) -> Generator[CockroachDBService, None, None]:
    """Provide a running CockroachDB container service.

    Yields:
        Active CockroachDBService instance.
    """
    with provide_cockroachdb_service(
        docker_service=docker_service,
        isolation_level=xdist_cockroachdb_isolation_level,
        driver_opts=cockroachdb_driver_opts,
        image=cockroachdb_image,
    ) as service:
        yield service


@pytest.fixture(scope="session")
def cockroachdb_connection(
    cockroachdb_service: CockroachDBService,
    cockroachdb_driver_opts: dict[str, str],
) -> Generator[Any, None, None]:
    """Provide a deprecated psycopg connection to CockroachDB.

    Yields:
        Active psycopg connection.
    """
    with open_cockroachdb_connection(
        cockroachdb_service,
        cockroachdb_driver_opts,
        fixture_name="cockroachdb_connection",
    ) as conn:
        yield conn


@pytest.fixture(scope="session")
def cockroachdb_startup_connection(
    cockroachdb_service: CockroachDBService,
    cockroachdb_driver_opts: dict[str, str],
) -> Generator[Any, None, None]:
    """Provide a deprecated startup psycopg connection to CockroachDB.

    Yields:
        Active psycopg connection.
    """
    with open_cockroachdb_connection(
        cockroachdb_service,
        cockroachdb_driver_opts,
        fixture_name="cockroachdb_startup_connection",
    ) as conn:
        yield conn


def _quote_identifier(value: str) -> str:
    return f'"{value.replace(chr(34), chr(34) * 2)}"'


def _exec_cockroach_sql(
    container: Container,
    sql: str,
    *,
    database: str = "defaultdb",
) -> tuple[int, bytes]:
    result = container.exec_run([
        "cockroach",
        "sql",
        "--insecure",
        "--host=localhost:26257",
        f"--database={database}",
        "--format=tsv",
        "-e",
        sql,
    ])
    return result.exit_code if result.exit_code is not None else -1, exec_output_to_bytes(result.output)


def _prepare_database(container: Container, database: str) -> None:
    quoted_database = _quote_identifier(database)
    last_output = b""
    for attempt in range(15):
        exit_code, output = _exec_cockroach_sql(
            container,
            f"CREATE DATABASE IF NOT EXISTS {quoted_database}",
        )
        if exit_code == 0:
            verify_code, verify_output = _exec_cockroach_sql(
                container,
                "SELECT 1",
                database=database,
            )
            if verify_code == 0:
                return
            last_output = verify_output
        else:
            last_output = output
        time.sleep(1 + attempt * 0.5)

    msg = f"CockroachDB database {database!r} could not be prepared. Last output: {last_output!r}"
    raise RuntimeError(msg)
