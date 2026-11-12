"""CockroachDB container service fixtures."""

from __future__ import annotations

import contextlib
import dataclasses
import importlib
import time
import warnings
from typing import TYPE_CHECKING, Any
from urllib.parse import quote, urlencode

import pytest
from docker.errors import APIError, NotFound

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
    "exec_cockroach_sql",
    "provide_cockroachdb_service",
    "xdist_cockroachdb_isolation_level",
)

COCKROACHDB_USER = "root"
COCKROACHDB_DATABASE = "pytest_databases"


def _default_cockroach_driver_opts() -> dict[str, str]:
    """Return a fresh copy of default insecure CockroachDB libpq driver options."""
    return {"sslmode": "disable"}


def exec_cockroach_sql(
    container: Container,
    sql: str,
    *,
    database: str = "defaultdb",
) -> tuple[int, bytes]:
    """Execute SQL inside a CockroachDB container using ``cockroach sql --insecure``.

    Returns:
        Tuple of ``(exit_code, output_bytes)``.
    """
    try:
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
    except (APIError, NotFound) as exc:
        return -1, str(exc).encode()
    return result.exit_code if result.exit_code is not None else -1, exec_output_to_bytes(result.output)


@dataclasses.dataclass
class CockroachDBService(ServiceContainer):
    """Service handle for a running CockroachDB container."""

    database: str
    driver_opts: dict[str, str] = dataclasses.field(default_factory=_default_cockroach_driver_opts)
    user: str = COCKROACHDB_USER

    @property
    def dsn(self) -> str:
        """Formatted ``postgresql://`` connection URI with encoded user, database, and ``driver_opts``."""
        encoded_user = quote(self.user, safe="")
        host = f"[{self.host}]" if ":" in self.host and not self.host.startswith("[") else self.host
        encoded_db = quote(self.database, safe="")
        base = f"postgresql://{encoded_user}@{host}:{self.port}/{encoded_db}"
        if self.driver_opts:
            return f"{base}?{urlencode(self.driver_opts)}"
        return base

    @property
    def connection_config(self) -> dict[str, Any]:
        """Driver keyword arguments (``host``, ``port``, ``user``, ``database``, and ``driver_opts``)."""
        return {
            "host": self.host,
            "port": self.port,
            "user": self.user,
            "database": self.database,
            **self.driver_opts,
        }

    def exec_sql(self, sql: str, *, database: str | None = None) -> tuple[int, bytes]:
        """Execute ``sql`` via :func:`exec_cockroach_sql` against ``database`` (or ``self.database``).

        Returns:
            Tuple of ``(exit_code, output_bytes)``.
        """
        return exec_cockroach_sql(self.container, sql, database=database or self.database)


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
        exit_code, _ = exec_cockroach_sql(_service.container, "SELECT 1")
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
            driver_opts=dict(driver_opts),
        )


@pytest.fixture(scope="session")
def xdist_cockroachdb_isolation_level() -> XdistIsolationLevel:
    """Return the pytest-xdist isolation level for CockroachDB."""
    return "database"


@pytest.fixture(scope="session")
def cockroachdb_driver_opts() -> dict[str, str]:
    """Return default PostgreSQL wire-protocol driver options for CockroachDB."""
    return {"sslmode": "disable"}


@pytest.fixture(scope="session")
def cockroachdb_image() -> str:
    """Return the CockroachDB container image."""
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
    with _open_cockroachdb_connection(cockroachdb_service, cockroachdb_driver_opts) as conn:
        yield conn


@contextlib.contextmanager
def _open_cockroachdb_connection(
    service: CockroachDBService,
    driver_opts: dict[str, str],
) -> Generator[Any, None, None]:
    """Emit a DeprecationWarning and open a psycopg connection to CockroachDB.

    Yields:
        Active psycopg connection.
    """
    warnings.warn(
        "The 'cockroachdb_connection' fixture is deprecated in v0.20.0 and will be removed in v1.0.0. "
        "Use 'cockroachdb_service' and instantiate your psycopg client directly.",
        DeprecationWarning,
        stacklevel=3,
    )
    psycopg = importlib.import_module("psycopg")
    conn_str = dataclasses.replace(service, driver_opts=dict(driver_opts)).dsn
    with psycopg.connect(conn_str) as conn:
        yield conn


def _quote_identifier(value: str) -> str:
    return f'"{value.replace(chr(34), chr(34) * 2)}"'


def _prepare_database(container: Container, database: str) -> None:
    quoted_database = _quote_identifier(database)
    last_output = b""
    for attempt in range(15):
        exit_code, output = exec_cockroach_sql(
            container,
            f"CREATE DATABASE IF NOT EXISTS {quoted_database}",
        )
        if exit_code == 0:
            verify_code, verify_output = exec_cockroach_sql(
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
