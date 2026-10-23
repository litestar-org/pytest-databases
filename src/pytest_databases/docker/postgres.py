"""PostgreSQL, pgvector, ParadeDB, and AlloyDB Omni container service fixtures."""

from __future__ import annotations

import dataclasses
import importlib
import os
import re
import time
import warnings
from contextlib import contextmanager
from typing import TYPE_CHECKING, Any

import pytest

from pytest_databases.helpers import exec_output_to_bytes, get_xdist_worker_num
from pytest_databases.types import ServiceContainer, XdistIsolationLevel

if TYPE_CHECKING:
    from collections.abc import Generator

    from docker.models.containers import Container
    from psycopg import Connection

    from pytest_databases._service import DockerService

__all__ = [
    "PostgresService",
    "alloydb_omni_15_connection",
    "alloydb_omni_15_port",
    "alloydb_omni_15_service",
    "alloydb_omni_16_connection",
    "alloydb_omni_16_port",
    "alloydb_omni_16_service",
    "alloydb_omni_17_connection",
    "alloydb_omni_17_port",
    "alloydb_omni_17_service",
    "alloydb_omni_18_connection",
    "alloydb_omni_18_port",
    "alloydb_omni_18_service",
    "alloydb_omni_connection",
    "alloydb_omni_image",
    "alloydb_omni_port",
    "alloydb_omni_service",
    "clone_template_database",
    "create_worker_database",
    "drop_database_force",
    "exec_psql",
    "make_connection_string",
    "paradedb_15_connection",
    "paradedb_15_port",
    "paradedb_15_service",
    "paradedb_16_connection",
    "paradedb_16_port",
    "paradedb_16_service",
    "paradedb_17_connection",
    "paradedb_17_port",
    "paradedb_17_service",
    "paradedb_18_connection",
    "paradedb_18_port",
    "paradedb_18_service",
    "paradedb_connection",
    "paradedb_image",
    "paradedb_port",
    "paradedb_service",
    "pgvector_13_connection",
    "pgvector_13_port",
    "pgvector_13_service",
    "pgvector_14_connection",
    "pgvector_14_port",
    "pgvector_14_service",
    "pgvector_15_connection",
    "pgvector_15_port",
    "pgvector_15_service",
    "pgvector_16_connection",
    "pgvector_16_port",
    "pgvector_16_service",
    "pgvector_17_connection",
    "pgvector_17_port",
    "pgvector_17_service",
    "pgvector_18_connection",
    "pgvector_18_port",
    "pgvector_18_service",
    "pgvector_connection",
    "pgvector_image",
    "pgvector_port",
    "pgvector_service",
    "postgres_11_connection",
    "postgres_11_port",
    "postgres_11_service",
    "postgres_12_connection",
    "postgres_12_port",
    "postgres_12_service",
    "postgres_13_connection",
    "postgres_13_port",
    "postgres_13_service",
    "postgres_14_connection",
    "postgres_14_port",
    "postgres_14_service",
    "postgres_15_connection",
    "postgres_15_port",
    "postgres_15_service",
    "postgres_16_connection",
    "postgres_16_port",
    "postgres_16_service",
    "postgres_17_connection",
    "postgres_17_port",
    "postgres_17_service",
    "postgres_18_connection",
    "postgres_18_port",
    "postgres_18_service",
    "postgres_connection",
    "postgres_host",
    "postgres_image",
    "postgres_password",
    "postgres_port",
    "postgres_service",
    "postgres_user",
    "provide_postgres_connection",
    "provide_postgres_service",
    "xdist_postgres_isolation_level",
]

IDENTIFIER_PATTERN = re.compile(r"^[A-Za-z_][A-Za-z0-9_$]*$")


@dataclasses.dataclass
class PostgresService(ServiceContainer):
    """Connection metadata and lifecycle helpers for a PostgreSQL-compatible container service."""

    database: str
    password: str
    user: str

    def clone_template_database(self, target_db: str, *, source_db: str | None = None) -> str:
        """Clone ``source_db`` (defaults to ``self.database``) into ``target_db``."""
        return clone_template_database(self, target_db=target_db, source_db=source_db)

    def drop_database_force(self, db_name: str) -> None:
        """Terminate active backends and drop ``db_name`` if it exists."""
        drop_database_force(self, db_name=db_name)


def make_connection_string(host: str, port: int, user: str, password: str, database: str) -> str:
    """Format a libpq connection string for PostgreSQL."""
    return f"dbname={database} user={user} host={host} port={port} password={password}"


def exec_psql(
    container: Container,
    *,
    user: str,
    password: str,
    database: str,
    sql: str,
    tuples_only: bool = False,
) -> tuple[int, bytes]:
    """Execute a SQL statement via ``psql`` over the container TCP loopback interface."""
    cmd = ["psql", "-v", "ON_ERROR_STOP=1", "-h", "localhost", "-p", "5432", "-U", user, "-d", database]
    if tuples_only:
        cmd.extend(["-tAc", sql])
    else:
        cmd.extend(["-c", sql])
    result = container.exec_run(cmd, environment={"PGPASSWORD": password})
    return result.exit_code if result.exit_code is not None else -1, exec_output_to_bytes(result.output)


def create_worker_database(
    container: Container,
    *,
    user: str,
    password: str,
    db_name: str,
) -> None:
    """Create and verify a PostgreSQL database inside the container."""
    safe_db = _validate_identifier(db_name)
    last_output = b""
    for _ in range(10):
        exit_code, output = exec_psql(
            container,
            user=user,
            password=password,
            database="postgres",
            sql=f'CREATE DATABASE "{safe_db}";',
        )
        if exit_code == 0 or b"already exists" in output:
            break
        last_output = output
        time.sleep(0.5)
    else:
        message = (
            f"CREATE DATABASE {safe_db!r} failed after 10 attempts: {last_output.decode(errors='replace').strip()}"
        )
        raise RuntimeError(message)
    exit_code, output = exec_psql(
        container,
        user=user,
        password=password,
        database=safe_db,
        sql="SELECT 1",
        tuples_only=True,
    )
    if exit_code != 0 or output.strip() != b"1":
        message = f"Verification SELECT against {safe_db!r} failed: {output.decode(errors='replace').strip()}"
        raise RuntimeError(message)


