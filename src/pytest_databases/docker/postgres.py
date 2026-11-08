"""PostgreSQL, pgvector, ParadeDB, and AlloyDB Omni container service fixtures."""

from __future__ import annotations

import dataclasses
import importlib
import inspect
import os
import time
import warnings
from contextlib import contextmanager
from typing import TYPE_CHECKING, Any

import pytest

from pytest_databases._postgres_templates import (
    DEFAULT_TEMPLATE_NAME,
    PostgresTemplateSupport,
    make_connection_string,
    split_template_setup,
    validate_identifier,
)
from pytest_databases.helpers import exec_output_to_bytes, get_xdist_worker_num, tcp_port_open
from pytest_databases.types import PostgresXdistIsolationLevel, ServiceContainer

if TYPE_CHECKING:
    from collections.abc import Callable, Generator, Sequence
    from pathlib import Path

    from docker.models.containers import Container
    from psycopg import Connection

    from pytest_databases._service import DockerService

__all__ = (
    "PostgresService",
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
    "postgres_template_fingerprint_sources",
    "postgres_template_lock_dir",
    "postgres_template_name",
    "postgres_template_options",
    "postgres_template_setup",
    "postgres_user",
    "provide_postgres_connection",
    "provide_postgres_service",
    "xdist_postgres_isolation_level",
)


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


@dataclasses.dataclass(frozen=True)
class PostgresTemplateOptions:
    """Template database settings used when the isolation level is ``"template"``.

    ``name`` is the template name prefix (None means ``"pytest_databases_template"``). ``setup`` is a callable
    receiving the staging :class:`PostgresService`, or SQL statements / ``.sql`` file paths whose text and contents are
    hashed into the template name. ``fingerprint_sources`` adds strings, bytes, files, or directories to that digest
    (use it to version a setup callable). ``lock_dir`` holds the cross-worker lock file (None means the system temp
    directory) and ``lock_timeout`` is the number of seconds to wait for it.
    """

    name: str | None = None
    setup: Callable[[PostgresService], object] | str | Path | Sequence[str | Path] | None = None
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
    return "postgres"


