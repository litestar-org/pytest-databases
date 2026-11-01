"""Embedded and non-containerized PostgreSQL service management."""

from __future__ import annotations

import atexit
import contextlib
import dataclasses
import hashlib
import json
import os
import re
import shutil
import socket
import subprocess
import tempfile
import time
from contextlib import contextmanager
from pathlib import Path
from typing import TYPE_CHECKING, Any

import filelock
import pytest

from pytest_databases.helpers import get_xdist_worker_id, get_xdist_worker_num

pgembed: Any = None
pgserver: Any = None

with contextlib.suppress(ImportError):
    import pgembed as _pgembed

    pgembed = _pgembed

with contextlib.suppress(ImportError):
    import pgserver as _pgserver

    pgserver = _pgserver

if TYPE_CHECKING:
    from collections.abc import Callable, Generator, Sequence
    from typing import Literal

    from pytest_databases.types import XdistIsolationLevel

__all__ = (
    "EmbeddedPostgresService",
    "PostgresBinaries",
    "clone_template_database",
    "compute_schema_fingerprint",
    "create_worker_database_from_template",
    "drop_database_force",
    "embedded_postgres_database",
    "embedded_postgres_password",
    "embedded_postgres_port",
    "embedded_postgres_service",
    "embedded_postgres_template_lock_dir",
    "embedded_postgres_template_name",
    "embedded_postgres_template_setup",
    "embedded_postgres_user",
    "ensure_template_database",
    "exec_psql",
    "make_connection_string",
    "provide_embedded_postgres_service",
    "resolve_postgres_binaries",
    "sweep_worker_databases",
    "xdist_embedded_postgres_isolation_level",
)

IDENTIFIER_PATTERN = re.compile(r"^[A-Za-z_][A-Za-z0-9_$]*$")


@dataclasses.dataclass(frozen=True)
class PostgresBinaries:
    """Paths to verified local PostgreSQL server and client binaries."""

    initdb: Path
    postgres: Path
    pg_ctl: Path
    psql: Path
    pg_config: Path | None = None

    def verify(self) -> None:
        """Verify all mandatory binary paths exist and are executable."""
        for name, path in (
            ("initdb", self.initdb),
            ("postgres", self.postgres),
            ("pg_ctl", self.pg_ctl),
            ("psql", self.psql),
        ):
            if not path.is_file():
                msg = f"PostgreSQL {name} binary does not exist: {path}"
                raise FileNotFoundError(msg)
            if not os.access(path, os.X_OK):
                msg = f"PostgreSQL {name} binary is not executable: {path}"
                raise PermissionError(msg)


def _find_binaries_in_dir(directory: Path) -> PostgresBinaries | None:
    """Attempt to locate mandatory PostgreSQL binaries within a directory."""
    initdb = directory / "initdb"
    postgres = directory / "postgres"
    pg_ctl = directory / "pg_ctl"
    psql = directory / "psql"
    pg_config = directory / "pg_config"
    if initdb.is_file() and postgres.is_file():
        binaries = PostgresBinaries(
            initdb=initdb,
            postgres=postgres,
            pg_ctl=pg_ctl if pg_ctl.is_file() else postgres,
            psql=psql if psql.is_file() else directory / "psql",
            pg_config=pg_config if pg_config.is_file() else None,
        )
        binaries.verify()
        return binaries
    return None


def _find_binaries_on_path() -> PostgresBinaries | None:
    """Attempt to locate mandatory PostgreSQL binaries on system PATH."""
    which_initdb = shutil.which("initdb")
    which_postgres = shutil.which("postgres")
    which_pg_ctl = shutil.which("pg_ctl")
    which_psql = shutil.which("psql")
    which_pg_config = shutil.which("pg_config")

    if which_initdb and which_postgres and which_psql:
        binaries = PostgresBinaries(
            initdb=Path(which_initdb),
            postgres=Path(which_postgres),
            pg_ctl=Path(which_pg_ctl) if which_pg_ctl else Path(which_postgres),
            psql=Path(which_psql),
            pg_config=Path(which_pg_config) if which_pg_config else None,
        )
        binaries.verify()
        return binaries
    return None


def _find_binaries_in_system_locations() -> PostgresBinaries | None:
    """Probe pg_config and standard non-PATH system directories for PostgreSQL binaries."""
    pg_config_path = shutil.which("pg_config")
    if pg_config_path:
        with contextlib.suppress(Exception):
            result = subprocess.run([pg_config_path, "--bindir"], capture_output=True, text=True, check=False)
            if result.returncode == 0 and result.stdout.strip():
                binaries = _find_binaries_in_dir(Path(result.stdout.strip()))
                if binaries is not None:
                    return binaries

    glob_patterns = (
        ("/usr/lib/postgresql", "*/bin"),
        ("/opt/homebrew/opt", "postgresql@*/bin"),
        ("/usr/local/opt", "postgresql@*/bin"),
        ("/usr", "pgsql-*/bin"),
    )
    for root_str, pattern in glob_patterns:
        root = Path(root_str)
        if not root.is_dir():
            continue
        matches = [p for p in root.glob(pattern) if p.is_dir()]
        matches.sort(
            key=lambda p: [int(s) if s.isdigit() else s for s in re.split(r"(\d+)", str(p))],
            reverse=True,
        )
        for candidate_dir in matches:
            binaries = _find_binaries_in_dir(candidate_dir)
            if binaries is not None:
                return binaries

    return None


