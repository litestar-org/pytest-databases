"""MariaDB container service fixtures."""

from __future__ import annotations

import contextlib
import os
import shlex
import time
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING, Any

import filelock
import pytest
from docker.errors import APIError, NotFound

from pytest_databases.helpers import (
    env_port,
    exec_output_to_bytes,
    get_xdist_worker_num,
    read_init_scripts,
    run_container_init_once,
    simple_string_hash,
    tcp_port_open,
)
from pytest_databases.types import ServiceContainer, XdistIsolationLevel

if TYPE_CHECKING:
    from collections.abc import Generator, Mapping, Sequence

    from docker.models.containers import Container

    from pytest_databases._service import DockerService

_DB_INIT_LOCK_TIMEOUT: float = 180.0

__all__ = (
    "MariaDBService",
    "exec_mariadb",
    "mariadb_113_service",
    "mariadb_114_service",
    "mariadb_118_service",
    "mariadb_122_service",
    "mariadb_123_service",
    "mariadb_130_service",
    "mariadb_database",
    "mariadb_password",
    "mariadb_port",
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

    def exec_sql(
        self,
        sql: str,
        *,
        database: str | None = None,
        user: str | None = None,
        password: str | None = None,
        batch: bool = True,
    ) -> tuple[int, bytes]:
        """Execute ``sql`` via the in-container ``mariadb`` client over TCP loopback.

        Returns:
            Tuple of ``(exit_code, output_bytes)``.
        """
        return exec_mariadb(
            self.container,
            sql,
            user=self.user if user is None else user,
            password=self.password if password is None else password,
            database=self.db if database is None else database,
            batch=batch,
        )


def exec_mariadb(
    container: Container,
    sql: str,
    *,
    user: str = "root",
    password: str = "",
    database: str | None = None,
    batch: bool = True,
) -> tuple[int, bytes]:
    """Execute ``sql`` inside a MariaDB container using ``MYSQL_PWD`` authentication.

    Args:
        container: Running MariaDB container handle.
        sql: SQL statement(s) passed to ``mariadb -e``.
        user: MariaDB user name.
        password: Password passed via ``MYSQL_PWD`` environment variable.
        database: Optional target database name.
        batch: When ``True``, adds ``--batch --skip-column-names`` for clean scalar/tabular parsing.

    Returns:
        Tuple of ``(exit_code, output_bytes)``.
    """
    cmd = ["mariadb", "--protocol=tcp", "-h", "127.0.0.1", f"--user={user}"]
    if batch:
        cmd.extend(["--batch", "--skip-column-names"])
    if database:
        cmd.extend(["-D", database])
    cmd.extend(["-e", sql])
    env = {"MYSQL_PWD": password} if password else None
    try:
        result = container.exec_run(cmd, environment=env)
    except (APIError, NotFound) as exc:
        return -1, str(exc).encode()
    code = result.exit_code if result.exit_code is not None else -1
    return code, exec_output_to_bytes(result.output)


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
    *,
    host_port: int | None = None,
    command: str | Sequence[str] | None = None,
    env: Mapping[str, str] | None = None,
    init_sql: str | Path | Sequence[str | Path] | None = None,
    timeout: int = 120,
    pause: float = 1.0,
) -> Generator[MariaDBService, None, None]:
    """Start and manage a MariaDB container service with ``performance_schema`` enabled by default.

    Yields:
        Active :class:`MariaDBService` instance bound to ``database`` (or ``<database>_<worker>`` under xdist).

    Raises:
        ValueError: If ``database`` or ``user`` is invalid.
        RuntimeError: If database provisioning, user grants, or ``init_sql`` fails.
    """
    base_db = _validate_mariadb_identifier(database)
    if not user:
        msg = "MariaDB user must be non-empty."
        raise ValueError(msg)
    resolved_name, db_name = _resolve_mariadb_targets(name, base_db, isolation_level)

    def check(_service: ServiceContainer) -> bool:
        code, _ = exec_mariadb(_service.container, "SELECT 1", user="root", password=root_password)
        return code == 0 and tcp_port_open(_service.host, _service.port)

    with docker_service.run(
        image=image,
        check=check,
        container_port=3306,
        name=resolved_name,
        command=_build_mariadb_command(command),
        env=_build_mariadb_env(
            user=user,
            password=password,
            root_password=root_password,
            database=base_db,
            extra_env=env,
        ),
        timeout=timeout,
        pause=pause,
        transient=isolation_level == "server",
        host_port=host_port,
    ) as service:
        lock_path = _resolve_db_init_lock_path(docker_service, service.container)
        _provision_mariadb_database(
            service.container,
            fixture_name=resolved_name,
            db_name=db_name,
            user=user,
            password=password,
            root_password=root_password,
            lock_path=lock_path,
        )
        _apply_mariadb_init_sql(
            service.container,
            db_name=db_name,
            root_password=root_password,
            init_sql=init_sql,
            lock_dir=docker_service.temp_dir,
        )
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


