"""PostgreSQL, pgvector, ParadeDB, and AlloyDB Omni container service fixtures."""

from __future__ import annotations

import dataclasses
import importlib
import inspect
import os
import shlex
import tempfile
import time
import warnings
from contextlib import contextmanager
from pathlib import Path
from typing import TYPE_CHECKING, Any

import filelock
import pytest

from pytest_databases._service import resolve_postgres_backend
from pytest_databases.embedded._pgwire import run_simple_query
from pytest_databases.helpers import (
    DEFAULT_TEMPLATE_NAME,
    PostgresTemplateSupport,
    compute_fingerprint,
    env_port,
    exec_output_to_bytes,
    get_xdist_worker_num,
    is_fixture_registered,
    make_connection_string,
    read_init_scripts,
    run_container_init_once,
    simple_string_hash,
    split_template_setup,
    tcp_port_open,
    validate_identifier,
)
from pytest_databases.types import PostgresServiceProtocol, PostgresXdistIsolationLevel, ServiceContainer

if TYPE_CHECKING:
    from collections.abc import Callable, Generator, Mapping, Sequence

    from docker.models.containers import Container
    from psycopg import Connection

    from pytest_databases._service import DockerService

__all__ = (
    "ALLOYDB_OMNI_INIT_SQL",
    "ALLOYDB_OMNI_LEGACY_PRELOAD_LIBRARIES",
    "ALLOYDB_OMNI_PRELOAD_LIBRARIES",
    "DEFAULT_ALLOYDB_OMNI_SHM_SIZE",
    "DEFAULT_ALLOYDB_OMNI_STARTUP_TIMEOUT",
    "DEFAULT_POSTGRES_STARTUP_TIMEOUT",
    "PGVECTOR_INIT_SQL",
    "ExternalPostgresService",
    "PostgresService",
    "PostgresServiceProtocol",
    "PostgresTemplateOptions",
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
    "alloydb_omni_command",
    "alloydb_omni_connection",
    "alloydb_omni_image",
    "alloydb_omni_legacy_command",
    "alloydb_omni_port",
    "alloydb_omni_service",
    "alloydb_omni_shm_size",
    "alloydb_omni_startup_timeout",
    "build_alloydb_omni_command",
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
    "postgres_any_service",
    "postgres_connection",
    "postgres_database",
    "postgres_external_host",
    "postgres_external_port",
    "postgres_external_service",
    "postgres_host",
    "postgres_image",
    "postgres_password",
    "postgres_port",
    "postgres_service",
    "postgres_startup_timeout",
    "postgres_template_fingerprint_sources",
    "postgres_template_lock_dir",
    "postgres_template_name",
    "postgres_template_options",
    "postgres_template_setup",
    "postgres_user",
    "provide_default_postgres_session",
    "provide_external_postgres_service",
    "provide_postgres_connection",
    "provide_postgres_service",
    "xdist_postgres_isolation_level",
)

DEFAULT_POSTGRES_STARTUP_TIMEOUT: int = 60
DEFAULT_ALLOYDB_OMNI_STARTUP_TIMEOUT: int = 90
DEFAULT_ALLOYDB_OMNI_SHM_SIZE: str = "512m"

ALLOYDB_OMNI_LEGACY_PRELOAD_LIBRARIES: tuple[str, ...] = (
    "g_stats",
    "google_columnar_engine",
    "google_job_scheduler",
    "google_ml_integration",
    "google_storage",
    "pg_stat_statements",
)
ALLOYDB_OMNI_PRELOAD_LIBRARIES: tuple[str, ...] = (
    *ALLOYDB_OMNI_LEGACY_PRELOAD_LIBRARIES,
    "pg_textsearch",
)


def _idempotent_extension_sql(extension: str, *, cascade: bool = True) -> str:
    """Return a PL/pgSQL block creating ``extension`` while tolerating concurrent ML-agent install races."""
    cascade_clause = " CASCADE" if cascade else ""
    return (
        "DO $$ BEGIN "
        f"CREATE EXTENSION IF NOT EXISTS {extension}{cascade_clause}; "
        "EXCEPTION WHEN duplicate_object OR unique_violation THEN NULL; "
        "END $$;"
    )


ALLOYDB_OMNI_INIT_SQL: tuple[str, ...] = (
    _idempotent_extension_sql("google_columnar_engine"),
    _idempotent_extension_sql("pg_stat_statements"),
    _idempotent_extension_sql("vector"),
    _idempotent_extension_sql("alloydb_scann"),
    _idempotent_extension_sql("google_ml_integration"),
    _idempotent_extension_sql("alloydb_ai_nl"),
    (
        "DO $$ BEGIN "
        "IF EXISTS (SELECT 1 FROM pg_available_extensions WHERE name = 'pg_textsearch') THEN "
        "CREATE EXTENSION IF NOT EXISTS pg_textsearch CASCADE; "
        "END IF; "
        "EXCEPTION WHEN duplicate_object OR unique_violation THEN NULL; "
        "END $$;"
    ),
)
PGVECTOR_INIT_SQL: tuple[str, ...] = (_idempotent_extension_sql("vector", cascade=False),)


def build_alloydb_omni_command(
    *,
    include_textsearch: bool = True,
    extra_gucs: Mapping[str, str] | None = None,
) -> list[str]:
    """Return PostgreSQL postmaster args enabling verified AlloyDB Omni 15-18 columnar, BM25, ScaNN, and AI GUCs."""
    preload = ALLOYDB_OMNI_PRELOAD_LIBRARIES if include_textsearch else ALLOYDB_OMNI_LEGACY_PRELOAD_LIBRARIES
    gucs: dict[str, str] = {
        "shared_preload_libraries": ",".join(preload),
        "pg_stat_statements.track": "all",
        "google_columnar_engine.enabled": "on",
        "google_columnar_engine.memory_size_in_mb": "256",
        "omni_enable_ml_agent_process": "on",
        "google_ml_integration.enable_model_support": "on",
        "google_ml_integration.enable_ai_query_engine": "on",
        "alloydb_ai_nl.enabled": "on",
        "max_connections": "500",
    }
    if extra_gucs:
        gucs.update(extra_gucs)
    command = ["postgres"]
    for key, value in gucs.items():
        command.extend(["-c", f"{key}={value}"])
    return command


@dataclasses.dataclass
class PostgresService(ServiceContainer, PostgresTemplateSupport):
    """Connection metadata and lifecycle helpers for a PostgreSQL-compatible container service.

    Template helpers (:meth:`ensure_template`, :meth:`create_worker_database_from_template`,
    :meth:`sweep_worker_databases`, :meth:`clone_template_database`, :meth:`drop_database_force`) run ``psql``
    inside the container.
    """

    database: str
    password: str
    user: str

    @property
    def dsn(self) -> str:
        """Libpq keyword/value connection string for this service.

        Returns:
            Formatted libpq connection string.
        """
        return make_connection_string(
            host=self.host,
            port=self.port,
            user=self.user,
            password=self.password,
            database=self.database,
        )

    @property
    def connection_config(self) -> dict[str, Any]:
        """Driver keyword arguments (``host``, ``port``, ``user``, ``database``, and optional ``password``).

        Returns:
            Dictionary of connection keyword arguments.
        """
        config: dict[str, Any] = {
            "host": self.host,
            "port": self.port,
            "user": self.user,
            "database": self.database,
        }
        if self.password:
            config["password"] = self.password
        return config

    def exec_sql(
        self,
        sql: str,
        *,
        database: str | None = None,
        tuples_only: bool = False,
        timeout: float = 30.0,
    ) -> tuple[int, bytes]:
        """Execute ``sql`` against ``database`` (defaults to ``self.database``) via in-container ``psql``.

        Returns:
            Tuple of ``(exit_code, output_bytes)``.
        """
        del timeout
        return self._run_sql(database or self.database, sql, tuples_only=tuples_only)

    def _run_sql(self, database: str, sql: str, *, tuples_only: bool = False) -> tuple[int, bytes]:
        """Execute ``sql`` against ``database`` with ``psql`` inside the container.

        Returns:
            The ``psql`` exit code and output.
        """
        return exec_psql(
            self.container,
            user=self.user,
            password=self.password,
            database=database,
            sql=sql,
            tuples_only=tuples_only,
        )