def resolve_postgres_binaries(bin_dir: Path | str | None = None) -> PostgresBinaries:
    """Resolve PostgreSQL server binaries from explicit paths, pgembed, pgserver, or host PATH.

    Args:
        bin_dir: Optional explicit directory containing postgres binaries.

    Returns:
        Verified PostgresBinaries instance.

    Raises:
        RuntimeError: If mandatory PostgreSQL binaries cannot be discovered.
    """
    candidate_dirs: list[Path] = []

    if bin_dir is not None:
        candidate_dirs.append(Path(bin_dir))

    env_bin = os.environ.get("PG_BIN_DIR")
    if env_bin:
        candidate_dirs.append(Path(env_bin))

    if pgembed is not None:
        pgembed_bin = getattr(pgembed, "POSTGRES_BIN_PATH", None)
        if pgembed_bin is not None:
            candidate_dirs.append(Path(pgembed_bin))

    if pgserver is not None:
        pgserver_bin = (
            getattr(pgserver, "POSTGRES_BIN_PATH", None)
            or getattr(getattr(pgserver, "postgres_server", None), "POSTGRES_BIN_PATH", None)
            or getattr(getattr(pgserver, "_commands", None), "POSTGRES_BIN_PATH", None)
        )
        if pgserver_bin is not None:
            candidate_dirs.append(Path(pgserver_bin))

    for candidate in candidate_dirs:
        discovered = _find_binaries_in_dir(candidate)
        if discovered is not None:
            return discovered

    path_discovered = _find_binaries_on_path()
    if path_discovered is not None:
        return path_discovered

    system_discovered = _find_binaries_in_system_locations()
    if system_discovered is not None:
        return system_discovered

    msg = (
        "PostgreSQL server binaries ('initdb', 'postgres', 'psql') were not found. "
        "Install PostgreSQL on your system PATH or install 'pgembed' "
        "(pip install pytest-databases[embedded-postgres] or pip install pgembed)."
    )
    raise RuntimeError(msg)


@dataclasses.dataclass
class EmbeddedPostgresService:
    """Connection metadata and operational helpers for an embedded PostgreSQL server."""

    host: str
    port: int
    user: str
    password: str
    database: str
    data_dir: Path
    binaries: PostgresBinaries
    process: subprocess.Popen[bytes] | None = None
    unix_socket_dir: Path | None = None

    @property
    def dsn(self) -> str:
        """Format a standard libpq connection string."""
        return make_connection_string(
            host=self.host,
            port=self.port,
            user=self.user,
            password=self.password,
            database=self.database,
        )

    @property
    def connection_config(self) -> dict[str, Any]:
        """Dictionary of connection parameters matching database adapter conventions."""
        return {
            "host": self.host,
            "port": self.port,
            "user": self.user,
            "password": self.password,
            "database": self.database,
        }

    def clone_template_database(self, target_db: str, *, source_db: str | None = None) -> str:
        """Clone ``source_db`` (defaults to ``self.database``) into ``target_db``."""
        return clone_template_database(self, target_db=target_db, source_db=source_db)

    def drop_database_force(self, db_name: str) -> None:
        """Terminate active backends and drop ``db_name`` if it exists."""
        drop_database_force(self, db_name=db_name)

    def ensure_template(
        self,
        template_name: str,
        *,
        setup_fn: Callable[[EmbeddedPostgresService], Any] | None = None,
        setup_sql: str | Sequence[str] | None = None,
        lock_dir: Path | str | None = None,
        lock_timeout: float = 180.0,
        fingerprint_sources: Sequence[str | bytes | Path] | None = None,
    ) -> str:
        """Ensure a PostgreSQL template database exists, initializing it if absent."""
        return ensure_template_database(
            self,
            template_name=template_name,
            setup_fn=setup_fn,
            setup_sql=setup_sql,
            lock_dir=lock_dir,
            lock_timeout=lock_timeout,
            fingerprint_sources=fingerprint_sources,
        )

    def create_worker_database_from_template(
        self,
        template_name: str,
        worker_db: str,
    ) -> str:
        """Create a worker database by cloning an existing PostgreSQL template database."""
        return create_worker_database_from_template(
            self,
            template_name=template_name,
            worker_db=worker_db,
        )

    def sweep_worker_databases(self, prefix: str = "pytest_databases_") -> list[str]:
        """Terminate backends and drop transient worker databases matching ``prefix`` while preserving templates."""
        return sweep_worker_databases(self, prefix=prefix)

    @staticmethod
    def compute_fingerprint(*sources: str | bytes | Path) -> str:
        """Compute a deterministic SHA-256 fingerprint from strings, bytes, files, or directories."""
        return compute_schema_fingerprint(*sources)

    def exec_psql(
        self,
        sql: str,
        *,
        database: str | None = None,
        tuples_only: bool = False,
        timeout: float = 30.0,
    ) -> tuple[int, bytes]:
        """Execute a SQL statement via ``psql`` against this service."""
        return exec_psql(
            self.binaries,
            user=self.user,
            password=self.password,
            database=database or self.database,
            host=self.host,
            port=self.port,
            sql=sql,
            tuples_only=tuples_only,
            timeout=timeout,
        )