def _make_port_fixture(fixture_name: str, env_var: str, doc: str) -> Any:
    """Create a session-scoped optional host-port fixture backed by ``env_var``."""

    def _fixture() -> int | None:
        return _env_port(env_var)

    _fixture.__name__ = fixture_name
    _fixture.__qualname__ = fixture_name
    _fixture.__doc__ = doc
    _fixture.__module__ = __name__
    return pytest.fixture(autouse=False, scope="session")(_fixture)


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
) -> Generator[PostgresService, None, None]:
    """Start and validate a PostgreSQL-compatible container service.

    Readiness runs ``SELECT 1`` through ``psql`` inside the container and then opens a TCP connection to the
    published host port. With ``xdist_postgres_isolate="template"`` the template described by ``template`` is built
    once per container and the service database (``pytest_databases`` or ``pytest_databases_<worker>``) is cloned
    from it, with or without xdist.

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
        return exit_code == 0 and output.strip() == b"1" and tcp_port_open(_service.host, _service.port)

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
        if xdist_postgres_isolate == "template":
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
                fingerprint_sources=options.fingerprint_sources,
                lock_dir=options.lock_dir,
                lock_timeout=options.lock_timeout,
            )
            admin.create_worker_database_from_template(template_name, db_name)
        else:
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


def _make_postgres_service_fixture(
    fixture_name: str,
    *,
    name: str,
    port_fixture: str,
    doc: str,
    image: str | None = None,
    image_fixture: str | None = None,
) -> Any:
    """Create a session-scoped PostgreSQL family service fixture."""

    def _fixture(**kwargs: Any) -> Generator[PostgresService, None, None]:
        resolved_image = kwargs[image_fixture] if image_fixture is not None else str(image)
        with provide_postgres_service(
            kwargs["docker_service"],
            image=resolved_image,
            name=name,
            xdist_postgres_isolate=kwargs["xdist_postgres_isolation_level"],
            host=kwargs["postgres_host"],
            user=kwargs["postgres_user"],
            password=kwargs["postgres_password"],
            host_port=kwargs[port_fixture],
            template=kwargs["postgres_template_options"],
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
        port_fixture,
        "postgres_template_options",
    ])
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
)
postgres_12_service = _make_postgres_service_fixture(
    "postgres_12_service",
    image="postgres:12",
    name="postgres-12",
    port_fixture="postgres_12_port",
    doc="Provide a PostgreSQL 12 service.",
)
postgres_13_service = _make_postgres_service_fixture(
    "postgres_13_service",
    image="postgres:13",
    name="postgres-13",
    port_fixture="postgres_13_port",
    doc="Provide a PostgreSQL 13 service.",
)
postgres_14_service = _make_postgres_service_fixture(
    "postgres_14_service",
    image="postgres:14",
    name="postgres-14",
    port_fixture="postgres_14_port",
    doc="Provide a PostgreSQL 14 service.",
)
postgres_15_service = _make_postgres_service_fixture(
    "postgres_15_service",
    image="postgres:15",
    name="postgres-15",
    port_fixture="postgres_15_port",
    doc="Provide a PostgreSQL 15 service.",
)
postgres_16_service = _make_postgres_service_fixture(
    "postgres_16_service",
    image="postgres:16",
    name="postgres-16",
    port_fixture="postgres_16_port",
    doc="Provide a PostgreSQL 16 service.",
)
postgres_17_service = _make_postgres_service_fixture(
    "postgres_17_service",
    image="postgres:17",
    name="postgres-17",
    port_fixture="postgres_17_port",
    doc="Provide a PostgreSQL 17 service.",
)
postgres_18_service = _make_postgres_service_fixture(
    "postgres_18_service",
    image="postgres:18",
    name="postgres-18",
    port_fixture="postgres_18_port",
    doc="Provide a PostgreSQL 18 service.",
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
)
pgvector_13_service = _make_postgres_service_fixture(
    "pgvector_13_service",
    image="pgvector/pgvector:pg13",
    name="pgvector-13",
    port_fixture="pgvector_13_port",
    doc="Provide a pgvector PG13 service.",
)
pgvector_14_service = _make_postgres_service_fixture(
    "pgvector_14_service",
    image="pgvector/pgvector:pg14",
    name="pgvector-14",
    port_fixture="pgvector_14_port",
    doc="Provide a pgvector PG14 service.",
)
pgvector_15_service = _make_postgres_service_fixture(
    "pgvector_15_service",
    image="pgvector/pgvector:pg15",
    name="pgvector-15",
    port_fixture="pgvector_15_port",
    doc="Provide a pgvector PG15 service.",
)
pgvector_16_service = _make_postgres_service_fixture(
    "pgvector_16_service",
    image="pgvector/pgvector:pg16",
    name="pgvector-16",
    port_fixture="pgvector_16_port",
    doc="Provide a pgvector PG16 service.",
)
pgvector_17_service = _make_postgres_service_fixture(
    "pgvector_17_service",
    image="pgvector/pgvector:pg17",
    name="pgvector-17",
    port_fixture="pgvector_17_port",
    doc="Provide a pgvector PG17 service.",
)
pgvector_18_service = _make_postgres_service_fixture(
    "pgvector_18_service",
    image="pgvector/pgvector:pg18",
    name="pgvector-18",
    port_fixture="pgvector_18_port",
    doc="Provide a pgvector PG18 service.",
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
)
paradedb_15_service = _make_postgres_service_fixture(
    "paradedb_15_service",
    image="paradedb/paradedb:latest-pg15",
    name="paradedb-15",
    port_fixture="paradedb_15_port",
    doc="Provide a ParadeDB PG15 service.",
)
paradedb_16_service = _make_postgres_service_fixture(
    "paradedb_16_service",
    image="paradedb/paradedb:latest-pg16",
    name="paradedb-16",
    port_fixture="paradedb_16_port",
    doc="Provide a ParadeDB PG16 service.",
)
paradedb_17_service = _make_postgres_service_fixture(
    "paradedb_17_service",
    image="paradedb/paradedb:latest-pg17",
    name="paradedb-17",
    port_fixture="paradedb_17_port",
    doc="Provide a ParadeDB PG17 service.",
)
paradedb_18_service = _make_postgres_service_fixture(
    "paradedb_18_service",
    image="paradedb/paradedb:latest-pg18",
    name="paradedb-18",
    port_fixture="paradedb_18_port",
    doc="Provide a ParadeDB PG18 service.",
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

alloydb_omni_service = _make_postgres_service_fixture(
    "alloydb_omni_service",
    image_fixture="alloydb_omni_image",
    name="alloydb-omni",
    port_fixture="alloydb_omni_port",
    doc="Provide the default AlloyDB Omni service.",
)
alloydb_omni_15_service = _make_postgres_service_fixture(
    "alloydb_omni_15_service",
    image="gcr.io/alloydb-omni/alloydbomni:15",
    name="alloydb-omni-15",
    port_fixture="alloydb_omni_15_port",
    doc="Provide an AlloyDB Omni 15 service.",
)
alloydb_omni_16_service = _make_postgres_service_fixture(
    "alloydb_omni_16_service",
    image="gcr.io/alloydb-omni/alloydbomni:16",
    name="alloydb-omni-16",
    port_fixture="alloydb_omni_16_port",
    doc="Provide an AlloyDB Omni 16 service.",
)
alloydb_omni_17_service = _make_postgres_service_fixture(
    "alloydb_omni_17_service",
    image="gcr.io/alloydb-omni/alloydbomni:17",
    name="alloydb-omni-17",
    port_fixture="alloydb_omni_17_port",
    doc="Provide an AlloyDB Omni 17 service.",
)
alloydb_omni_18_service = _make_postgres_service_fixture(
    "alloydb_omni_18_service",
    image="gcr.io/alloydb-omni/alloydbomni:18",
    name="alloydb-omni-18",
    port_fixture="alloydb_omni_18_port",
    doc="Provide an AlloyDB Omni 18 service.",
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


def _env_port(var_name: str) -> int | None:
    """Return an integer port from environment variable ``var_name`` if set."""
    value = os.environ.get(var_name)
    return int(value) if value else None