@dataclasses.dataclass
class ExternalPostgresService(PostgresTemplateSupport):
    """Connection metadata and SQL/template helpers for a pre-running PostgreSQL endpoint.

    Queries and template database management run directly over the stdlib PostgreSQL v3 wire
    protocol (`trust`, cleartext, MD5, or `SCRAM-SHA-256`) with zero container runtime or driver dependencies.
    """

    host: str
    port: int
    database: str
    user: str = "postgres"
    password: str = ""

    @property
    def dsn(self) -> str:
        """Libpq keyword/value connection string for this endpoint.

        Returns:
            Formatted libpq connection string.
        """
        return make_connection_string(
            host=self.host,
            port=self.port,
            user=self.user,
            password=self.password,
            database=self.database,
        )

    @property
    def connection_config(self) -> dict[str, Any]:
        """Driver keyword arguments (``host``, ``port``, ``user``, ``database``, and optional ``password``).

        Returns:
            Dictionary of connection keyword arguments.
        """
        config: dict[str, Any] = {
            "host": self.host,
            "port": self.port,
            "user": self.user,
            "database": self.database,
        }
        if self.password:
            config["password"] = self.password
        return config

    def exec_sql(
        self,
        sql: str,
        *,
        database: str | None = None,
        tuples_only: bool = False,
        timeout: float = 30.0,
    ) -> tuple[int, bytes]:
        """Execute ``sql`` against ``database`` (defaults to ``self.database``) over the v3 wire protocol.

        Args:
            sql: SQL statement text to execute.
            database: Optional target database override.
            tuples_only: Accepted for signature parity with :meth:`PostgresService.exec_sql`; wire output is
                always formatted as unaligned tab-separated tuples matching ``psql -tA``.
            timeout: Socket timeout in seconds.

        Returns:
            Tuple of ``(exit_code, output_bytes)`` where ``0`` is success, ``1`` is a SQL error, and ``2``
            is a connection or authentication failure.
        """
        del tuples_only
        return run_simple_query(
            self.host,
            self.port,
            user=self.user,
            database=database or self.database,
            sql=sql,
            password=self.password,
            timeout=timeout,
        )

    def _run_sql(self, database: str, sql: str, *, tuples_only: bool = False) -> tuple[int, bytes]:
        """Execute ``sql`` against ``database`` over the PostgreSQL wire protocol."""
        return self.exec_sql(sql, database=database, tuples_only=tuples_only)


@dataclasses.dataclass(frozen=True)
class PostgresTemplateOptions:
    """Template database settings used when the isolation level is ``"template"``.

    ``name`` is the template name prefix (None means ``"pytest_databases_template"``). ``setup`` is a callable
    receiving the staging PostgreSQL service, or SQL statements / ``.sql`` file paths whose text and contents are
    hashed into the template name. ``fingerprint_sources`` adds strings, bytes, files, or directories to that digest
    (use it to version a setup callable). ``lock_dir`` holds the cross-worker lock file (None means the system temp
    directory) and ``lock_timeout`` is the number of seconds to wait for it.
    """

    name: str | None = None
    setup: (
        Callable[[PostgresService], object]
        | Callable[[ExternalPostgresService], object]
        | str
        | Path
        | Sequence[str | Path]
        | None
    ) = None
    lock_dir: Path | str | None = None
    lock_timeout: float = 180.0
    fingerprint_sources: Sequence[str | bytes | Path] = ()


def exec_psql(
    container: Container,
    *,
    user: str,
    password: str,
    database: str,
    sql: str,
    tuples_only: bool = False,
) -> tuple[int, bytes]:
    """Execute a SQL statement via ``psql`` over the container TCP loopback interface.

    Returns:
        The ``psql`` exit code and output.
    """
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
    """Create and verify a PostgreSQL database inside the container.

    Raises:
        RuntimeError: If ``CREATE DATABASE`` keeps failing or the verification query fails.
    """
    safe_db = validate_identifier(db_name)
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
    """Clone ``source_db`` into ``target_db`` using PostgreSQL ``CREATE DATABASE ... TEMPLATE``.

    Returns:
        The name of the created database.
    """
    return service.clone_template_database(target_db, source_db=source_db)


def drop_database_force(
    service: PostgresService,
    *,
    db_name: str,
) -> None:
    """Terminate active backends and drop ``db_name`` if it exists."""
    service.drop_database_force(db_name)


@pytest.fixture(scope="session")
def xdist_postgres_isolation_level() -> PostgresXdistIsolationLevel:
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
    return os.environ.get("POSTGRES_USER", "postgres")


@pytest.fixture(autouse=False, scope="session")
def postgres_database() -> str:
    """Return the default database name for PostgreSQL services."""
    return os.environ.get("POSTGRES_DATABASE", "pytest_databases")


@pytest.fixture(autouse=False, scope="session")
def postgres_external_host() -> str | None:
    """Return an optional pre-started external PostgreSQL hostname or IP from ``POSTGRES_EXTERNAL_HOST``."""
    value = os.environ.get("POSTGRES_EXTERNAL_HOST", "").strip()
    return value or None


def _make_port_fixture(fixture_name: str, env_var: str, doc: str) -> Any:
    """Create a session-scoped optional host-port fixture backed by ``env_var``."""

    def _fixture() -> int | None:
        return env_port(env_var)

    _fixture.__name__ = fixture_name
    _fixture.__qualname__ = fixture_name
    _fixture.__doc__ = doc
    _fixture.__module__ = __name__
    return pytest.fixture(autouse=False, scope="session")(_fixture)


postgres_external_port = _make_port_fixture(
    "postgres_external_port",
    "POSTGRES_EXTERNAL_PORT",
    "Return an optional port for a pre-started external PostgreSQL service (defaults to 5432).",
)


postgres_port = _make_port_fixture(
    "postgres_port",
    "POSTGRES_PORT",
    "Return an optional pinned host port for the default PostgreSQL container.",
)
postgres_11_port = _make_port_fixture(
    "postgres_11_port",
    "POSTGRES_11_PORT",
    "Return an optional pinned host port for PostgreSQL 11.",
)
postgres_12_port = _make_port_fixture(
    "postgres_12_port",
    "POSTGRES_12_PORT",
    "Return an optional pinned host port for PostgreSQL 12.",
)
postgres_13_port = _make_port_fixture(
    "postgres_13_port",
    "POSTGRES_13_PORT",
    "Return an optional pinned host port for PostgreSQL 13.",
)
postgres_14_port = _make_port_fixture(
    "postgres_14_port",
    "POSTGRES_14_PORT",
    "Return an optional pinned host port for PostgreSQL 14.",
)
postgres_15_port = _make_port_fixture(
    "postgres_15_port",
    "POSTGRES_15_PORT",
    "Return an optional pinned host port for PostgreSQL 15.",
)
postgres_16_port = _make_port_fixture(
    "postgres_16_port",
    "POSTGRES_16_PORT",
    "Return an optional pinned host port for PostgreSQL 16.",
)
postgres_17_port = _make_port_fixture(
    "postgres_17_port",
    "POSTGRES_17_PORT",
    "Return an optional pinned host port for PostgreSQL 17.",
)
postgres_18_port = _make_port_fixture(
    "postgres_18_port",
    "POSTGRES_18_PORT",
    "Return an optional pinned host port for PostgreSQL 18.",
)