def make_connection_string(host: str, port: int, user: str, password: str, database: str) -> str:
    """Format a libpq connection string for PostgreSQL."""
    return f"dbname={database} user={user} host={host} port={port} password={password}"


def exec_psql(
    binaries: PostgresBinaries | Path,
    *,
    user: str,
    password: str,
    database: str,
    host: str = "127.0.0.1",
    port: int = 5432,
    sql: str,
    tuples_only: bool = False,
    timeout: float = 30.0,
) -> tuple[int, bytes]:
    """Execute a SQL statement via ``psql`` over the local TCP interface.

    Args:
        binaries: Verified PostgresBinaries instance or explicit psql binary path.
        user: Database user name.
        password: Database password.
        database: Target database name.
        host: Hostname or IP to connect to.
        port: Port to connect to.
        sql: SQL query string.
        tuples_only: Whether to emit unaligned raw tuples.
        timeout: Subprocess execution timeout in seconds.

    Returns:
        Tuple of (exit_code, output_bytes).
    """
    psql_path = binaries.psql if isinstance(binaries, PostgresBinaries) else binaries
    cmd = [
        str(psql_path),
        "-v",
        "ON_ERROR_STOP=1",
        "-h",
        host,
        "-p",
        str(port),
        "-U",
        user,
        "-d",
        database,
    ]
    if tuples_only:
        cmd.extend(["-tAc", sql])
    else:
        cmd.extend(["-c", sql])

    env = {**os.environ, "PGPASSWORD": password}
    try:
        result = subprocess.run(
            cmd,
            env=env,
            capture_output=True,
            timeout=timeout,
            check=False,
        )
    except (subprocess.TimeoutExpired, OSError) as exc:
        return -1, str(exc).encode("utf-8")
    else:
        output = result.stdout or result.stderr
        return result.returncode, output


def _validate_identifier(identifier: str) -> str:
    """Validate that an SQL identifier contains only alphanumeric characters and underscores."""
    if not IDENTIFIER_PATTERN.fullmatch(identifier):
        msg = f"Invalid SQL identifier: {identifier!r}"
        raise ValueError(msg)
    return identifier


def clone_template_database(
    service: EmbeddedPostgresService,
    *,
    target_db: str,
    source_db: str | None = None,
) -> str:
    """Clone ``source_db`` into ``target_db`` using PostgreSQL ``CREATE DATABASE ... TEMPLATE``.

    Args:
        service: Connected EmbeddedPostgresService instance.
        target_db: Name of the cloned database to create.
        source_db: Source database or template name (defaults to ``service.database``).

    Returns:
        The target database name.
    """
    safe_source = _validate_identifier(source_db or service.database)
    safe_target = _validate_identifier(target_db)
    terminate_sql = (
        "SELECT pg_terminate_backend(pid) FROM pg_stat_activity "
        f"WHERE datname = '{safe_source}' AND pid <> pg_backend_pid();"
    )
    exec_psql(
        service.binaries,
        user=service.user,
        password=service.password,
        database="postgres",
        host=service.host,
        port=service.port,
        sql=terminate_sql,
    )
    exit_code, output = exec_psql(
        service.binaries,
        user=service.user,
        password=service.password,
        database="postgres",
        host=service.host,
        port=service.port,
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
    service: EmbeddedPostgresService,
    *,
    db_name: str,
) -> None:
    """Terminate active backends and drop ``db_name`` if it exists.

    Args:
        service: Connected EmbeddedPostgresService instance.
        db_name: Name of the database to drop.
    """
    safe_db = _validate_identifier(db_name)
    terminate_sql = (
        "SELECT pg_terminate_backend(pid) FROM pg_stat_activity "
        f"WHERE datname = '{safe_db}' AND pid <> pg_backend_pid();"
    )
    exec_psql(
        service.binaries,
        user=service.user,
        password=service.password,
        database="postgres",
        host=service.host,
        port=service.port,
        sql=terminate_sql,
    )
    exit_code, output = exec_psql(
        service.binaries,
        user=service.user,
        password=service.password,
        database="postgres",
        host=service.host,
        port=service.port,
        sql=f'DROP DATABASE IF EXISTS "{safe_db}";',
    )
    if exit_code != 0:
        msg = f"Failed to drop database {safe_db!r}: {output.decode(errors='replace').strip()}"
        raise RuntimeError(msg)