def clone_template_database(
    service: PostgresService,
    *,
    target_db: str,
    source_db: str | None = None,
) -> str:
    """Clone ``source_db`` into ``target_db`` using PostgreSQL ``CREATE DATABASE ... TEMPLATE``."""
    safe_source = _validate_identifier(source_db or service.database)
    safe_target = _validate_identifier(target_db)
    terminate_sql = (
        "SELECT pg_terminate_backend(pid) FROM pg_stat_activity "
        f"WHERE datname = '{safe_source}' AND pid <> pg_backend_pid();"
    )
    exec_psql(
        service.container,
        user=service.user,
        password=service.password,
        database="postgres",
        sql=terminate_sql,
    )
    exit_code, output = exec_psql(
        service.container,
        user=service.user,
        password=service.password,
        database="postgres",
        sql=f'CREATE DATABASE "{safe_target}" TEMPLATE "{safe_source}";',
    )
    if exit_code != 0:
        msg = (
            f"Failed to clone template database {safe_source!r} to {safe_target!r}: "
            f"{output.decode(errors='replace').strip()}"
        )
        raise RuntimeError(msg)
    return safe_target


def drop_database_force(
    service: PostgresService,
    *,
    db_name: str,
) -> None:
    """Terminate active backends and drop ``db_name`` if it exists."""
    safe_db = _validate_identifier(db_name)
    terminate_sql = (
        "SELECT pg_terminate_backend(pid) FROM pg_stat_activity "
        f"WHERE datname = '{safe_db}' AND pid <> pg_backend_pid();"
    )
    exec_psql(
        service.container,
        user=service.user,
        password=service.password,
        database="postgres",
        sql=terminate_sql,
    )
    exit_code, output = exec_psql(
        service.container,
        user=service.user,
        password=service.password,
        database="postgres",
        sql=f'DROP DATABASE IF EXISTS "{safe_db}";',
    )
    if exit_code != 0:
        msg = f"Failed to drop database {safe_db!r}: {output.decode(errors='replace').strip()}"
        raise RuntimeError(msg)


@pytest.fixture(scope="session")
def xdist_postgres_isolation_level() -> XdistIsolationLevel:
    """Return the default pytest-xdist isolation level for PostgreSQL services."""
    return "database"


@pytest.fixture(autouse=False, scope="session")
def postgres_host() -> str:
    """Return the host address for PostgreSQL containers."""
    return os.environ.get("POSTGRES_HOST", "127.0.0.1")


@pytest.fixture(autouse=False, scope="session")
def postgres_password() -> str:
    """Return the default superuser password for PostgreSQL containers."""
    return "super-secret"


@pytest.fixture(autouse=False, scope="session")
def postgres_user() -> str:
    """Return the default superuser name for PostgreSQL containers."""
    return "postgres"


@pytest.fixture(autouse=False, scope="session")
def postgres_port() -> int | None:
    """Return an optional pinned host port for the default PostgreSQL container."""
    return _env_port("POSTGRES_PORT")


@pytest.fixture(autouse=False, scope="session")
def postgres_11_port() -> int | None:
    """Return an optional pinned host port for PostgreSQL 11."""
    return _env_port("POSTGRES_11_PORT")


@pytest.fixture(autouse=False, scope="session")
def postgres_12_port() -> int | None:
    """Return an optional pinned host port for PostgreSQL 12."""
    return _env_port("POSTGRES_12_PORT")


@pytest.fixture(autouse=False, scope="session")
def postgres_13_port() -> int | None:
    """Return an optional pinned host port for PostgreSQL 13."""
    return _env_port("POSTGRES_13_PORT")


@pytest.fixture(autouse=False, scope="session")
def postgres_14_port() -> int | None:
    """Return an optional pinned host port for PostgreSQL 14."""
    return _env_port("POSTGRES_14_PORT")


@pytest.fixture(autouse=False, scope="session")
def postgres_15_port() -> int | None:
    """Return an optional pinned host port for PostgreSQL 15."""
    return _env_port("POSTGRES_15_PORT")


@pytest.fixture(autouse=False, scope="session")
def postgres_16_port() -> int | None:
    """Return an optional pinned host port for PostgreSQL 16."""
    return _env_port("POSTGRES_16_PORT")


@pytest.fixture(autouse=False, scope="session")
def postgres_17_port() -> int | None:
    """Return an optional pinned host port for PostgreSQL 17."""
    return _env_port("POSTGRES_17_PORT")


@pytest.fixture(autouse=False, scope="session")
def postgres_18_port() -> int | None:
    """Return an optional pinned host port for PostgreSQL 18."""
    return _env_port("POSTGRES_18_PORT")


@contextmanager
def provide_postgres_service(
    docker_service: DockerService,
    image: str,
    name: str,
    host: str,
    user: str,
    password: str,
    xdist_postgres_isolate: XdistIsolationLevel,
    host_port: int | None = None,
    timeout: int = 60,
    pause: float = 0.5,
) -> Generator[PostgresService, None, None]:
    """Start and validate a PostgreSQL-compatible container service using ``psql``.

    Yields:
        A configured :class:`PostgresService` instance.
    """

    def check(_service: ServiceContainer) -> bool:
        exit_code, output = exec_psql(
            _service.container,
            user=user,
            password=password,
            database="postgres",
            sql="SELECT 1",
            tuples_only=True,
        )
        return exit_code == 0 and output.strip() == b"1"

    worker_num = get_xdist_worker_num()
    db_name = "pytest_databases"
    if worker_num is not None:
        suffix = f"_{worker_num}"
        if xdist_postgres_isolate == "server":
            name += suffix
        else:
            db_name += suffix

    with docker_service.run(
        image=image,
        check=check,
        container_host=host,
        container_port=5432,
        name=name,
        env={
            "POSTGRES_PASSWORD": password,
        },
        timeout=timeout,
        pause=pause,
        transient=xdist_postgres_isolate == "server",
        host_port=host_port,
    ) as service:
        create_worker_database(
            service.container,
            user=user,
            password=password,
            db_name=db_name,
        )
        yield PostgresService(
            host=service.host,
            port=service.port,
            container=service.container,
            database=db_name,
            user=user,
            password=password,
        )