@pytest.fixture(scope="session")
def mariadb_port() -> int | None:
    """Return an optional pinned host port for MariaDB containers from ``MARIADB_PORT``."""
    return env_port("MARIADB_PORT")


def _make_mariadb_service_fixture(fixture_name: str, image: str, name: str, doc: str) -> Any:
    """Create a session-scoped MariaDB service fixture for a specific version tag."""

    def _fixture(
        docker_service: DockerService,
        xdist_mariadb_isolation_level: XdistIsolationLevel,
        mariadb_user: str,
        mariadb_password: str,
        mariadb_root_password: str,
        mariadb_database: str,
        mariadb_port: int | None,
    ) -> Generator[MariaDBService, None, None]:
        with provide_mariadb_service(
            docker_service=docker_service,
            image=image,
            name=name,
            isolation_level=xdist_mariadb_isolation_level,
            user=mariadb_user,
            password=mariadb_password,
            root_password=mariadb_root_password,
            database=mariadb_database,
            host_port=mariadb_port,
        ) as service:
            yield service

    _fixture.__name__ = fixture_name
    _fixture.__qualname__ = fixture_name
    _fixture.__doc__ = doc
    _fixture.__module__ = __name__
    return pytest.fixture(autouse=False, scope="session")(_fixture)


mariadb_113_service = _make_mariadb_service_fixture(
    "mariadb_113_service",
    "mariadb:11.3",
    "mariadb-11.3",
    "Provide a running MariaDB 11.3 container service.",
)
mariadb_114_service = _make_mariadb_service_fixture(
    "mariadb_114_service",
    "mariadb:11.4",
    "mariadb-11.4",
    "Provide a running MariaDB 11.4 container service.",
)
mariadb_118_service = _make_mariadb_service_fixture(
    "mariadb_118_service",
    "mariadb:11.8",
    "mariadb-11.8",
    "Provide a running MariaDB 11.8 LTS container service.",
)
mariadb_122_service = _make_mariadb_service_fixture(
    "mariadb_122_service",
    "mariadb:12.2",
    "mariadb-12.2",
    "Provide a running MariaDB 12.2 container service.",
)
mariadb_123_service = _make_mariadb_service_fixture(
    "mariadb_123_service",
    "mariadb:12.3",
    "mariadb-12.3",
    "Provide a running MariaDB 12.3 container service.",
)
mariadb_130_service = _make_mariadb_service_fixture(
    "mariadb_130_service",
    "mariadb:13.0",
    "mariadb-13.0",
    "Provide a running MariaDB 13.0 container service.",
)


@pytest.fixture(autouse=False, scope="session")
def mariadb_service(mariadb_114_service: MariaDBService) -> MariaDBService:
    """Provide the default MariaDB container service."""
    return mariadb_114_service


def _validate_mariadb_identifier(name: str) -> str:
    """Validate that ``name`` fits MariaDB's 64-character identifier rules without NUL or control bytes."""
    if not name or len(name) > 64 or any(ord(ch) < 32 for ch in name):
        msg = f"Invalid MariaDB database identifier: {name!r}"
        raise ValueError(msg)
    return name


def _quote_mariadb_identifier(name: str) -> str:
    """Quote a MariaDB schema identifier with backticks."""
    return f"`{name.replace('`', '``')}`"


def _quote_mariadb_literal(value: str) -> str:
    """Quote a MariaDB string literal escaping backslashes and single quotes."""
    escaped = value.replace("\\", "\\\\").replace("'", "''")
    return f"'{escaped}'"


def _resolve_mariadb_targets(name: str, base_db: str, isolation_level: XdistIsolationLevel) -> tuple[str, str]:
    """Compute container logical name and database name for the active pytest-xdist worker."""
    worker_num = get_xdist_worker_num()
    if worker_num is None:
        return name, base_db
    suffix = f"_{worker_num}"
    if isolation_level == "server":
        return f"{name}{suffix}", base_db
    return name, _validate_mariadb_identifier(f"{base_db}{suffix}")