def compute_schema_fingerprint(*sources: str | bytes | Path) -> str:
    """Compute a deterministic SHA-256 fingerprint from strings, bytes, files, or directories.

    Args:
        *sources: String SQL, raw bytes, file paths, or directory paths to hash.

    Returns:
        A 12-character lowercase hex digest suitable for database name suffixing.
    """
    hasher = hashlib.sha256()
    for source in sources:
        if isinstance(source, bytes):
            hasher.update(b"bytes:")
            hasher.update(source)
        elif isinstance(source, Path):
            if source.exists():
                _hash_filesystem_path(hasher, source)
            else:
                hasher.update(b"path:")
                hasher.update(str(source).encode("utf-8"))
        elif isinstance(source, str):
            path_candidate = Path(source)
            if path_candidate.exists():
                _hash_filesystem_path(hasher, path_candidate)
            else:
                hasher.update(b"str:")
                hasher.update(source.encode("utf-8"))
    return hasher.hexdigest()[:12]


def _hash_filesystem_path(hasher: Any, path: Path) -> None:
    """Hash a file or recursively hash a directory in deterministic order."""
    if path.is_file():
        hasher.update(b"file:")
        hasher.update(path.name.encode("utf-8"))
        hasher.update(path.read_bytes())
    elif path.is_dir():
        hasher.update(b"dir:")
        hasher.update(path.name.encode("utf-8"))
        for entry in sorted(path.rglob("*")):
            if entry.is_file():
                hasher.update(entry.relative_to(path).as_posix().encode("utf-8"))
                hasher.update(entry.read_bytes())


def ensure_template_database(
    service: EmbeddedPostgresService,
    *,
    template_name: str,
    setup_fn: Callable[[EmbeddedPostgresService], Any] | None = None,
    setup_sql: str | Sequence[str] | None = None,
    lock_dir: Path | str | None = None,
    lock_timeout: float = 180.0,
    fingerprint_sources: Sequence[str | bytes | Path] | None = None,
) -> str:
    """Ensure a PostgreSQL template database exists, initializing it if absent using double-checked file locking.

    Args:
        service: Connected EmbeddedPostgresService instance.
        template_name: Target template database name (or prefix if fingerprint_sources are provided).
        setup_fn: Optional callable receiving a staging EmbeddedPostgresService instance to perform setup.
        setup_sql: Optional SQL statement or sequence of SQL statements executed against the staging database.
        lock_dir: Optional directory for cross-worker lock files (defaults to tempfile.gettempdir()).
        lock_timeout: Timeout in seconds for cross-worker file lock acquisition.
        fingerprint_sources: Optional sequence of files, directories, or strings to compute a fingerprint suffix.

    Returns:
        The validated and confirmed template database name.
    """
    resolved_name = template_name
    if fingerprint_sources is not None:
        digest = compute_schema_fingerprint(*fingerprint_sources)
        resolved_name = f"{template_name}_{digest}"
    safe_tpl = _validate_identifier(resolved_name)

    check_sql = f"SELECT 1 FROM pg_database WHERE datname = '{safe_tpl}' AND datistemplate = true;"
    exit_code, output = exec_psql(
        service.binaries,
        user=service.user,
        password=service.password,
        database="postgres",
        host=service.host,
        port=service.port,
        sql=check_sql,
        tuples_only=True,
    )
    if exit_code == 0 and output.strip() == b"1":
        return safe_tpl

    lock_base = Path(lock_dir or tempfile.gettempdir())
    lock_base.mkdir(parents=True, exist_ok=True)
    lock_path = lock_base / f"pytest_databases_tpl_{safe_tpl}.lock"

    with filelock.FileLock(str(lock_path), timeout=lock_timeout):
        exit_code, output = exec_psql(
            service.binaries,
            user=service.user,
            password=service.password,
            database="postgres",
            host=service.host,
            port=service.port,
            sql=check_sql,
            tuples_only=True,
        )
        if exit_code == 0 and output.strip() == b"1":
            return safe_tpl

        staging_name = _validate_identifier(f"{safe_tpl}_staging")
        drop_database_force(service, db_name=staging_name)

        exit_code, output = exec_psql(
            service.binaries,
            user=service.user,
            password=service.password,
            database="postgres",
            host=service.host,
            port=service.port,
            sql=f'CREATE DATABASE "{staging_name}";',
        )
        if exit_code != 0:
            msg = f"Failed to create staging database {staging_name!r}: {output.decode(errors='replace').strip()}"
            raise RuntimeError(msg)

        if setup_sql is not None:
            stmts = [setup_sql] if isinstance(setup_sql, str) else list(setup_sql)
            for stmt in stmts:
                exit_code, output = exec_psql(
                    service.binaries,
                    user=service.user,
                    password=service.password,
                    database=staging_name,
                    host=service.host,
                    port=service.port,
                    sql=stmt,
                )
                if exit_code != 0:
                    drop_database_force(service, db_name=staging_name)
                    msg = f"Failed to execute setup SQL on staging database {staging_name!r}: {output.decode(errors='replace').strip()}"
                    raise RuntimeError(msg)

        if setup_fn is not None:
            staging_service = dataclasses.replace(service, database=staging_name)
            try:
                setup_fn(staging_service)
            except Exception:
                drop_database_force(service, db_name=staging_name)
                raise

        terminate_sql = (
            "SELECT pg_terminate_backend(pid) FROM pg_stat_activity "
            f"WHERE datname = '{staging_name}' AND pid <> pg_backend_pid();"
        )
        exec_psql(
            service.binaries,
            user=service.user,
            password=service.password,
            database="postgres",
            host=service.host,
            port=service.port,
            sql=terminate_sql,
        )

        exit_code, output = exec_psql(
            service.binaries,
            user=service.user,
            password=service.password,
            database="postgres",
            host=service.host,
            port=service.port,
            sql=f'ALTER DATABASE "{staging_name}" WITH is_template = true allow_connections = false;',
        )
        if exit_code != 0:
            drop_database_force(service, db_name=staging_name)
            msg = f"Failed to mark staging database {staging_name!r} as template: {output.decode(errors='replace').strip()}"
            raise RuntimeError(msg)

        drop_database_force(service, db_name=safe_tpl)

        exit_code, output = exec_psql(
            service.binaries,
            user=service.user,
            password=service.password,
            database="postgres",
            host=service.host,
            port=service.port,
            sql=f'ALTER DATABASE "{staging_name}" RENAME TO "{safe_tpl}";',
        )
        if exit_code != 0:
            drop_database_force(service, db_name=staging_name)
            msg = f"Failed to rename staging database {staging_name!r} to {safe_tpl!r}: {output.decode(errors='replace').strip()}"
            raise RuntimeError(msg)

        return safe_tpl