@contextmanager
def provide_postgres_connection(
    service: PostgresService,
    *,
    fixture_name: str,
) -> Generator[Connection[Any], None, None]:
    """Emit a deprecation warning and yield a ``psycopg.Connection`` for ``service``.

    Yields:
        An open ``psycopg.Connection`` connected to ``service``.
    """
    warnings.warn(
        f"The '{fixture_name}' fixture is deprecated and will be removed in a future release. "
        "Use the corresponding '*_service' fixture and construct your own psycopg connection.",
        DeprecationWarning,
        stacklevel=2,
    )
    psycopg_module = importlib.import_module("psycopg")
    with psycopg_module.connect(
        make_connection_string(
            host=service.host,
            port=service.port,
            user=service.user,
            password=service.password,
            database=service.database,
        ),
    ) as conn:
        yield conn


@pytest.fixture(autouse=False, scope="session")
def postgres_11_service(
    docker_service: DockerService,
    xdist_postgres_isolation_level: XdistIsolationLevel,
    postgres_host: str,
    postgres_user: str,
    postgres_password: str,
    postgres_11_port: int | None,
) -> Generator[PostgresService, None, None]:
    """Provide a PostgreSQL 11 service.

    Yields:
        A running :class:`PostgresService` instance.
    """
    with provide_postgres_service(
        docker_service,
        image="postgres:11",
        name="postgres-11",
        xdist_postgres_isolate=xdist_postgres_isolation_level,
        host=postgres_host,
        user=postgres_user,
        password=postgres_password,
        host_port=postgres_11_port,
    ) as service:
        yield service


@pytest.fixture(autouse=False, scope="session")
def postgres_12_service(
    docker_service: DockerService,
    xdist_postgres_isolation_level: XdistIsolationLevel,
    postgres_host: str,
    postgres_user: str,
    postgres_password: str,
    postgres_12_port: int | None,
) -> Generator[PostgresService, None, None]:
    """Provide a PostgreSQL 12 service.

    Yields:
        A running :class:`PostgresService` instance.
    """
    with provide_postgres_service(
        docker_service,
        image="postgres:12",
        name="postgres-12",
        xdist_postgres_isolate=xdist_postgres_isolation_level,
        host=postgres_host,
        user=postgres_user,
        password=postgres_password,
        host_port=postgres_12_port,
    ) as service:
        yield service


@pytest.fixture(autouse=False, scope="session")
def postgres_13_service(
    docker_service: DockerService,
    xdist_postgres_isolation_level: XdistIsolationLevel,
    postgres_host: str,
    postgres_user: str,
    postgres_password: str,
    postgres_13_port: int | None,
) -> Generator[PostgresService, None, None]:
    """Provide a PostgreSQL 13 service.

    Yields:
        A running :class:`PostgresService` instance.
    """
    with provide_postgres_service(
        docker_service,
        image="postgres:13",
        name="postgres-13",
        xdist_postgres_isolate=xdist_postgres_isolation_level,
        host=postgres_host,
        user=postgres_user,
        password=postgres_password,
        host_port=postgres_13_port,
    ) as service:
        yield service


@pytest.fixture(autouse=False, scope="session")
def postgres_14_service(
    docker_service: DockerService,
    xdist_postgres_isolation_level: XdistIsolationLevel,
    postgres_host: str,
    postgres_user: str,
    postgres_password: str,
    postgres_14_port: int | None,
) -> Generator[PostgresService, None, None]:
    """Provide a PostgreSQL 14 service.

    Yields:
        A running :class:`PostgresService` instance.
    """
    with provide_postgres_service(
        docker_service,
        image="postgres:14",
        name="postgres-14",
        xdist_postgres_isolate=xdist_postgres_isolation_level,
        host=postgres_host,
        user=postgres_user,
        password=postgres_password,
        host_port=postgres_14_port,
    ) as service:
        yield service


@pytest.fixture(autouse=False, scope="session")
def postgres_15_service(
    docker_service: DockerService,
    xdist_postgres_isolation_level: XdistIsolationLevel,
    postgres_host: str,
    postgres_user: str,
    postgres_password: str,
    postgres_15_port: int | None,
) -> Generator[PostgresService, None, None]:
    """Provide a PostgreSQL 15 service.

    Yields:
        A running :class:`PostgresService` instance.
    """
    with provide_postgres_service(
        docker_service,
        image="postgres:15",
        name="postgres-15",
        xdist_postgres_isolate=xdist_postgres_isolation_level,
        host=postgres_host,
        user=postgres_user,
        password=postgres_password,
        host_port=postgres_15_port,
    ) as service:
        yield service


@pytest.fixture(autouse=False, scope="session")
def postgres_16_service(
    docker_service: DockerService,
    xdist_postgres_isolation_level: XdistIsolationLevel,
    postgres_host: str,
    postgres_user: str,
    postgres_password: str,
    postgres_16_port: int | None,
) -> Generator[PostgresService, None, None]:
    """Provide a PostgreSQL 16 service.

    Yields:
        A running :class:`PostgresService` instance.
    """
    with provide_postgres_service(
        docker_service,
        image="postgres:16",
        name="postgres-16",
        xdist_postgres_isolate=xdist_postgres_isolation_level,
        host=postgres_host,
        user=postgres_user,
        password=postgres_password,
        host_port=postgres_16_port,
    ) as service:
        yield service


@pytest.fixture(autouse=False, scope="session")
def postgres_17_service(
    docker_service: DockerService,
    xdist_postgres_isolation_level: XdistIsolationLevel,
    postgres_host: str,
    postgres_user: str,
    postgres_password: str,
    postgres_17_port: int | None,
) -> Generator[PostgresService, None, None]:
    """Provide a PostgreSQL 17 service.

    Yields:
        A running :class:`PostgresService` instance.
    """
    with provide_postgres_service(
        docker_service,
        image="postgres:17",
        name="postgres-17",
        xdist_postgres_isolate=xdist_postgres_isolation_level,
        host=postgres_host,
        user=postgres_user,
        password=postgres_password,
        host_port=postgres_17_port,
    ) as service:
        yield service