def _build_mariadb_command(command: str | Sequence[str] | None) -> str | list[str]:
    """Build ``mariadbd`` command flags keeping ``--performance-schema=ON`` unless explicitly overridden."""
    if command is None:
        return "--performance-schema=ON"
    args = shlex.split(command) if isinstance(command, str) else list(command)
    has_perf_flag = any(
        arg.startswith(("--performance-schema", "--performance_schema", "--skip-performance-schema")) for arg in args
    )
    return args if has_perf_flag else ["--performance-schema=ON", *args]


def _build_mariadb_env(
    *,
    user: str,
    password: str,
    root_password: str,
    database: str,
    extra_env: Mapping[str, str] | None,
) -> dict[str, str]:
    """Compose container environment variables for MariaDB initialization."""
    container_env: dict[str, str] = {
        "MARIADB_ROOT_PASSWORD": root_password,
        "MARIADB_DATABASE": database,
        "MARIADB_ROOT_HOST": "%",
        "LANG": "C.UTF-8",
    }
    if user != "root":
        container_env["MARIADB_USER"] = user
        container_env["MARIADB_PASSWORD"] = password
    if extra_env:
        container_env.update(extra_env)
    return container_env


def _resolve_db_init_lock_path(docker_service: DockerService, container: Container) -> Path | None:
    """Resolve the cross-worker lock file path for container database initialization."""
    container_id = getattr(container, "id", None)
    if not isinstance(container_id, str) or not container_id.strip():
        return None
    temp_dir = Path(docker_service.temp_dir)
    temp_dir.mkdir(parents=True, exist_ok=True)
    return temp_dir / f"{container_id.strip()}_db_init.lock"


def _provision_mariadb_database(
    container: Container,
    *,
    fixture_name: str,
    db_name: str,
    user: str,
    password: str,
    root_password: str,
    lock_path: Path | None = None,
) -> None:
    """Ensure ``db_name`` exists and ``user`` has global privileges and verified login access."""
    quoted_db = _quote_mariadb_identifier(db_name)
    setup_parts = [f"CREATE DATABASE IF NOT EXISTS {quoted_db}"]
    if user != "root":
        setup_parts.extend((
            f"GRANT ALL PRIVILEGES ON *.* TO {_quote_mariadb_literal(user)}@'%'",
            "FLUSH PRIVILEGES",
        ))
    setup_sql = "; ".join(setup_parts) + ";"
    lock_context: contextlib.AbstractContextManager[object] = (
        filelock.FileLock(str(lock_path), timeout=_DB_INIT_LOCK_TIMEOUT)
        if lock_path is not None
        else contextlib.nullcontext()
    )
    last_err = b""
    with lock_context:
        for attempt in range(15):
            setup_code, setup_out = exec_mariadb(container, setup_sql, user="root", password=root_password, batch=False)
            if setup_code == 0:
                verify_code, verify_out = exec_mariadb(
                    container, "SELECT 1", user=user, password=password, database=db_name
                )
                if verify_code == 0:
                    return
                last_err = verify_out
            else:
                last_err = setup_out
            time.sleep(1 + attempt * 0.5)
    msg = (
        f"MariaDB fixture {fixture_name!r}: user {user!r} could not reach database "
        f"{db_name!r} after 15 attempts. Last output: {last_err!r}"
    )
    raise RuntimeError(msg)


def _apply_mariadb_init_sql(
    container: Container,
    *,
    db_name: str,
    root_password: str,
    init_sql: str | Path | Sequence[str | Path] | None,
    lock_dir: Path | None = None,
) -> None:
    """Execute ``init_sql`` statements once per ``(container, db_name)`` as ``root``."""
    statements = read_init_scripts(init_sql)
    if not statements:
        return
    fingerprint = simple_string_hash("\n;\n".join(statements))

    def _run() -> None:
        for statement in statements:
            code, output = exec_mariadb(
                container,
                statement,
                user="root",
                password=root_password,
                database=db_name,
                batch=False,
            )
            if code != 0:
                detail = output.decode(errors="replace").strip()
                msg = f"MariaDB init_sql failed on database {db_name!r} (exit {code}): {detail}"
                raise RuntimeError(msg)

    run_container_init_once(container, f"mariadb:{db_name}", fingerprint, _run, lock_dir=lock_dir)