def create_worker_database_from_template(
    service: EmbeddedPostgresService,
    *,
    template_name: str,
    worker_db: str,
) -> str:
    """Create a worker database by cloning an existing PostgreSQL template database.

    Args:
        service: Connected EmbeddedPostgresService instance.
        template_name: Existing template database name.
        worker_db: Target database name to create for the worker.

    Returns:
        The created worker database name.
    """
    safe_tpl = _validate_identifier(template_name)
    safe_worker_db = _validate_identifier(worker_db)
    drop_database_force(service, db_name=safe_worker_db)
    exit_code, output = exec_psql(
        service.binaries,
        user=service.user,
        password=service.password,
        database="postgres",
        host=service.host,
        port=service.port,
        sql=f'CREATE DATABASE "{safe_worker_db}" TEMPLATE "{safe_tpl}";',
    )
    if exit_code != 0:
        msg = (
            f"Failed to clone template database {safe_tpl!r} into {safe_worker_db!r}: "
            f"{output.decode(errors='replace').strip()}"
        )
        raise RuntimeError(msg)
    exit_code, output = exec_psql(
        service.binaries,
        user=service.user,
        password=service.password,
        database="postgres",
        host=service.host,
        port=service.port,
        sql=f'ALTER DATABASE "{safe_worker_db}" WITH allow_connections = true;',
    )
    if exit_code != 0:
        msg = (
            f"Failed to alter cloned database {safe_worker_db!r}: "
            f"{output.decode(errors='replace').strip()}"
        )
        raise RuntimeError(msg)
    exit_code, output = exec_psql(
        service.binaries,
        user=service.user,
        password=service.password,
        database=safe_worker_db,
        host=service.host,
        port=service.port,
        sql="SELECT 1",
        tuples_only=True,
    )
    if exit_code != 0 or output.strip() != b"1":
        msg = f"Verification SELECT against cloned worker database {safe_worker_db!r} failed: {output.decode(errors='replace').strip()}"
        raise RuntimeError(msg)
    return safe_worker_db


def sweep_worker_databases(
    service: EmbeddedPostgresService,
    *,
    prefix: str = "pytest_databases_",
) -> list[str]:
    """Terminate backends and drop transient worker databases matching ``prefix`` while preserving templates.

    Args:
        service: Connected EmbeddedPostgresService instance.
        prefix: Database name prefix to match for worker databases.

    Returns:
        List of dropped database names.
    """
    query = (
        f"SELECT datname FROM pg_database WHERE datname LIKE '{prefix}%' "
        "AND datistemplate = false AND datallowconn = true;"
    )
    exit_code, output = exec_psql(
        service.binaries,
        user=service.user,
        password=service.password,
        database="postgres",
        host=service.host,
        port=service.port,
        sql=query,
        tuples_only=True,
    )
    if exit_code != 0:
        return []
    dropped: list[str] = []
    lines = [line.strip().decode("utf-8") for line in output.splitlines() if line.strip()]
    for db_name in lines:
        if db_name and IDENTIFIER_PATTERN.fullmatch(db_name):
            drop_database_force(service, db_name=db_name)
            dropped.append(db_name)
    return dropped