@pytest.fixture(autouse=False, scope="session")
def postgres_18_service(
    docker_service: DockerService,
    xdist_postgres_isolation_level: XdistIsolationLevel,
    postgres_host: str,
    postgres_user: str,
    postgres_password: str,
    postgres_18_port: int | None,
) -> Generator[PostgresService, None, None]:
    """Provide a PostgreSQL 18 service.

    Yields:
        A running :class:`PostgresService` instance.
    """
    with provide_postgres_service(
        docker_service,
        image="postgres:18",
        name="postgres-18",
        xdist_postgres_isolate=xdist_postgres_isolation_level,
        host=postgres_host,
        user=postgres_user,
        password=postgres_password,
        host_port=postgres_18_port,
    ) as service:
        yield service


@pytest.fixture(autouse=False, scope="session")
def postgres_11_connection(
    postgres_11_service: PostgresService,
) -> Generator[Connection[Any], None, None]:
    """Provide a deprecated psycopg connection to PostgreSQL 11.

    Yields:
        An open ``psycopg.Connection``.
    """
    with provide_postgres_connection(postgres_11_service, fixture_name="postgres_11_connection") as conn:
        yield conn


@pytest.fixture(autouse=False, scope="session")
def postgres_12_connection(
    postgres_12_service: PostgresService,
) -> Generator[Connection[Any], None, None]:
    """Provide a deprecated psycopg connection to PostgreSQL 12.

    Yields:
        An open ``psycopg.Connection``.
    """
    with provide_postgres_connection(postgres_12_service, fixture_name="postgres_12_connection") as conn:
        yield conn


@pytest.fixture(autouse=False, scope="session")
def postgres_13_connection(
    postgres_13_service: PostgresService,
) -> Generator[Connection[Any], None, None]:
    """Provide a deprecated psycopg connection to PostgreSQL 13.

    Yields:
        An open ``psycopg.Connection``.
    """
    with provide_postgres_connection(postgres_13_service, fixture_name="postgres_13_connection") as conn:
        yield conn


@pytest.fixture(autouse=False, scope="session")
def postgres_14_connection(
    postgres_14_service: PostgresService,
) -> Generator[Connection[Any], None, None]:
    """Provide a deprecated psycopg connection to PostgreSQL 14.

    Yields:
        An open ``psycopg.Connection``.
    """
    with provide_postgres_connection(postgres_14_service, fixture_name="postgres_14_connection") as conn:
        yield conn


@pytest.fixture(autouse=False, scope="session")
def postgres_15_connection(
    postgres_15_service: PostgresService,
) -> Generator[Connection[Any], None, None]:
    """Provide a deprecated psycopg connection to PostgreSQL 15.

    Yields:
        An open ``psycopg.Connection``.
    """
    with provide_postgres_connection(postgres_15_service, fixture_name="postgres_15_connection") as conn:
        yield conn


@pytest.fixture(autouse=False, scope="session")
def postgres_16_connection(
    postgres_16_service: PostgresService,
) -> Generator[Connection[Any], None, None]:
    """Provide a deprecated psycopg connection to PostgreSQL 16.

    Yields:
        An open ``psycopg.Connection``.
    """
    with provide_postgres_connection(postgres_16_service, fixture_name="postgres_16_connection") as conn:
        yield conn


@pytest.fixture(autouse=False, scope="session")
def postgres_17_connection(
    postgres_17_service: PostgresService,
) -> Generator[Connection[Any], None, None]:
    """Provide a deprecated psycopg connection to PostgreSQL 17.

    Yields:
        An open ``psycopg.Connection``.
    """
    with provide_postgres_connection(postgres_17_service, fixture_name="postgres_17_connection") as conn:
        yield conn


@pytest.fixture(autouse=False, scope="session")
def postgres_18_connection(
    postgres_18_service: PostgresService,
) -> Generator[Connection[Any], None, None]:
    """Provide a deprecated psycopg connection to PostgreSQL 18.

    Yields:
        An open ``psycopg.Connection``.
    """
    with provide_postgres_connection(postgres_18_service, fixture_name="postgres_18_connection") as conn:
        yield conn


@pytest.fixture(autouse=False, scope="session")
def postgres_image() -> str:
    """Return the default PostgreSQL container image tag."""
    return "postgres:18"


@pytest.fixture(autouse=False, scope="session")
def postgres_service(
    docker_service: DockerService,
    postgres_image: str,
    xdist_postgres_isolation_level: XdistIsolationLevel,
    postgres_host: str,
    postgres_user: str,
    postgres_password: str,
    postgres_port: int | None,
) -> Generator[PostgresService, None, None]:
    """Provide the default PostgreSQL service.

    Yields:
        A running :class:`PostgresService` instance.
    """
    with provide_postgres_service(
        docker_service,
        image=postgres_image,
        name="postgres",
        xdist_postgres_isolate=xdist_postgres_isolation_level,
        host=postgres_host,
        user=postgres_user,
        password=postgres_password,
        host_port=postgres_port,
    ) as service:
        yield service


@pytest.fixture(autouse=False, scope="session")
def postgres_connection(
    postgres_service: PostgresService,
) -> Generator[Connection[Any], None, None]:
    """Provide a deprecated psycopg connection to the default PostgreSQL service.

    Yields:
        An open ``psycopg.Connection``.
    """
    with provide_postgres_connection(postgres_service, fixture_name="postgres_connection") as conn:
        yield conn


@pytest.fixture(autouse=False, scope="session")
def pgvector_image() -> str:
    """Return the default pgvector container image tag."""
    return "pgvector/pgvector:pg18"


@pytest.fixture(autouse=False, scope="session")
def pgvector_port() -> int | None:
    """Return an optional pinned host port for the default pgvector service."""
    return _env_port("PGVECTOR_PORT")


@pytest.fixture(autouse=False, scope="session")
def pgvector_13_port() -> int | None:
    """Return an optional pinned host port for pgvector PG13."""
    return _env_port("PGVECTOR_13_PORT")


@pytest.fixture(autouse=False, scope="session")
def pgvector_14_port() -> int | None:
    """Return an optional pinned host port for pgvector PG14."""
    return _env_port("PGVECTOR_14_PORT")