@contextmanager
def provide_postgres_service(
    docker_service: DockerService,
    image: str,
    name: str,
    host: str,
    user: str,
    password: str,
    xdist_postgres_isolate: PostgresXdistIsolationLevel,
    host_port: int | None = None,
    timeout: int = 60,
    pause: float = 0.5,
    template: PostgresTemplateOptions | None = None,
    *,
    database: str = "pytest_databases",
    command: str | list[str] | None = None,
    env: Mapping[str, str] | None = None,
    shm_size: int | str | None = None,
    mem_limit: str | None = None,
    volumes: dict[str, dict[str, str]] | list[str] | None = None,
    init_sql: str | Path | Sequence[str | Path] | None = None,
) -> Generator[PostgresService, None, None]:
    """Start and validate a PostgreSQL-compatible container service.

    Readiness runs ``SELECT 1`` through ``psql`` inside the container against ``postgres`` and then opens
    a TCP connection to the published host port. ``POSTGRES_USER`` and ``POSTGRES_DB`` are forwarded into
    the container environment so custom superuser names and database names initialize cleanly across
    official ``postgres``, ``pgvector``, ``paradedb``, and ``alloydbomni`` images.

    With ``xdist_postgres_isolate="template"`` the template described by ``template`` is built once per
    container and the service database (``<database>`` or ``<database>_<worker>``) is cloned from it.
    Any ``init_sql`` statements or ``.sql`` files run deterministically once against the provisioned
    database under a cross-worker file lock.

    Yields:
        A configured :class:`PostgresService` instance.
    """
    if not user:
        msg = "PostgreSQL user must be non-empty."
        raise ValueError(msg)
    base_db = validate_identifier(database)
    resolved_name, db_name = _resolve_postgres_targets(name, base_db, xdist_postgres_isolate)

    def check(_service: ServiceContainer) -> bool:
        exit_code, output = exec_psql(
            _service.container,
            user=user,
            password=password,
            database="postgres",
            sql="SELECT 1",
            tuples_only=True,
        )
        return exit_code == 0 and output.strip() == b"1" and tcp_port_open(_service.host, _service.port)

    with docker_service.run(
        image=image,
        check=check,
        container_host=host,
        container_port=5432,
        name=resolved_name,
        command=command,
        env=_build_postgres_env(user=user, password=password, database=base_db, extra_env=env),
        timeout=timeout,
        pause=pause,
        transient=xdist_postgres_isolate == "server",
        host_port=host_port,
        shm_size=shm_size,
        mem_limit=mem_limit,
        volumes=volumes,
    ) as service:
        _provision_container_database(
            service,
            user=user,
            password=password,
            db_name=db_name,
            isolate=xdist_postgres_isolate,
            template=template,
            init_sql=init_sql,
        )
        if xdist_postgres_isolate != "template":
            _apply_container_init_sql(
                service.container,
                user=user,
                password=password,
                db_name=db_name,
                init_sql=init_sql,
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
def provide_external_postgres_service(
    host: str,
    port: int = 5432,
    *,
    user: str = "postgres",
    password: str = "",
    database: str = "pytest_databases",
    maintenance_database: str = "postgres",
    xdist_postgres_isolate: PostgresXdistIsolationLevel = "database",
    template: PostgresTemplateOptions | None = None,
    init_sql: str | Path | Sequence[str | Path] | None = None,
    lock_dir: Path | str | None = None,
    timeout: float = 60.0,
    pause: float = 0.5,
) -> Generator[ExternalPostgresService, None, None]:
    """Attach to a pre-started external PostgreSQL endpoint with clientless wire readiness and isolation.

    Uses the stdlib PostgreSQL v3 wire client (`trust`, cleartext, MD5, and `SCRAM-SHA-256`) to wait for
    readiness, create or clone per-worker databases, and execute optional ``init_sql`` scripts without
    requiring a container runtime, ``psql``, or ``psycopg``.

    Args:
        host: External PostgreSQL server hostname or IP address.
        port: External PostgreSQL server TCP port.
        user: Role name used for authentication and database setup.
        password: Optional role password (empty string for ``trust`` authentication).
        database: Base database name (suffixed ``_<worker>`` under ``pytest-xdist``).
        maintenance_database: Existing database probed for readiness and ``CREATE DATABASE`` statements.
        xdist_postgres_isolate: ``"database"`` or ``"template"`` (``"server"`` is rejected on fixed endpoints).
        template: Optional template database configuration when ``xdist_postgres_isolate="template"``.
        init_sql: Optional SQL statement, ``.sql`` file path, or sequence of statements/paths applied once.
        lock_dir: Optional directory for cross-worker coordination lock and marker files.
        timeout: Seconds to wait for the external server to accept queries.
        pause: Seconds between readiness probe attempts.

    Yields:
        Configured :class:`ExternalPostgresService` targeting the isolated database.

    Raises:
        ValueError: If ``user`` is empty, ``xdist_postgres_isolate="server"``, or timing values are non-positive.
        TimeoutError: If the external server does not answer ``SELECT 1`` within ``timeout`` seconds.
        RuntimeError: If database creation, template setup, or ``init_sql`` fails.
    """
    if not user:
        msg = "PostgreSQL user must be non-empty."
        raise ValueError(msg)
    if xdist_postgres_isolate == "server":
        msg = (
            "xdist_postgres_isolate='server' is not supported for external PostgreSQL endpoints; "
            "use 'database' or 'template'."
        )
        raise ValueError(msg)
    if timeout <= 0 or pause <= 0:
        msg = "timeout and pause must be strictly greater than zero."
        raise ValueError(msg)

    base_db = validate_identifier(database)
    maint_db = validate_identifier(maintenance_database)
    worker_num = get_xdist_worker_num()
    db_name = validate_identifier(f"{base_db}_{worker_num}") if worker_num is not None else base_db

    _wait_for_external_postgres(
        host,
        port,
        user=user,
        password=password,
        database=maint_db,
        timeout=timeout,
        pause=pause,
    )
    admin = ExternalPostgresService(host=host, port=port, database=maint_db, user=user, password=password)
    _provision_external_database(
        admin,
        db_name=db_name,
        isolate=xdist_postgres_isolate,
        template=template,
        init_sql=init_sql,
        lock_dir=lock_dir,
    )
    target = ExternalPostgresService(host=host, port=port, database=db_name, user=user, password=password)
    if xdist_postgres_isolate != "template":
        _apply_external_init_sql(target, admin=admin, init_sql=init_sql, lock_dir=lock_dir)
    yield target


@pytest.fixture(autouse=False, scope="session")
def postgres_external_service(
    postgres_external_host: str | None,
    postgres_external_port: int | None,
    postgres_user: str,
    postgres_password: str,
    postgres_database: str,
    xdist_postgres_isolation_level: PostgresXdistIsolationLevel,
    postgres_template_options: PostgresTemplateOptions,
    postgres_startup_timeout: int,
) -> Generator[ExternalPostgresService, None, None]:
    """Attach to a pre-started PostgreSQL service configured via ``POSTGRES_EXTERNAL_HOST``.

    Yields:
        Configured :class:`ExternalPostgresService` targeting the isolated database.
    """
    if not postgres_external_host:
        pytest.skip("Set POSTGRES_EXTERNAL_HOST or override postgres_external_host to use postgres_external_service.")
    isolate: PostgresXdistIsolationLevel = (
        "database" if xdist_postgres_isolation_level == "server" else xdist_postgres_isolation_level
    )
    with provide_external_postgres_service(
        postgres_external_host,
        postgres_external_port or 5432,
        user=postgres_user,
        password=postgres_password,
        database=postgres_database,
        xdist_postgres_isolate=isolate,
        template=postgres_template_options,
        timeout=postgres_startup_timeout,
    ) as service:
        yield service


@contextmanager
def provide_postgres_connection(
    service: PostgresService | ExternalPostgresService,
    *,
    fixture_name: str,
) -> Generator[Connection[Any], None, None]:
    """Emit a deprecation warning and yield a ``psycopg.Connection`` for ``service``.

    Yields:
        An open ``psycopg.Connection`` connected to ``service``.
    """
    warnings.warn(
        f"The '{fixture_name}' fixture is deprecated in v0.20.0 and will be removed in v1.0.0. "
        "Use the corresponding '*_service' fixture and construct your own psycopg connection.",
        DeprecationWarning,
        stacklevel=3,
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


@pytest.fixture(scope="session")
def postgres_startup_timeout() -> int:
    """Return startup readiness timeout in seconds for PostgreSQL containers."""
    return int(os.getenv("POSTGRES_STARTUP_TIMEOUT", str(DEFAULT_POSTGRES_STARTUP_TIMEOUT)))


def _make_postgres_service_fixture(
    fixture_name: str,
    *,
    name: str,
    port_fixture: str,
    doc: str,
    image: str | None = None,
    image_fixture: str | None = None,
    timeout_fixture_name: str | None = None,
    command_fixture_name: str | None = None,
    shm_size_fixture_name: str | None = None,
    default_init_sql: str | Path | Sequence[str | Path] | None = None,
) -> Any:
    """Create a session-scoped PostgreSQL family service fixture."""

    def _fixture(**kwargs: Any) -> Generator[PostgresService, None, None]:
        resolved_image = kwargs[image_fixture] if image_fixture is not None else str(image)
        timeout = kwargs[timeout_fixture_name] if timeout_fixture_name is not None else DEFAULT_POSTGRES_STARTUP_TIMEOUT
        command = kwargs[command_fixture_name] if command_fixture_name is not None else None
        shm_size = kwargs[shm_size_fixture_name] if shm_size_fixture_name is not None else None
        with provide_postgres_service(
            kwargs["docker_service"],
            image=resolved_image,
            name=name,
            xdist_postgres_isolate=kwargs["xdist_postgres_isolation_level"],
            host=kwargs["postgres_host"],
            user=kwargs["postgres_user"],
            password=kwargs["postgres_password"],
            host_port=kwargs[port_fixture],
            timeout=timeout,
            template=kwargs["postgres_template_options"],
            database=kwargs["postgres_database"],
            command=command,
            shm_size=shm_size,
            init_sql=default_init_sql,
        ) as service:
            yield service

    param_names = ["docker_service"]
    if image_fixture is not None:
        param_names.append(image_fixture)
    param_names.extend([
        "xdist_postgres_isolation_level",
        "postgres_host",
        "postgres_user",
        "postgres_password",
        "postgres_database",
        port_fixture,
        "postgres_template_options",
    ])
    if timeout_fixture_name is not None:
        param_names.append(timeout_fixture_name)
    if command_fixture_name is not None:
        param_names.append(command_fixture_name)
    if shm_size_fixture_name is not None:
        param_names.append(shm_size_fixture_name)
    _fixture.__signature__ = inspect.Signature([  # type: ignore[attr-defined]
        inspect.Parameter(param, inspect.Parameter.POSITIONAL_OR_KEYWORD) for param in param_names
    ])
    _fixture.__name__ = fixture_name
    _fixture.__qualname__ = fixture_name
    _fixture.__doc__ = doc
    _fixture.__module__ = __name__
    return pytest.fixture(autouse=False, scope="session")(_fixture)


def _make_postgres_connection_fixture(
    fixture_name: str,
    *,
    service_fixture: str,
    doc: str,
) -> Any:
    """Create a session-scoped deprecated psycopg connection fixture."""

    def _fixture(**kwargs: Any) -> Generator[Connection[Any], None, None]:
        with provide_postgres_connection(kwargs[service_fixture], fixture_name=fixture_name) as conn:
            yield conn

    _fixture.__signature__ = inspect.Signature([  # type: ignore[attr-defined]
        inspect.Parameter(service_fixture, inspect.Parameter.POSITIONAL_OR_KEYWORD),
    ])
    _fixture.__name__ = fixture_name
    _fixture.__qualname__ = fixture_name
    _fixture.__doc__ = doc
    _fixture.__module__ = __name__
    return pytest.fixture(autouse=False, scope="session")(_fixture)


postgres_11_service = _make_postgres_service_fixture(
    "postgres_11_service",
    image="postgres:11",
    name="postgres-11",
    port_fixture="postgres_11_port",
    doc="Provide a PostgreSQL 11 service.",
    timeout_fixture_name="postgres_startup_timeout",
)
postgres_12_service = _make_postgres_service_fixture(
    "postgres_12_service",
    image="postgres:12",
    name="postgres-12",
    port_fixture="postgres_12_port",
    doc="Provide a PostgreSQL 12 service.",
    timeout_fixture_name="postgres_startup_timeout",
)
postgres_13_service = _make_postgres_service_fixture(
    "postgres_13_service",
    image="postgres:13",
    name="postgres-13",
    port_fixture="postgres_13_port",
    doc="Provide a PostgreSQL 13 service.",
    timeout_fixture_name="postgres_startup_timeout",
)
postgres_14_service = _make_postgres_service_fixture(
    "postgres_14_service",
    image="postgres:14",
    name="postgres-14",
    port_fixture="postgres_14_port",
    doc="Provide a PostgreSQL 14 service.",
    timeout_fixture_name="postgres_startup_timeout",
)
postgres_15_service = _make_postgres_service_fixture(
    "postgres_15_service",
    image="postgres:15",
    name="postgres-15",
    port_fixture="postgres_15_port",
    doc="Provide a PostgreSQL 15 service.",
    timeout_fixture_name="postgres_startup_timeout",
)
postgres_16_service = _make_postgres_service_fixture(
    "postgres_16_service",
    image="postgres:16",
    name="postgres-16",
    port_fixture="postgres_16_port",
    doc="Provide a PostgreSQL 16 service.",
    timeout_fixture_name="postgres_startup_timeout",
)
postgres_17_service = _make_postgres_service_fixture(
    "postgres_17_service",
    image="postgres:17",
    name="postgres-17",
    port_fixture="postgres_17_port",
    doc="Provide a PostgreSQL 17 service.",
    timeout_fixture_name="postgres_startup_timeout",
)
postgres_18_service = _make_postgres_service_fixture(
    "postgres_18_service",
    image="postgres:18",
    name="postgres-18",
    port_fixture="postgres_18_port",
    doc="Provide a PostgreSQL 18 service.",
    timeout_fixture_name="postgres_startup_timeout",
)

postgres_11_connection = _make_postgres_connection_fixture(
    "postgres_11_connection",
    service_fixture="postgres_11_service",
    doc="Provide a deprecated psycopg connection to PostgreSQL 11.",
)
postgres_12_connection = _make_postgres_connection_fixture(
    "postgres_12_connection",
    service_fixture="postgres_12_service",
    doc="Provide a deprecated psycopg connection to PostgreSQL 12.",
)
postgres_13_connection = _make_postgres_connection_fixture(
    "postgres_13_connection",
    service_fixture="postgres_13_service",
    doc="Provide a deprecated psycopg connection to PostgreSQL 13.",
)
postgres_14_connection = _make_postgres_connection_fixture(
    "postgres_14_connection",
    service_fixture="postgres_14_service",
    doc="Provide a deprecated psycopg connection to PostgreSQL 14.",
)
postgres_15_connection = _make_postgres_connection_fixture(
    "postgres_15_connection",
    service_fixture="postgres_15_service",
    doc="Provide a deprecated psycopg connection to PostgreSQL 15.",
)
postgres_16_connection = _make_postgres_connection_fixture(
    "postgres_16_connection",
    service_fixture="postgres_16_service",
    doc="Provide a deprecated psycopg connection to PostgreSQL 16.",
)
postgres_17_connection = _make_postgres_connection_fixture(
    "postgres_17_connection",
    service_fixture="postgres_17_service",
    doc="Provide a deprecated psycopg connection to PostgreSQL 17.",
)
postgres_18_connection = _make_postgres_connection_fixture(
    "postgres_18_connection",
    service_fixture="postgres_18_service",
    doc="Provide a deprecated psycopg connection to PostgreSQL 18.",
)


@pytest.fixture(autouse=False, scope="session")
def postgres_image() -> str:
    """Return the default PostgreSQL container image tag."""
    return "postgres:18"


@pytest.fixture(autouse=False, scope="session")
def postgres_template_name() -> str | None:
    """Return the template name prefix for ``"template"`` isolation (None means ``"pytest_databases_template"``)."""
    return None


@pytest.fixture(autouse=False, scope="session")
def postgres_template_setup() -> Callable[[PostgresService], object] | str | Path | Sequence[str | Path] | None:
    """Return the template setup: a callable receiving the staging service, or SQL statements / ``.sql`` paths."""
    return None


@pytest.fixture(autouse=False, scope="session")
def postgres_template_lock_dir() -> Path | str | None:
    """Return the directory for template lock files (None means the system temp directory)."""
    return None


@pytest.fixture(autouse=False, scope="session")
def postgres_template_fingerprint_sources() -> Sequence[str | bytes | Path]:
    """Return extra strings, bytes, files, or directories folded into the template name digest."""
    return ()


@pytest.fixture(autouse=False, scope="session")
def postgres_template_options(
    postgres_template_name: str | None,
    postgres_template_setup: Callable[[PostgresService], object] | str | Path | Sequence[str | Path] | None,
    postgres_template_lock_dir: Path | str | None,
    postgres_template_fingerprint_sources: Sequence[str | bytes | Path],
) -> PostgresTemplateOptions:
    """Combine the ``postgres_template_*`` fixtures; every PostgreSQL family service uses it."""
    return PostgresTemplateOptions(
        name=postgres_template_name,
        setup=postgres_template_setup,
        lock_dir=postgres_template_lock_dir,
        fingerprint_sources=postgres_template_fingerprint_sources,
    )


postgres_service = _make_postgres_service_fixture(
    "postgres_service",
    image_fixture="postgres_image",
    name="postgres",
    port_fixture="postgres_port",
    doc="Provide the default PostgreSQL service.",
    timeout_fixture_name="postgres_startup_timeout",
)
postgres_connection = _make_postgres_connection_fixture(
    "postgres_connection",
    service_fixture="postgres_service",
    doc="Provide a deprecated psycopg connection to the default PostgreSQL service.",
)


@pytest.fixture(autouse=False, scope="session")
def pgvector_image() -> str:
    """Return the default pgvector container image tag."""
    return "pgvector/pgvector:pg18"


pgvector_port = _make_port_fixture(
    "pgvector_port",
    "PGVECTOR_PORT",
    "Return an optional pinned host port for the default pgvector service.",
)
pgvector_13_port = _make_port_fixture(
    "pgvector_13_port",
    "PGVECTOR_13_PORT",
    "Return an optional pinned host port for pgvector PG13.",
)
pgvector_14_port = _make_port_fixture(
    "pgvector_14_port",
    "PGVECTOR_14_PORT",
    "Return an optional pinned host port for pgvector PG14.",
)
pgvector_15_port = _make_port_fixture(
    "pgvector_15_port",
    "PGVECTOR_15_PORT",
    "Return an optional pinned host port for pgvector PG15.",
)
pgvector_16_port = _make_port_fixture(
    "pgvector_16_port",
    "PGVECTOR_16_PORT",
    "Return an optional pinned host port for pgvector PG16.",
)
pgvector_17_port = _make_port_fixture(
    "pgvector_17_port",
    "PGVECTOR_17_PORT",
    "Return an optional pinned host port for pgvector PG17.",
)
pgvector_18_port = _make_port_fixture(
    "pgvector_18_port",
    "PGVECTOR_18_PORT",
    "Return an optional pinned host port for pgvector PG18.",
)

pgvector_service = _make_postgres_service_fixture(
    "pgvector_service",
    image_fixture="pgvector_image",
    name="pgvector",
    port_fixture="pgvector_port",
    doc="Provide the default pgvector service.",
    timeout_fixture_name="postgres_startup_timeout",
    default_init_sql=PGVECTOR_INIT_SQL,
)
pgvector_13_service = _make_postgres_service_fixture(
    "pgvector_13_service",
    image="pgvector/pgvector:pg13",
    name="pgvector-13",
    port_fixture="pgvector_13_port",
    doc="Provide a pgvector PG13 service.",
    timeout_fixture_name="postgres_startup_timeout",
    default_init_sql=PGVECTOR_INIT_SQL,
)
pgvector_14_service = _make_postgres_service_fixture(
    "pgvector_14_service",
    image="pgvector/pgvector:pg14",
    name="pgvector-14",
    port_fixture="pgvector_14_port",
    doc="Provide a pgvector PG14 service.",
    timeout_fixture_name="postgres_startup_timeout",
    default_init_sql=PGVECTOR_INIT_SQL,
)
pgvector_15_service = _make_postgres_service_fixture(
    "pgvector_15_service",
    image="pgvector/pgvector:pg15",
    name="pgvector-15",
    port_fixture="pgvector_15_port",
    doc="Provide a pgvector PG15 service.",
    timeout_fixture_name="postgres_startup_timeout",
    default_init_sql=PGVECTOR_INIT_SQL,
)
pgvector_16_service = _make_postgres_service_fixture(
    "pgvector_16_service",
    image="pgvector/pgvector:pg16",
    name="pgvector-16",
    port_fixture="pgvector_16_port",
    doc="Provide a pgvector PG16 service.",
    timeout_fixture_name="postgres_startup_timeout",
    default_init_sql=PGVECTOR_INIT_SQL,
)
pgvector_17_service = _make_postgres_service_fixture(
    "pgvector_17_service",
    image="pgvector/pgvector:pg17",
    name="pgvector-17",
    port_fixture="pgvector_17_port",
    doc="Provide a pgvector PG17 service.",
    timeout_fixture_name="postgres_startup_timeout",
    default_init_sql=PGVECTOR_INIT_SQL,
)
pgvector_18_service = _make_postgres_service_fixture(
    "pgvector_18_service",
    image="pgvector/pgvector:pg18",
    name="pgvector-18",
    port_fixture="pgvector_18_port",
    doc="Provide a pgvector PG18 service.",
    timeout_fixture_name="postgres_startup_timeout",
    default_init_sql=PGVECTOR_INIT_SQL,
)

pgvector_connection = _make_postgres_connection_fixture(
    "pgvector_connection",
    service_fixture="pgvector_service",
    doc="Provide a deprecated psycopg connection to the default pgvector service.",
)
pgvector_13_connection = _make_postgres_connection_fixture(
    "pgvector_13_connection",
    service_fixture="pgvector_13_service",
    doc="Provide a deprecated psycopg connection to pgvector PG13.",
)
pgvector_14_connection = _make_postgres_connection_fixture(
    "pgvector_14_connection",
    service_fixture="pgvector_14_service",
    doc="Provide a deprecated psycopg connection to pgvector PG14.",
)
pgvector_15_connection = _make_postgres_connection_fixture(
    "pgvector_15_connection",
    service_fixture="pgvector_15_service",
    doc="Provide a deprecated psycopg connection to pgvector PG15.",
)
pgvector_16_connection = _make_postgres_connection_fixture(
    "pgvector_16_connection",
    service_fixture="pgvector_16_service",
    doc="Provide a deprecated psycopg connection to pgvector PG16.",
)
pgvector_17_connection = _make_postgres_connection_fixture(
    "pgvector_17_connection",
    service_fixture="pgvector_17_service",
    doc="Provide a deprecated psycopg connection to pgvector PG17.",
)
pgvector_18_connection = _make_postgres_connection_fixture(
    "pgvector_18_connection",
    service_fixture="pgvector_18_service",
    doc="Provide a deprecated psycopg connection to pgvector PG18.",
)


@pytest.fixture(autouse=False, scope="session")
def paradedb_image() -> str:
    """Return the default ParadeDB container image tag."""
    return "paradedb/paradedb:latest-pg18"


paradedb_port = _make_port_fixture(
    "paradedb_port",
    "PARADEDB_PORT",
    "Return an optional pinned host port for the default ParadeDB service.",
)
paradedb_15_port = _make_port_fixture(
    "paradedb_15_port",
    "PARADEDB_15_PORT",
    "Return an optional pinned host port for ParadeDB PG15.",
)
paradedb_16_port = _make_port_fixture(
    "paradedb_16_port",
    "PARADEDB_16_PORT",
    "Return an optional pinned host port for ParadeDB PG16.",
)
paradedb_17_port = _make_port_fixture(
    "paradedb_17_port",
    "PARADEDB_17_PORT",
    "Return an optional pinned host port for ParadeDB PG17.",
)
paradedb_18_port = _make_port_fixture(
    "paradedb_18_port",
    "PARADEDB_18_PORT",
    "Return an optional pinned host port for ParadeDB PG18.",
)

paradedb_service = _make_postgres_service_fixture(
    "paradedb_service",
    image_fixture="paradedb_image",
    name="paradedb",
    port_fixture="paradedb_port",
    doc="Provide the default ParadeDB service.",
    timeout_fixture_name="postgres_startup_timeout",
)
paradedb_15_service = _make_postgres_service_fixture(
    "paradedb_15_service",
    image="paradedb/paradedb:latest-pg15",
    name="paradedb-15",
    port_fixture="paradedb_15_port",
    doc="Provide a ParadeDB PG15 service.",
    timeout_fixture_name="postgres_startup_timeout",
)
paradedb_16_service = _make_postgres_service_fixture(
    "paradedb_16_service",
    image="paradedb/paradedb:latest-pg16",
    name="paradedb-16",
    port_fixture="paradedb_16_port",
    doc="Provide a ParadeDB PG16 service.",
    timeout_fixture_name="postgres_startup_timeout",
)
paradedb_17_service = _make_postgres_service_fixture(
    "paradedb_17_service",
    image="paradedb/paradedb:latest-pg17",
    name="paradedb-17",
    port_fixture="paradedb_17_port",
    doc="Provide a ParadeDB PG17 service.",
    timeout_fixture_name="postgres_startup_timeout",
)
paradedb_18_service = _make_postgres_service_fixture(
    "paradedb_18_service",
    image="paradedb/paradedb:latest-pg18",
    name="paradedb-18",
    port_fixture="paradedb_18_port",
    doc="Provide a ParadeDB PG18 service.",
    timeout_fixture_name="postgres_startup_timeout",
)

paradedb_connection = _make_postgres_connection_fixture(
    "paradedb_connection",
    service_fixture="paradedb_service",
    doc="Provide a deprecated psycopg connection to the default ParadeDB service.",
)
paradedb_15_connection = _make_postgres_connection_fixture(
    "paradedb_15_connection",
    service_fixture="paradedb_15_service",
    doc="Provide a deprecated psycopg connection to ParadeDB PG15.",
)
paradedb_16_connection = _make_postgres_connection_fixture(
    "paradedb_16_connection",
    service_fixture="paradedb_16_service",
    doc="Provide a deprecated psycopg connection to ParadeDB PG16.",
)
paradedb_17_connection = _make_postgres_connection_fixture(
    "paradedb_17_connection",
    service_fixture="paradedb_17_service",
    doc="Provide a deprecated psycopg connection to ParadeDB PG17.",
)
paradedb_18_connection = _make_postgres_connection_fixture(
    "paradedb_18_connection",
    service_fixture="paradedb_18_service",
    doc="Provide a deprecated psycopg connection to ParadeDB PG18.",
)


@pytest.fixture(autouse=False, scope="session")
def alloydb_omni_image() -> str:
    """Return the default AlloyDB Omni container image tag on Google Container Registry."""
    return "gcr.io/alloydb-omni/alloydbomni:18"


alloydb_omni_port = _make_port_fixture(
    "alloydb_omni_port",
    "ALLOYDB_OMNI_PORT",
    "Return an optional pinned host port for the default AlloyDB Omni service.",
)
alloydb_omni_15_port = _make_port_fixture(
    "alloydb_omni_15_port",
    "ALLOYDB_OMNI_15_PORT",
    "Return an optional pinned host port for AlloyDB Omni 15.",
)
alloydb_omni_16_port = _make_port_fixture(
    "alloydb_omni_16_port",
    "ALLOYDB_OMNI_16_PORT",
    "Return an optional pinned host port for AlloyDB Omni 16.",
)
alloydb_omni_17_port = _make_port_fixture(
    "alloydb_omni_17_port",
    "ALLOYDB_OMNI_17_PORT",
    "Return an optional pinned host port for AlloyDB Omni 17.",
)
alloydb_omni_18_port = _make_port_fixture(
    "alloydb_omni_18_port",
    "ALLOYDB_OMNI_18_PORT",
    "Return an optional pinned host port for AlloyDB Omni 18.",
)


@pytest.fixture(scope="session")
def alloydb_omni_startup_timeout() -> int:
    """Return startup readiness timeout in seconds for AlloyDB Omni containers."""
    return int(os.getenv("ALLOYDB_OMNI_STARTUP_TIMEOUT", str(DEFAULT_ALLOYDB_OMNI_STARTUP_TIMEOUT)))


@pytest.fixture(scope="session")
def alloydb_omni_shm_size() -> str | None:
    """Return shared-memory size for AlloyDB Omni containers."""
    return os.getenv("ALLOYDB_OMNI_SHM_SIZE", DEFAULT_ALLOYDB_OMNI_SHM_SIZE) or None


@pytest.fixture(scope="session")
def alloydb_omni_command(alloydb_omni_image: str) -> list[str] | str | None:
    """Return postmaster command for ``alloydb_omni_service``, omitting ``pg_textsearch`` for 15/16 tags."""
    override = os.getenv("ALLOYDB_OMNI_COMMAND")
    if override is not None:
        return shlex.split(override) or None
    return build_alloydb_omni_command(include_textsearch=not _is_legacy_alloydb_omni_image(alloydb_omni_image))


@pytest.fixture(scope="session")
def alloydb_omni_legacy_command() -> list[str] | str | None:
    """Return postmaster command for AlloyDB Omni 15 and 16 containers without ``pg_textsearch``."""
    override = os.getenv("ALLOYDB_OMNI_LEGACY_COMMAND")
    if override is None:
        override = os.getenv("ALLOYDB_OMNI_COMMAND")
    if override is not None:
        return shlex.split(override) or None
    return build_alloydb_omni_command(include_textsearch=False)


alloydb_omni_service = _make_postgres_service_fixture(
    "alloydb_omni_service",
    image_fixture="alloydb_omni_image",
    name="alloydb-omni",
    port_fixture="alloydb_omni_port",
    doc="Provide the default AlloyDB Omni service.",
    timeout_fixture_name="alloydb_omni_startup_timeout",
    command_fixture_name="alloydb_omni_command",
    shm_size_fixture_name="alloydb_omni_shm_size",
    default_init_sql=ALLOYDB_OMNI_INIT_SQL,
)
alloydb_omni_15_service = _make_postgres_service_fixture(
    "alloydb_omni_15_service",
    image="gcr.io/alloydb-omni/alloydbomni:15",
    name="alloydb-omni-15",
    port_fixture="alloydb_omni_15_port",
    doc="Provide an AlloyDB Omni 15 service.",
    timeout_fixture_name="alloydb_omni_startup_timeout",
    command_fixture_name="alloydb_omni_legacy_command",
    shm_size_fixture_name="alloydb_omni_shm_size",
    default_init_sql=ALLOYDB_OMNI_INIT_SQL,
)
alloydb_omni_16_service = _make_postgres_service_fixture(
    "alloydb_omni_16_service",
    image="gcr.io/alloydb-omni/alloydbomni:16",
    name="alloydb-omni-16",
    port_fixture="alloydb_omni_16_port",
    doc="Provide an AlloyDB Omni 16 service.",
    timeout_fixture_name="alloydb_omni_startup_timeout",
    command_fixture_name="alloydb_omni_legacy_command",
    shm_size_fixture_name="alloydb_omni_shm_size",
    default_init_sql=ALLOYDB_OMNI_INIT_SQL,
)
alloydb_omni_17_service = _make_postgres_service_fixture(
    "alloydb_omni_17_service",
    image="gcr.io/alloydb-omni/alloydbomni:17",
    name="alloydb-omni-17",
    port_fixture="alloydb_omni_17_port",
    doc="Provide an AlloyDB Omni 17 service.",
    timeout_fixture_name="alloydb_omni_startup_timeout",
    command_fixture_name="alloydb_omni_command",
    shm_size_fixture_name="alloydb_omni_shm_size",
    default_init_sql=ALLOYDB_OMNI_INIT_SQL,
)
alloydb_omni_18_service = _make_postgres_service_fixture(
    "alloydb_omni_18_service",
    image="gcr.io/alloydb-omni/alloydbomni:18",
    name="alloydb-omni-18",
    port_fixture="alloydb_omni_18_port",
    doc="Provide an AlloyDB Omni 18 service.",
    timeout_fixture_name="alloydb_omni_startup_timeout",
    command_fixture_name="alloydb_omni_command",
    shm_size_fixture_name="alloydb_omni_shm_size",
    default_init_sql=ALLOYDB_OMNI_INIT_SQL,
)

alloydb_omni_connection = _make_postgres_connection_fixture(
    "alloydb_omni_connection",
    service_fixture="alloydb_omni_service",
    doc="Provide a deprecated psycopg connection to the default AlloyDB Omni service.",
)
alloydb_omni_15_connection = _make_postgres_connection_fixture(
    "alloydb_omni_15_connection",
    service_fixture="alloydb_omni_15_service",
    doc="Provide a deprecated psycopg connection to AlloyDB Omni 15.",
)
alloydb_omni_16_connection = _make_postgres_connection_fixture(
    "alloydb_omni_16_connection",
    service_fixture="alloydb_omni_16_service",
    doc="Provide a deprecated psycopg connection to AlloyDB Omni 16.",
)
alloydb_omni_17_connection = _make_postgres_connection_fixture(
    "alloydb_omni_17_connection",
    service_fixture="alloydb_omni_17_service",
    doc="Provide a deprecated psycopg connection to AlloyDB Omni 17.",
)
alloydb_omni_18_connection = _make_postgres_connection_fixture(
    "alloydb_omni_18_connection",
    service_fixture="alloydb_omni_18_service",
    doc="Provide a deprecated psycopg connection to AlloyDB Omni 18.",
)


def _is_legacy_alloydb_omni_image(image: str) -> bool:
    """Return whether ``image`` names an AlloyDB Omni 15 or 16 tag lacking ``pg_textsearch``."""
    without_digest = image.split("@", 1)[0]
    last_segment = without_digest.rsplit("/", 1)[-1]
    if ":" not in last_segment:
        return False
    tag = last_segment.split(":", 1)[1]
    return tag in {"15", "16"} or tag.startswith(("15.", "15-", "16.", "16-"))


def _first_registered_fixture(
    request: pytest.FixtureRequest,
    *names: str,
    default: Any = None,
) -> Any:
    """Return the value of the first fixture in ``names`` registered in ``request``, else ``default``."""
    for name in names:
        if is_fixture_registered(request, name):
            return request.getfixturevalue(name)
    return default


def _resolve_optional_postgres_template(request: pytest.FixtureRequest) -> PostgresTemplateOptions | None:
    """Build ``PostgresTemplateOptions`` when user template fixtures are registered in the active session."""
    if is_fixture_registered(request, "postgres_template_options"):
        return request.getfixturevalue("postgres_template_options")
    has_override = any(
        is_fixture_registered(request, fixture_name)
        for fixture_name in (
            "postgres_template_setup",
            "postgres_template_name",
            "postgres_template_fingerprint_sources",
            "postgres_template_lock_dir",
            "embedded_postgres_template_setup",
            "embedded_postgres_template_name",
            "embedded_postgres_template_fingerprint_sources",
            "embedded_postgres_template_lock_dir",
        )
    )
    if not has_override:
        return None
    name = _first_registered_fixture(request, "postgres_template_name", "embedded_postgres_template_name")
    setup = _first_registered_fixture(request, "postgres_template_setup", "embedded_postgres_template_setup")
    fingerprint_sources = _first_registered_fixture(
        request,
        "postgres_template_fingerprint_sources",
        "embedded_postgres_template_fingerprint_sources",
        default=(),
    )
    lock_dir = _first_registered_fixture(request, "postgres_template_lock_dir", "embedded_postgres_template_lock_dir")
    return PostgresTemplateOptions(
        name=name,
        setup=setup,
        lock_dir=lock_dir,
        fingerprint_sources=fingerprint_sources,
    )


@contextmanager
def provide_default_postgres_session(
    request: pytest.FixtureRequest,
) -> Generator[PostgresService | ExternalPostgresService, None, None]:
    """Yield ``postgres_service`` if registered, or provision a Docker/external PostgreSQL session fallback.

    Yields:
        Active :class:`PostgresService` or :class:`ExternalPostgresService`.
    """
    if is_fixture_registered(request, "postgres_service"):
        yield request.getfixturevalue("postgres_service")
        return

    external_host = (
        request.getfixturevalue("postgres_external_host")
        if is_fixture_registered(request, "postgres_external_host")
        else os.environ.get("POSTGRES_EXTERNAL_HOST", "").strip() or None
    )
    isolate: PostgresXdistIsolationLevel = (
        request.getfixturevalue("xdist_postgres_isolation_level")
        if is_fixture_registered(request, "xdist_postgres_isolation_level")
        else "database"
    )
    user = (
        request.getfixturevalue("postgres_user")
        if is_fixture_registered(request, "postgres_user")
        else os.environ.get("POSTGRES_USER", "postgres")
    )
    password = (
        request.getfixturevalue("postgres_password")
        if is_fixture_registered(request, "postgres_password")
        else "super-secret"
    )
    database = (
        request.getfixturevalue("postgres_database")
        if is_fixture_registered(request, "postgres_database")
        else os.environ.get("POSTGRES_DATABASE", "pytest_databases")
    )
    timeout = (
        request.getfixturevalue("postgres_startup_timeout")
        if is_fixture_registered(request, "postgres_startup_timeout")
        else int(os.environ.get("POSTGRES_STARTUP_TIMEOUT", str(DEFAULT_POSTGRES_STARTUP_TIMEOUT)))
    )
    template = _resolve_optional_postgres_template(request)

    if external_host:
        external_port = (
            request.getfixturevalue("postgres_external_port")
            if is_fixture_registered(request, "postgres_external_port")
            else env_port("POSTGRES_EXTERNAL_PORT")
        )
        ext_isolate: PostgresXdistIsolationLevel = "database" if isolate == "server" else isolate
        with provide_external_postgres_service(
            host=external_host,
            port=external_port or 5432,
            user=user,
            password=password,
            database=database,
            xdist_postgres_isolate=ext_isolate,
            timeout=timeout,
            template=template,
        ) as ext_service:
            yield ext_service
        return

    host = (
        request.getfixturevalue("postgres_host")
        if is_fixture_registered(request, "postgres_host")
        else os.environ.get("POSTGRES_HOST", "127.0.0.1")
    )
    host_port = (
        request.getfixturevalue("postgres_port")
        if is_fixture_registered(request, "postgres_port")
        else env_port("POSTGRES_PORT")
    )
    image = (
        request.getfixturevalue("postgres_image") if is_fixture_registered(request, "postgres_image") else "postgres:18"
    )
    docker_service = request.getfixturevalue("docker_service")
    with provide_postgres_service(
        docker_service,
        image=image,
        name="postgres",
        host=host,
        user=user,
        password=password,
        xdist_postgres_isolate=isolate,
        host_port=host_port,
        timeout=timeout,
        template=template,
        database=database,
    ) as docker_pg_service:
        yield docker_pg_service


@pytest.fixture(autouse=False, scope="session")
def postgres_any_service(
    request: pytest.FixtureRequest,
    tmp_path_factory: pytest.TempPathFactory,
) -> Generator[PostgresServiceProtocol, None, None]:
    """Provide a session-scoped Docker or embedded PostgreSQL service selected via ``--postgres-backend``.

    Yields:
        Active PostgreSQL service conforming to :class:`~pytest_databases.types.PostgresServiceProtocol`.
    """
    backend = resolve_postgres_backend(request.config)
    if backend == "embedded":
        embedded_pg_module = importlib.import_module("pytest_databases.embedded.postgres")
        with embedded_pg_module.provide_default_embedded_postgres_session(request, tmp_path_factory) as service:
            yield service
        return
    with provide_default_postgres_session(request) as service:
        yield service


def _resolve_postgres_targets(
    name: str,
    base_db: str,
    isolate: PostgresXdistIsolationLevel,
) -> tuple[str, str]:
    """Resolve the container logical name and isolated database name for the active xdist worker."""
    worker_num = get_xdist_worker_num()
    if worker_num is None:
        return name, base_db
    suffix = f"_{worker_num}"
    if isolate == "server":
        return f"{name}{suffix}", base_db
    return name, validate_identifier(f"{base_db}{suffix}")


def _build_postgres_env(
    *,
    user: str,
    password: str,
    database: str,
    extra_env: Mapping[str, str] | None,
) -> dict[str, str]:
    """Compose container environment variables for PostgreSQL-compatible images."""
    container_env: dict[str, str] = {
        "POSTGRES_USER": user,
        "POSTGRES_DB": database,
    }
    trust_auth = bool(extra_env and extra_env.get("POSTGRES_HOST_AUTH_METHOD") == "trust")
    if password or not trust_auth:
        container_env["POSTGRES_PASSWORD"] = password
    if extra_env:
        container_env.update(extra_env)
    return container_env


def _provision_container_database(
    service: ServiceContainer,
    *,
    user: str,
    password: str,
    db_name: str,
    isolate: PostgresXdistIsolationLevel,
    template: PostgresTemplateOptions | None,
    init_sql: str | Path | Sequence[str | Path] | None = None,
) -> None:
    """Create or clone ``db_name`` inside a started PostgreSQL container."""
    if isolate != "template":
        create_worker_database(service.container, user=user, password=password, db_name=db_name)
        return
    options = template or PostgresTemplateOptions()
    setup_fn, setup_sql = split_template_setup(options.setup)
    admin = PostgresService(
        host=service.host,
        port=service.port,
        container=service.container,
        database="postgres",
        user=user,
        password=password,
    )
    template_name = admin.ensure_template(
        options.name or DEFAULT_TEMPLATE_NAME,
        setup_fn=setup_fn,
        setup_sql=setup_sql,
        init_sql=init_sql,
        fingerprint_sources=options.fingerprint_sources,
        lock_dir=options.lock_dir,
        lock_timeout=options.lock_timeout,
    )
    admin.create_worker_database_from_template(template_name, db_name)


def _apply_container_init_sql(
    container: Container,
    *,
    user: str,
    password: str,
    db_name: str,
    init_sql: str | Path | Sequence[str | Path] | None,
) -> None:
    """Execute ``init_sql`` statements once per ``(container, db_name)`` via ``psql``."""
    statements = read_init_scripts(init_sql)
    if not statements:
        return
    fingerprint = compute_fingerprint(*(stmt.encode("utf-8") for stmt in statements))

    def _run() -> None:
        for statement in statements:
            exit_code, output = exec_psql(
                container,
                user=user,
                password=password,
                database=db_name,
                sql=statement,
            )
            if exit_code != 0:
                detail = output.decode(errors="replace").strip()
                msg = f"PostgreSQL init_sql failed on database {db_name!r} (exit {exit_code}): {detail}"
                raise RuntimeError(msg)

    run_container_init_once(container, f"postgres:{db_name}", fingerprint, _run)


def _wait_for_external_postgres(
    host: str,
    port: int,
    *,
    user: str,
    password: str,
    database: str,
    timeout: float,
    pause: float,
) -> None:
    """Poll an external PostgreSQL endpoint over the v3 wire protocol until ``SELECT 1`` succeeds."""
    deadline = time.monotonic() + timeout
    last_detail = "endpoint did not accept TCP connections"
    while True:
        if tcp_port_open(host, port, timeout=min(2.0, timeout)):
            exit_code, output = run_simple_query(
                host,
                port,
                user=user,
                database=database,
                sql="SELECT 1",
                password=password,
                timeout=min(5.0, timeout),
            )
            if exit_code == 0 and output.strip() == b"1":
                return
            last_detail = output.decode(errors="replace").strip() or f"exit code {exit_code}"
        if time.monotonic() >= deadline:
            msg = f"External PostgreSQL endpoint {host}:{port} was not ready within {timeout}s: {last_detail}"
            raise TimeoutError(msg)
        time.sleep(pause)


def _provision_external_database(
    admin: ExternalPostgresService,
    *,
    db_name: str,
    isolate: PostgresXdistIsolationLevel,
    template: PostgresTemplateOptions | None,
    lock_dir: Path | str | None,
    init_sql: str | Path | Sequence[str | Path] | None = None,
) -> None:
    """Create or template-clone ``db_name`` on an external PostgreSQL endpoint."""
    if isolate == "template":
        options = template or PostgresTemplateOptions()
        setup_fn, setup_sql = split_template_setup(options.setup)
        template_name = admin.ensure_template(
            options.name or DEFAULT_TEMPLATE_NAME,
            setup_fn=setup_fn,
            setup_sql=setup_sql,
            init_sql=init_sql,
            fingerprint_sources=options.fingerprint_sources,
            lock_dir=options.lock_dir or lock_dir,
            lock_timeout=options.lock_timeout,
        )
        admin.create_worker_database_from_template(template_name, db_name)
        return

    base_dir = Path(lock_dir) if lock_dir is not None else Path(tempfile.gettempdir())
    base_dir.mkdir(parents=True, exist_ok=True)
    lock_key = simple_string_hash(f"extpg:{admin.host}:{admin.port}:{db_name}")
    lock_path = base_dir / f"pytest-databases-extpg-{lock_key}.lock"
    with filelock.FileLock(str(lock_path), timeout=120.0):
        exists_code, exists_out = admin.exec_sql(f"SELECT 1 FROM pg_database WHERE datname = '{db_name}';")
        if exists_code != 0 or exists_out.strip() != b"1":
            create_code, create_out = admin.exec_sql(f'CREATE DATABASE "{db_name}";')
            if create_code != 0 and b"already exists" not in create_out:
                detail = create_out.decode(errors="replace").strip()
                msg = f"External PostgreSQL CREATE DATABASE {db_name!r} failed: {detail}"
                raise RuntimeError(msg)
    verify_code, verify_out = admin.exec_sql("SELECT 1", database=db_name)
    if verify_code != 0 or verify_out.strip() != b"1":
        detail = verify_out.decode(errors="replace").strip()
        msg = f"Verification SELECT against external database {db_name!r} failed: {detail}"
        raise RuntimeError(msg)


def _apply_external_init_sql(
    target: ExternalPostgresService,
    *,
    admin: ExternalPostgresService,
    init_sql: str | Path | Sequence[str | Path] | None,
    lock_dir: Path | str | None,
) -> None:
    """Execute ``init_sql`` once per ``(cluster_identity, database, digest)`` on an external endpoint."""
    statements = read_init_scripts(init_sql)
    if not statements:
        return
    fingerprint = compute_fingerprint(*(stmt.encode("utf-8") for stmt in statements))
    sys_code, sys_out = admin.exec_sql("SELECT system_identifier FROM pg_control_system();")
    sys_id = sys_out.decode(errors="replace").strip() if sys_code == 0 else ""

    def _run() -> None:
        for statement in statements:
            exit_code, output = target.exec_sql(statement)
            if exit_code != 0:
                detail = output.decode(errors="replace").strip()
                msg = f"External PostgreSQL init_sql failed on {target.database!r}: {detail}"
                raise RuntimeError(msg)

    if sys_id:
        endpoint_id = f"extpg:{target.host}:{target.port}:{sys_id}"
        run_container_init_once(endpoint_id, f"postgres:{target.database}", fingerprint, _run, lock_dir=lock_dir)
        return
    base_dir = Path(lock_dir) if lock_dir is not None else Path(tempfile.gettempdir())
    base_dir.mkdir(parents=True, exist_ok=True)
    key = simple_string_hash(f"extpg:{target.host}:{target.port}:{target.database}:{fingerprint}")
    with filelock.FileLock(str(base_dir / f"pytest-databases-extpg-init-{key}.lock"), timeout=180.0):
        _run()