def _find_free_port() -> int:
    """Find an available ephemeral port on the loopback interface."""
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.bind(("127.0.0.1", 0))
        sock.listen(1)
        return int(sock.getsockname()[1])


def _check_socket_ready(host: str, port: int, timeout: float = 1.0) -> bool:
    """Probe a TCP socket for readiness."""
    try:
        with socket.create_connection((host, port), timeout=timeout):
            return True
    except OSError:
        return False


def init_cluster(
    binaries: PostgresBinaries,
    data_dir: Path,
    *,
    user: str = "postgres",
) -> None:
    """Initialize a fast ephemeral PostgreSQL database cluster."""
    data_dir.mkdir(parents=True, exist_ok=True)
    if (data_dir / "PG_VERSION").exists():
        return

    cmd = [
        str(binaries.initdb),
        "-D",
        str(data_dir),
        "-U",
        user,
        "--auth=trust",
        "--auth-host=trust",
        "--auth-local=trust",
        "--no-sync",
        "--encoding=UTF8",
    ]
    result = subprocess.run(
        cmd,
        capture_output=True,
        check=False,
    )
    if result.returncode != 0:
        msg = f"initdb failed on {data_dir}: {result.stderr.decode(errors='replace').strip()}"
        raise RuntimeError(msg)

    conf_path = data_dir / "postgresql.conf"
    tuning = (
        "\n# pytest-databases fast in-memory execution parameters\n"
        "fsync = off\n"
        "synchronous_commit = off\n"
        "full_page_writes = off\n"
        "shared_buffers = 32MB\n"
        "max_connections = 100\n"
    )
    with conf_path.open("a", encoding="utf-8") as conf_file:
        conf_file.write(tuning)


def start_cluster(
    binaries: PostgresBinaries,
    data_dir: Path,
    *,
    host: str = "127.0.0.1",
    port: int = 0,
    user: str = "postgres",
    unix_socket_dir: Path | None = None,
    startup_timeout: float = 15.0,
) -> tuple[subprocess.Popen[bytes], int]:
    """Start an embedded PostgreSQL server daemon and await SQL readiness."""
    socket_dir_arg = str(unix_socket_dir) if unix_socket_dir is not None else ""
    max_attempts = 3 if port == 0 else 1

    for attempt in range(max_attempts):
        allocated_port = port if port > 0 else _find_free_port()
        cmd = [
            str(binaries.postgres),
            "-D",
            str(data_dir),
            "-h",
            host,
            "-p",
            str(allocated_port),
            "-k",
            socket_dir_arg,
        ]

        process = subprocess.Popen(
            cmd,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )

        deadline = time.monotonic() + startup_timeout
        port_bind_failed = False
        while time.monotonic() < deadline:
            if process.poll() is not None:
                if attempt < max_attempts - 1 and port == 0:
                    port_bind_failed = True
                    break
                msg = f"PostgreSQL daemon terminated prematurely with code {process.returncode}"
                raise RuntimeError(msg)
            if _check_socket_ready(host, allocated_port, timeout=0.2):
                exit_code, output = exec_psql(
                    binaries,
                    user=user,
                    password="",
                    database="postgres",
                    host=host,
                    port=allocated_port,
                    sql="SELECT 1",
                    tuples_only=True,
                    timeout=1.0,
                )
                if exit_code == 0 and output.strip() == b"1":
                    return process, allocated_port
            time.sleep(0.1)

        if port_bind_failed:
            continue

        with contextlib.suppress(Exception):
            process.terminate()
            process.wait(timeout=2.0)
        msg = f"Embedded PostgreSQL on {host}:{allocated_port} failed to become responsive within {startup_timeout}s"
        raise TimeoutError(msg)

    msg = f"Embedded PostgreSQL failed to start after {max_attempts} attempts"
    raise RuntimeError(msg)


def stop_cluster(
    binaries: PostgresBinaries,
    data_dir: Path,
    process: subprocess.Popen[bytes] | None = None,
    timeout: float = 5.0,
) -> None:
    """Terminate the embedded PostgreSQL cluster cleanly."""
    if binaries.pg_ctl.is_file():
        cmd = [str(binaries.pg_ctl), "stop", "-D", str(data_dir), "-m", "immediate"]
        with contextlib.suppress(Exception):
            subprocess.run(cmd, capture_output=True, timeout=timeout, check=False)

    if process is not None and process.poll() is None:
        with contextlib.suppress(Exception):
            process.terminate()
            process.wait(timeout=timeout)
        if process.poll() is None:
            with contextlib.suppress(Exception):
                process.kill()