@pytest.fixture(autouse=False, scope="session")
def pgvector_15_port() -> int | None:
    """Return an optional pinned host port for pgvector PG15."""
    return _env_port("PGVECTOR_15_PORT")


@pytest.fixture(autouse=False, scope="session")
def pgvector_16_port() -> int | None:
    """Return an optional pinned host port for pgvector PG16."""
    return _env_port("PGVECTOR_16_PORT")


@pytest.fixture(autouse=False, scope="session")
def pgvector_17_port() -> int | None:
    """Return an optional pinned host port for pgvector PG17."""
    return _env_port("PGVECTOR_17_PORT")


@pytest.fixture(autouse=False, scope="session")
def pgvector_18_port() -> int | None:
    """Return an optional pinned host port for pgvector PG18."""
    return _env_port("PGVECTOR_18_PORT")


@pytest.fixture(autouse=False, scope="session")
def pgvector_service(
    docker_service: DockerService,
    pgvector_image: str,
    xdist_postgres_isolation_level: XdistIsolationLevel,
    postgres_host: str,
    postgres_user: str,
    postgres_password: str,
    pgvector_port: int | None,
) -> Generator[PostgresService, None, None]:
    """Provide the default pgvector service.

    Yields:
        A running :class:`PostgresService` instance.
    """
    with provide_postgres_service(
        docker_service,
        image=pgvector_image,
        name="pgvector",
        xdist_postgres_isolate=xdist_postgres_isolation_level,
        host=postgres_host,
        user=postgres_user,
        password=postgres_password,
        host_port=pgvector_port,
    ) as service:
        yield service


@pytest.fixture(autouse=False, scope="session")
def pgvector_13_service(
    docker_service: DockerService,
    xdist_postgres_isolation_level: XdistIsolationLevel,
    postgres_host: str,
    postgres_user: str,
    postgres_password: str,
    pgvector_13_port: int | None,
) -> Generator[PostgresService, None, None]:
    """Provide a pgvector PG13 service.

    Yields:
        A running :class:`PostgresService` instance.
    """
    with provide_postgres_service(
        docker_service,
        image="pgvector/pgvector:pg13",
        name="pgvector-13",
        xdist_postgres_isolate=xdist_postgres_isolation_level,
        host=postgres_host,
        user=postgres_user,
        password=postgres_password,
        host_port=pgvector_13_port,
    ) as service:
        yield service


@pytest.fixture(autouse=False, scope="session")
def pgvector_14_service(
    docker_service: DockerService,
    xdist_postgres_isolation_level: XdistIsolationLevel,
    postgres_host: str,
    postgres_user: str,
    postgres_password: str,
    pgvector_14_port: int | None,
) -> Generator[PostgresService, None, None]:
    """Provide a pgvector PG14 service.

    Yields:
        A running :class:`PostgresService` instance.
    """
    with provide_postgres_service(
        docker_service,
        image="pgvector/pgvector:pg14",
        name="pgvector-14",
        xdist_postgres_isolate=xdist_postgres_isolation_level,
        host=postgres_host,
        user=postgres_user,
        password=postgres_password,
        host_port=pgvector_14_port,
    ) as service:
        yield service


@pytest.fixture(autouse=False, scope="session")
def pgvector_15_service(
    docker_service: DockerService,
    xdist_postgres_isolation_level: XdistIsolationLevel,
    postgres_host: str,
    postgres_user: str,
    postgres_password: str,
    pgvector_15_port: int | None,
) -> Generator[PostgresService, None, None]:
    """Provide a pgvector PG15 service.

    Yields:
        A running :class:`PostgresService` instance.
    """
    with provide_postgres_service(
        docker_service,
        image="pgvector/pgvector:pg15",
        name="pgvector-15",
        xdist_postgres_isolate=xdist_postgres_isolation_level,
        host=postgres_host,
        user=postgres_user,
        password=postgres_password,
        host_port=pgvector_15_port,
    ) as service:
        yield service


@pytest.fixture(autouse=False, scope="session")
def pgvector_16_service(
    docker_service: DockerService,
    xdist_postgres_isolation_level: XdistIsolationLevel,
    postgres_host: str,
    postgres_user: str,
    postgres_password: str,
    pgvector_16_port: int | None,
) -> Generator[PostgresService, None, None]:
    """Provide a pgvector PG16 service.

    Yields:
        A running :class:`PostgresService` instance.
    """
    with provide_postgres_service(
        docker_service,
        image="pgvector/pgvector:pg16",
        name="pgvector-16",
        xdist_postgres_isolate=xdist_postgres_isolation_level,
        host=postgres_host,
        user=postgres_user,
        password=postgres_password,
        host_port=pgvector_16_port,
    ) as service:
        yield service


@pytest.fixture(autouse=False, scope="session")
def pgvector_17_service(
    docker_service: DockerService,
    xdist_postgres_isolation_level: XdistIsolationLevel,
    postgres_host: str,
    postgres_user: str,
    postgres_password: str,
    pgvector_17_port: int | None,
) -> Generator[PostgresService, None, None]:
    """Provide a pgvector PG17 service.

    Yields:
        A running :class:`PostgresService` instance.
    """
    with provide_postgres_service(
        docker_service,
        image="pgvector/pgvector:pg17",
        name="pgvector-17",
        xdist_postgres_isolate=xdist_postgres_isolation_level,
        host=postgres_host,
        user=postgres_user,
        password=postgres_password,
        host_port=pgvector_17_port,
    ) as service:
        yield service


@pytest.fixture(autouse=False, scope="session")
def pgvector_18_service(
    docker_service: DockerService,
    xdist_postgres_isolation_level: XdistIsolationLevel,
    postgres_host: str,
    postgres_user: str,
    postgres_password: str,
    pgvector_18_port: int | None,
) -> Generator[PostgresService, None, None]:
    """Provide a pgvector PG18 service.

    Yields:
        A running :class:`PostgresService` instance.
    """
    with provide_postgres_service(
        docker_service,
        image="pgvector/pgvector:pg18",
        name="pgvector-18",
        xdist_postgres_isolate=xdist_postgres_isolation_level,
        host=postgres_host,
        user=postgres_user,
        password=postgres_password,
        host_port=pgvector_18_port,
    ) as service:
        yield service


@pytest.fixture(autouse=False, scope="session")
def pgvector_connection(
    pgvector_service: PostgresService,
) -> Generator[Connection[Any], None, None]:
    """Provide a deprecated psycopg connection to the default pgvector service.

    Yields:
        An open ``psycopg.Connection``.
    """
    with provide_postgres_connection(pgvector_service, fixture_name="pgvector_connection") as conn:
        yield conn


@pytest.fixture(autouse=False, scope="session")
def pgvector_13_connection(
    pgvector_13_service: PostgresService,
) -> Generator[Connection[Any], None, None]:
    """Provide a deprecated psycopg connection to pgvector PG13.

    Yields:
        An open ``psycopg.Connection``.
    """
    with provide_postgres_connection(pgvector_13_service, fixture_name="pgvector_13_connection") as conn:
        yield conn


@pytest.fixture(autouse=False, scope="session")
def pgvector_14_connection(
    pgvector_14_service: PostgresService,
) -> Generator[Connection[Any], None, None]:
    """Provide a deprecated psycopg connection to pgvector PG14.

    Yields:
        An open ``psycopg.Connection``.
    """
    with provide_postgres_connection(pgvector_14_service, fixture_name="pgvector_14_connection") as conn:
        yield conn


@pytest.fixture(autouse=False, scope="session")
def pgvector_15_connection(
    pgvector_15_service: PostgresService,
) -> Generator[Connection[Any], None, None]:
    """Provide a deprecated psycopg connection to pgvector PG15.

    Yields:
        An open ``psycopg.Connection``.
    """
    with provide_postgres_connection(pgvector_15_service, fixture_name="pgvector_15_connection") as conn:
        yield conn


@pytest.fixture(autouse=False, scope="session")
def pgvector_16_connection(
    pgvector_16_service: PostgresService,
) -> Generator[Connection[Any], None, None]:
    """Provide a deprecated psycopg connection to pgvector PG16.

    Yields:
        An open ``psycopg.Connection``.
    """
    with provide_postgres_connection(pgvector_16_service, fixture_name="pgvector_16_connection") as conn:
        yield conn


@pytest.fixture(autouse=False, scope="session")
def pgvector_17_connection(
    pgvector_17_service: PostgresService,
) -> Generator[Connection[Any], None, None]:
    """Provide a deprecated psycopg connection to pgvector PG17.

    Yields:
        An open ``psycopg.Connection``.
    """
    with provide_postgres_connection(pgvector_17_service, fixture_name="pgvector_17_connection") as conn:
        yield conn


@pytest.fixture(autouse=False, scope="session")
def pgvector_18_connection(
    pgvector_18_service: PostgresService,
) -> Generator[Connection[Any], None, None]:
    """Provide a deprecated psycopg connection to pgvector PG18.

    Yields:
        An open ``psycopg.Connection``.
    """
    with provide_postgres_connection(pgvector_18_service, fixture_name="pgvector_18_connection") as conn:
        yield conn


@pytest.fixture(autouse=False, scope="session")
def paradedb_image() -> str:
    """Return the default ParadeDB container image tag."""
    return "paradedb/paradedb:latest-pg18"


@pytest.fixture(autouse=False, scope="session")
def paradedb_port() -> int | None:
    """Return an optional pinned host port for the default ParadeDB service."""
    return _env_port("PARADEDB_PORT")


@pytest.fixture(autouse=False, scope="session")
def paradedb_15_port() -> int | None:
    """Return an optional pinned host port for ParadeDB PG15."""
    return _env_port("PARADEDB_15_PORT")


@pytest.fixture(autouse=False, scope="session")
def paradedb_16_port() -> int | None:
    """Return an optional pinned host port for ParadeDB PG16."""
    return _env_port("PARADEDB_16_PORT")


@pytest.fixture(autouse=False, scope="session")
def paradedb_17_port() -> int | None:
    """Return an optional pinned host port for ParadeDB PG17."""
    return _env_port("PARADEDB_17_PORT")


@pytest.fixture(autouse=False, scope="session")
def paradedb_18_port() -> int | None:
    """Return an optional pinned host port for ParadeDB PG18."""
    return _env_port("PARADEDB_18_PORT")


@pytest.fixture(autouse=False, scope="session")
def paradedb_service(
    docker_service: DockerService,
    paradedb_image: str,
    xdist_postgres_isolation_level: XdistIsolationLevel,
    postgres_host: str,
    postgres_user: str,
    postgres_password: str,
    paradedb_port: int | None,
) -> Generator[PostgresService, None, None]:
    """Provide the default ParadeDB service.

    Yields:
        A running :class:`PostgresService` instance.
    """
    with provide_postgres_service(
        docker_service,
        image=paradedb_image,
        name="paradedb",
        xdist_postgres_isolate=xdist_postgres_isolation_level,
        host=postgres_host,
        user=postgres_user,
        password=postgres_password,
        host_port=paradedb_port,
    ) as service:
        yield service


@pytest.fixture(autouse=False, scope="session")
def paradedb_15_service(
    docker_service: DockerService,
    xdist_postgres_isolation_level: XdistIsolationLevel,
    postgres_host: str,
    postgres_user: str,
    postgres_password: str,
    paradedb_15_port: int | None,
) -> Generator[PostgresService, None, None]:
    """Provide a ParadeDB PG15 service.

    Yields:
        A running :class:`PostgresService` instance.
    """
    with provide_postgres_service(
        docker_service,
        image="paradedb/paradedb:latest-pg15",
        name="paradedb-15",
        xdist_postgres_isolate=xdist_postgres_isolation_level,
        host=postgres_host,
        user=postgres_user,
        password=postgres_password,
        host_port=paradedb_15_port,
    ) as service:
        yield service


@pytest.fixture(autouse=False, scope="session")
def paradedb_16_service(
    docker_service: DockerService,
    xdist_postgres_isolation_level: XdistIsolationLevel,
    postgres_host: str,
    postgres_user: str,
    postgres_password: str,
    paradedb_16_port: int | None,
) -> Generator[PostgresService, None, None]:
    """Provide a ParadeDB PG16 service.

    Yields:
        A running :class:`PostgresService` instance.
    """
    with provide_postgres_service(
        docker_service,
        image="paradedb/paradedb:latest-pg16",
        name="paradedb-16",
        xdist_postgres_isolate=xdist_postgres_isolation_level,
        host=postgres_host,
        user=postgres_user,
        password=postgres_password,
        host_port=paradedb_16_port,
    ) as service:
        yield service