@contextmanager
def provide_embedded_postgres_service(
    *,
    data_dir: Path | str | None = None,
    bin_dir: Path | str | None = None,
    host: str = "127.0.0.1",
    port: int = 0,
    user: str = "postgres",
    password: str = "",
    database: str = "postgres",
    cleanup_mode: Literal["delete", "keep"] = "delete",
    timeout: float = 15.0,
) -> Generator[EmbeddedPostgresService, None, None]:
    """Context manager provisioning a local embedded PostgreSQL server.

    Args:
        data_dir: Optional explicit directory for cluster data.
        bin_dir: Optional explicit directory containing PostgreSQL server binaries.
        host: Hostname or IP to bind (defaults to "127.0.0.1").
        port: Port to bind (0 for dynamic assignment).
        user: Database superuser name (defaults to "postgres").
        password: Database password.
        database: Default database name (defaults to "postgres").
        cleanup_mode: "delete" to wipe data_dir on teardown, "keep" to preserve it.
        timeout: Server startup readiness timeout in seconds.

    Yields:
        EmbeddedPostgresService: Connected and verified embedded service instance.
    """
    binaries = resolve_postgres_binaries(bin_dir)
    temporary_dir: tempfile.TemporaryDirectory[str] | None = None
    target_data_dir: Path

    if data_dir is not None:
        target_data_dir = Path(data_dir)
    else:
        temporary_dir = tempfile.TemporaryDirectory(prefix="pytest_databases_pg_")
        target_data_dir = Path(temporary_dir.name)

    init_cluster(binaries, target_data_dir, user=user)
    process, allocated_port = start_cluster(
        binaries,
        target_data_dir,
        host=host,
        port=port,
        user=user,
        startup_timeout=timeout,
    )

    if database != "postgres":
        exit_code, output = exec_psql(
            binaries,
            user=user,
            password=password,
            database="postgres",
            host=host,
            port=allocated_port,
            sql=f'CREATE DATABASE "{_validate_identifier(database)}";',
        )
        if exit_code != 0:
            stop_cluster(binaries, target_data_dir, process)
            msg = f"Failed to create database {database!r}: {output.decode(errors='replace').strip()}"
            raise RuntimeError(msg)

    service = EmbeddedPostgresService(
        host=host,
        port=allocated_port,
        user=user,
        password=password,
        database=database,
        data_dir=target_data_dir,
        binaries=binaries,
        process=process,
    )

    cleanup_handler = atexit.register(stop_cluster, binaries, target_data_dir, process)

    try:
        yield service
    finally:
        atexit.unregister(cleanup_handler)
        stop_cluster(binaries, target_data_dir, process)
        if cleanup_mode == "delete" and temporary_dir is not None:
            with contextlib.suppress(Exception):
                temporary_dir.cleanup()


@pytest.fixture(scope="session")
def embedded_postgres_user() -> str:
    """Default superuser name for embedded PostgreSQL."""
    return "postgres"


@pytest.fixture(scope="session")
def embedded_postgres_password() -> str:
    """Default superuser password for embedded PostgreSQL."""
    return ""


@pytest.fixture(scope="session")
def embedded_postgres_database() -> str:
    """Default initial database name for embedded PostgreSQL."""
    return "pytest_databases"


@pytest.fixture(scope="session")
def embedded_postgres_port() -> int:
    """Default port for embedded PostgreSQL (0 indicates dynamic allocation)."""
    return 0


@pytest.fixture(scope="session")
def xdist_embedded_postgres_isolation_level() -> XdistIsolationLevel:
    """Default isolation strategy for embedded PostgreSQL under pytest-xdist."""
    return "template"


@pytest.fixture(scope="session")
def embedded_postgres_template_name() -> str:
    """Default template database name for embedded PostgreSQL template acceleration."""
    return "pytest_databases_template"


@pytest.fixture(scope="session")
def embedded_postgres_template_setup() -> Callable[[EmbeddedPostgresService], Any] | None:
    """Optional hook invoked once per test session to provision the base template database."""
    return None


@pytest.fixture(scope="session")
def embedded_postgres_template_lock_dir() -> Path | None:
    """Optional lock directory override for coordinating cross-worker template builds."""
    return None