@pytest.fixture(autouse=False, scope="session")
def paradedb_17_service(
    docker_service: DockerService,
    xdist_postgres_isolation_level: XdistIsolationLevel,
    postgres_host: str,
    postgres_user: str,
    postgres_password: str,
    paradedb_17_port: int | None,
) -> Generator[PostgresService, None, None]:
    """Provide a ParadeDB PG17 service.

    Yields:
        A running :class:`PostgresService` instance.
    """
    with provide_postgres_service(
        docker_service,
        image="paradedb/paradedb:latest-pg17",
        name="paradedb-17",
        xdist_postgres_isolate=xdist_postgres_isolation_level,
        host=postgres_host,
        user=postgres_user,
        password=postgres_password,
        host_port=paradedb_17_port,
    ) as service:
        yield service


@pytest.fixture(autouse=False, scope="session")
def paradedb_18_service(
    docker_service: DockerService,
    xdist_postgres_isolation_level: XdistIsolationLevel,
    postgres_host: str,
    postgres_user: str,
    postgres_password: str,
    paradedb_18_port: int | None,
) -> Generator[PostgresService, None, None]:
    """Provide a ParadeDB PG18 service.

    Yields:
        A running :class:`PostgresService` instance.
    """
    with provide_postgres_service(
        docker_service,
        image="paradedb/paradedb:latest-pg18",
        name="paradedb-18",
        xdist_postgres_isolate=xdist_postgres_isolation_level,
        host=postgres_host,
        user=postgres_user,
        password=postgres_password,
        host_port=paradedb_18_port,
    ) as service:
        yield service


@pytest.fixture(autouse=False, scope="session")
def paradedb_connection(
    paradedb_service: PostgresService,
) -> Generator[Connection[Any], None, None]:
    """Provide a deprecated psycopg connection to the default ParadeDB service.

    Yields:
        An open ``psycopg.Connection``.
    """
    with provide_postgres_connection(paradedb_service, fixture_name="paradedb_connection") as conn:
        yield conn


@pytest.fixture(autouse=False, scope="session")
def paradedb_15_connection(
    paradedb_15_service: PostgresService,
) -> Generator[Connection[Any], None, None]:
    """Provide a deprecated psycopg connection to ParadeDB PG15.

    Yields:
        An open ``psycopg.Connection``.
    """
    with provide_postgres_connection(paradedb_15_service, fixture_name="paradedb_15_connection") as conn:
        yield conn


@pytest.fixture(autouse=False, scope="session")
def paradedb_16_connection(
    paradedb_16_service: PostgresService,
) -> Generator[Connection[Any], None, None]:
    """Provide a deprecated psycopg connection to ParadeDB PG16.

    Yields:
        An open ``psycopg.Connection``.
    """
    with provide_postgres_connection(paradedb_16_service, fixture_name="paradedb_16_connection") as conn:
        yield conn


@pytest.fixture(autouse=False, scope="session")
def paradedb_17_connection(
    paradedb_17_service: PostgresService,
) -> Generator[Connection[Any], None, None]:
    """Provide a deprecated psycopg connection to ParadeDB PG17.

    Yields:
        An open ``psycopg.Connection``.
    """
    with provide_postgres_connection(paradedb_17_service, fixture_name="paradedb_17_connection") as conn:
        yield conn


@pytest.fixture(autouse=False, scope="session")
def paradedb_18_connection(
    paradedb_18_service: PostgresService,
) -> Generator[Connection[Any], None, None]:
    """Provide a deprecated psycopg connection to ParadeDB PG18.

    Yields:
        An open ``psycopg.Connection``.
    """
    with provide_postgres_connection(paradedb_18_service, fixture_name="paradedb_18_connection") as conn:
        yield conn


@pytest.fixture(autouse=False, scope="session")
def alloydb_omni_image() -> str:
    """Return the default AlloyDB Omni container image tag on Google Container Registry."""
    return "gcr.io/alloydb-omni/alloydbomni:18"


@pytest.fixture(autouse=False, scope="session")
def alloydb_omni_port() -> int | None:
    """Return an optional pinned host port for the default AlloyDB Omni service."""
    return _env_port("ALLOYDB_OMNI_PORT")


@pytest.fixture(autouse=False, scope="session")
def alloydb_omni_15_port() -> int | None:
    """Return an optional pinned host port for AlloyDB Omni 15."""
    return _env_port("ALLOYDB_OMNI_15_PORT")


@pytest.fixture(autouse=False, scope="session")
def alloydb_omni_16_port() -> int | None:
    """Return an optional pinned host port for AlloyDB Omni 16."""
    return _env_port("ALLOYDB_OMNI_16_PORT")


@pytest.fixture(autouse=False, scope="session")
def alloydb_omni_17_port() -> int | None:
    """Return an optional pinned host port for AlloyDB Omni 17."""
    return _env_port("ALLOYDB_OMNI_17_PORT")


@pytest.fixture(autouse=False, scope="session")
def alloydb_omni_18_port() -> int | None:
    """Return an optional pinned host port for AlloyDB Omni 18."""
    return _env_port("ALLOYDB_OMNI_18_PORT")


@pytest.fixture(autouse=False, scope="session")
def alloydb_omni_service(
    docker_service: DockerService,
    alloydb_omni_image: str,
    xdist_postgres_isolation_level: XdistIsolationLevel,
    postgres_host: str,
    postgres_user: str,
    postgres_password: str,
    alloydb_omni_port: int | None,
) -> Generator[PostgresService, None, None]:
    """Provide the default AlloyDB Omni service.

    Yields:
        A running :class:`PostgresService` instance.
    """
    with provide_postgres_service(
        docker_service,
        image=alloydb_omni_image,
        name="alloydb-omni",
        xdist_postgres_isolate=xdist_postgres_isolation_level,
        host=postgres_host,
        user=postgres_user,
        password=postgres_password,
        host_port=alloydb_omni_port,
    ) as service:
        yield service


@pytest.fixture(autouse=False, scope="session")
def alloydb_omni_15_service(
    docker_service: DockerService,
    xdist_postgres_isolation_level: XdistIsolationLevel,
    postgres_host: str,
    postgres_user: str,
    postgres_password: str,
    alloydb_omni_15_port: int | None,
) -> Generator[PostgresService, None, None]:
    """Provide an AlloyDB Omni 15 service.

    Yields:
        A running :class:`PostgresService` instance.
    """
    with provide_postgres_service(
        docker_service,
        image="gcr.io/alloydb-omni/alloydbomni:15",
        name="alloydb-omni-15",
        xdist_postgres_isolate=xdist_postgres_isolation_level,
        host=postgres_host,
        user=postgres_user,
        password=postgres_password,
        host_port=alloydb_omni_15_port,
    ) as service:
        yield service


@pytest.fixture(autouse=False, scope="session")
def alloydb_omni_16_service(
    docker_service: DockerService,
    xdist_postgres_isolation_level: XdistIsolationLevel,
    postgres_host: str,
    postgres_user: str,
    postgres_password: str,
    alloydb_omni_16_port: int | None,
) -> Generator[PostgresService, None, None]:
    """Provide an AlloyDB Omni 16 service.

    Yields:
        A running :class:`PostgresService` instance.
    """
    with provide_postgres_service(
        docker_service,
        image="gcr.io/alloydb-omni/alloydbomni:16",
        name="alloydb-omni-16",
        xdist_postgres_isolate=xdist_postgres_isolation_level,
        host=postgres_host,
        user=postgres_user,
        password=postgres_password,
        host_port=alloydb_omni_16_port,
    ) as service:
        yield service


@pytest.fixture(autouse=False, scope="session")
def alloydb_omni_17_service(
    docker_service: DockerService,
    xdist_postgres_isolation_level: XdistIsolationLevel,
    postgres_host: str,
    postgres_user: str,
    postgres_password: str,
    alloydb_omni_17_port: int | None,
) -> Generator[PostgresService, None, None]:
    """Provide an AlloyDB Omni 17 service.

    Yields:
        A running :class:`PostgresService` instance.
    """
    with provide_postgres_service(
        docker_service,
        image="gcr.io/alloydb-omni/alloydbomni:17",
        name="alloydb-omni-17",
        xdist_postgres_isolate=xdist_postgres_isolation_level,
        host=postgres_host,
        user=postgres_user,
        password=postgres_password,
        host_port=alloydb_omni_17_port,
    ) as service:
        yield service


@pytest.fixture(autouse=False, scope="session")
def alloydb_omni_18_service(
    docker_service: DockerService,
    xdist_postgres_isolation_level: XdistIsolationLevel,
    postgres_host: str,
    postgres_user: str,
    postgres_password: str,
    alloydb_omni_18_port: int | None,
) -> Generator[PostgresService, None, None]:
    """Provide an AlloyDB Omni 18 service.

    Yields:
        A running :class:`PostgresService` instance.
    """
    with provide_postgres_service(
        docker_service,
        image="gcr.io/alloydb-omni/alloydbomni:18",
        name="alloydb-omni-18",
        xdist_postgres_isolate=xdist_postgres_isolation_level,
        host=postgres_host,
        user=postgres_user,
        password=postgres_password,
        host_port=alloydb_omni_18_port,
    ) as service:
        yield service


@pytest.fixture(autouse=False, scope="session")
def alloydb_omni_connection(
    alloydb_omni_service: PostgresService,
) -> Generator[Connection[Any], None, None]:
    """Provide a deprecated psycopg connection to the default AlloyDB Omni service.

    Yields:
        An open ``psycopg.Connection``.
    """
    with provide_postgres_connection(alloydb_omni_service, fixture_name="alloydb_omni_connection") as conn:
        yield conn


@pytest.fixture(autouse=False, scope="session")
def alloydb_omni_15_connection(
    alloydb_omni_15_service: PostgresService,
) -> Generator[Connection[Any], None, None]:
    """Provide a deprecated psycopg connection to AlloyDB Omni 15.

    Yields:
        An open ``psycopg.Connection``.
    """
    with provide_postgres_connection(alloydb_omni_15_service, fixture_name="alloydb_omni_15_connection") as conn:
        yield conn


@pytest.fixture(autouse=False, scope="session")
def alloydb_omni_16_connection(
    alloydb_omni_16_service: PostgresService,
) -> Generator[Connection[Any], None, None]:
    """Provide a deprecated psycopg connection to AlloyDB Omni 16.

    Yields:
        An open ``psycopg.Connection``.
    """
    with provide_postgres_connection(alloydb_omni_16_service, fixture_name="alloydb_omni_16_connection") as conn:
        yield conn


@pytest.fixture(autouse=False, scope="session")
def alloydb_omni_17_connection(
    alloydb_omni_17_service: PostgresService,
) -> Generator[Connection[Any], None, None]:
    """Provide a deprecated psycopg connection to AlloyDB Omni 17.

    Yields:
        An open ``psycopg.Connection``.
    """
    with provide_postgres_connection(alloydb_omni_17_service, fixture_name="alloydb_omni_17_connection") as conn:
        yield conn


@pytest.fixture(autouse=False, scope="session")
def alloydb_omni_18_connection(
    alloydb_omni_18_service: PostgresService,
) -> Generator[Connection[Any], None, None]:
    """Provide a deprecated psycopg connection to AlloyDB Omni 18.

    Yields:
        An open ``psycopg.Connection``.
    """
    with provide_postgres_connection(alloydb_omni_18_service, fixture_name="alloydb_omni_18_connection") as conn:
        yield conn


def _env_port(var_name: str) -> int | None:
    """Return an integer port from environment variable ``var_name`` if set."""
    value = os.environ.get(var_name)
    return int(value) if value else None


def _validate_identifier(identifier: str) -> str:
    """Validate that a PostgreSQL database identifier is safe for SQL interpolation."""
    if not IDENTIFIER_PATTERN.match(identifier):
        msg = f"Invalid PostgreSQL database identifier: {identifier!r}"
        raise ValueError(msg)
    return identifier