def _read_active_cluster_metadata(json_file: Path) -> dict[str, Any] | None:
    """Read cluster state and verify server responsiveness."""
    if not json_file.is_file():
        return None
    try:
        data = json.loads(json_file.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return None

    pid = data.get("pid")
    port = data.get("port")
    host = data.get("host", "127.0.0.1")
    if not isinstance(port, int):
        return None

    if isinstance(pid, int):
        with contextlib.suppress(OSError):
            os.kill(pid, 0)
    if _check_socket_ready(host, port, timeout=0.5):
        return data
    return None


def _provision_shared_cluster(
    shared_dir: Path,
    *,
    user: str,
    password: str,
    database: str,
    port: int,
) -> dict[str, Any]:
    """Initialize, launch, and register a single shared PostgreSQL cluster for xdist workers."""
    binaries = resolve_postgres_binaries()
    data_dir = shared_dir / "embedded_postgres_data"
    init_cluster(binaries, data_dir, user=user)
    process, allocated_port = start_cluster(
        binaries,
        data_dir,
        host="127.0.0.1",
        port=port,
        user=user,
        startup_timeout=30.0,
    )
    if database != "postgres":
        exec_psql(
            binaries,
            user=user,
            password=password,
            database="postgres",
            host="127.0.0.1",
            port=allocated_port,
            sql=f'CREATE DATABASE "{_validate_identifier(database)}";',
        )
    return {
        "host": "127.0.0.1",
        "port": allocated_port,
        "user": user,
        "password": password,
        "database": database,
        "data_dir": str(data_dir),
        "pid": process.pid,
    }


def _cleanup_shared_cluster(
    shared_dir: Path,
    lock_file: Path,
    json_file: Path,
) -> None:
    """Stop the shared cluster if all active worker markers are gone."""
    with filelock.FileLock(str(lock_file), timeout=60.0):
        remaining = list(shared_dir.glob("embedded_postgres_worker_*.active"))
        if remaining or not json_file.is_file():
            return
        data: dict[str, Any] = {}
        with contextlib.suppress(json.JSONDecodeError, OSError):
            data = json.loads(json_file.read_text(encoding="utf-8"))

        pid = data.get("pid")
        data_dir_str = data.get("data_dir")
        if isinstance(pid, int):
            with contextlib.suppress(OSError):
                os.kill(pid, 15)
        if data_dir_str is not None:
            with contextlib.suppress(Exception):
                stop_cluster(resolve_postgres_binaries(), Path(data_dir_str), None)

        with contextlib.suppress(FileNotFoundError):
            json_file.unlink()


@pytest.fixture(scope="session")
def embedded_postgres_service(
    request: pytest.FixtureRequest,
    tmp_path_factory: pytest.TempPathFactory,
    embedded_postgres_user: str,
    embedded_postgres_password: str,
    embedded_postgres_database: str,
    embedded_postgres_port: int,
    xdist_embedded_postgres_isolation_level: XdistIsolationLevel,
    embedded_postgres_template_name: str,
    embedded_postgres_template_setup: Callable[[EmbeddedPostgresService], Any] | None,
    embedded_postgres_template_lock_dir: Path | None,
) -> Generator[EmbeddedPostgresService, None, None]:
    """Session-scoped embedded PostgreSQL service fixture with multi-worker isolation support.

    Yields:
        EmbeddedPostgresService: Connected and verified service instance.
    """
    worker_id = get_xdist_worker_id()
    worker_num = get_xdist_worker_num()
    is_shared = worker_id is not None and xdist_embedded_postgres_isolation_level in {"template", "database"}

    if not is_shared:
        with provide_embedded_postgres_service(
            host="127.0.0.1",
            port=embedded_postgres_port,
            user=embedded_postgres_user,
            password=embedded_postgres_password,
            database=embedded_postgres_database,
        ) as service:
            yield service
        return

    shared_dir = tmp_path_factory.getbasetemp().parent
    lock_file = shared_dir / "embedded_postgres_cluster.lock"
    json_file = shared_dir / "embedded_postgres_cluster.json"
    active_worker = shared_dir / f"embedded_postgres_worker_{worker_id}.active"
    active_worker.touch()

    with filelock.FileLock(str(lock_file), timeout=180.0):
        metadata = _read_active_cluster_metadata(json_file)
        if metadata is None:
            metadata = _provision_shared_cluster(
                shared_dir,
                user=embedded_postgres_user,
                password=embedded_postgres_password,
                database=embedded_postgres_database,
                port=embedded_postgres_port,
            )
            json_file.write_text(json.dumps(metadata), encoding="utf-8")

    service = EmbeddedPostgresService(
        host=metadata["host"],
        port=metadata["port"],
        user=metadata["user"],
        password=metadata["password"],
        database=metadata["database"],
        data_dir=Path(metadata["data_dir"]),
        binaries=resolve_postgres_binaries(),
        process=None,
    )

    worker_suffix = str(worker_num) if worker_num is not None else (worker_id or "0")
    worker_db = f"{embedded_postgres_database}_{worker_suffix}"

    if xdist_embedded_postgres_isolation_level == "template":
        service.ensure_template(
            embedded_postgres_template_name,
            setup_fn=embedded_postgres_template_setup,
            lock_dir=embedded_postgres_template_lock_dir or shared_dir,
        )
        service.create_worker_database_from_template(
            embedded_postgres_template_name,
            worker_db=worker_db,
        )
        worker_service = dataclasses.replace(service, database=worker_db)
    elif xdist_embedded_postgres_isolation_level == "database":
        drop_database_force(service, db_name=worker_db)
        exit_code, output = service.exec_psql(f'CREATE DATABASE "{worker_db}";', database="postgres")
        if exit_code != 0:
            msg = f"Failed to create worker database {worker_db!r}: {output.decode(errors='replace').strip()}"
            raise RuntimeError(msg)
        worker_service = dataclasses.replace(service, database=worker_db)
    else:
        worker_service = service

    try:
        yield worker_service
    finally:
        with contextlib.suppress(FileNotFoundError):
            active_worker.unlink()
        _cleanup_shared_cluster(shared_dir, lock_file, json_file)
