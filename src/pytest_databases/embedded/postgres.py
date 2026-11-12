"""Embedded PostgreSQL service that runs local ``initdb`` / ``postgres`` binaries without a container runtime.

Binaries come from an explicit directory, ``PG_BIN_DIR``, the ``pgembed`` or ``pgserver`` packages (the
``embedded-postgres`` extra), the ``PATH``, ``pg_config --bindir``, or common system locations. The cluster uses
``trust`` authentication on a loopback TCP port with Unix sockets disabled, and SQL runs over the PostgreSQL wire
protocol, so neither ``psql`` nor a Python driver is required.
"""

from __future__ import annotations

import atexit
import contextlib
import dataclasses
import functools
import importlib
import json
import os
import re
import shutil
import signal
import socket
import subprocess
import tempfile
import time
from contextlib import contextmanager
from pathlib import Path
from typing import TYPE_CHECKING, Any, Literal

import filelock
import pytest

from pytest_databases._service import resolve_postgres_backend
from pytest_databases.embedded._pgwire import run_simple_query
from pytest_databases.helpers import (
    DEFAULT_TEMPLATE_NAME,
    PostgresTemplateSupport,
    get_xdist_worker_id,
    get_xdist_worker_num,
    make_connection_string,
    read_init_scripts,
    split_template_setup,
    tcp_port_open,
    validate_identifier,
)
from pytest_databases.types import PostgresServiceProtocol

if TYPE_CHECKING:
    from collections.abc import Callable, Generator, Sequence

    from pytest_databases.types import PostgresXdistIsolationLevel

__all__ = (
    "EmbeddedPostgresService",
    "PostgresBinaries",
    "PostgresServiceProtocol",
    "embedded_postgres_bin_dir",
    "embedded_postgres_database",
    "embedded_postgres_port",
    "embedded_postgres_service",
    "embedded_postgres_template_fingerprint_sources",
    "embedded_postgres_template_lock_dir",
    "embedded_postgres_template_name",
    "embedded_postgres_template_setup",
    "embedded_postgres_user",
    "init_cluster",
    "postgres_any_service",
    "provide_default_embedded_postgres_session",
    "provide_embedded_postgres_service",
    "resolve_postgres_binaries",
    "start_cluster",
    "stop_cluster",
    "xdist_embedded_postgres_isolation_level",
)

_PACKAGE_BIN_MODULES = ("pgembed._commands", "pgembed", "pgserver._commands", "pgserver.postgres_server", "pgserver")
_SYSTEM_BIN_GLOBS = (
    ("/usr/lib/postgresql", "*/bin"),
    ("/opt/homebrew/opt", "postgresql@*/bin"),
    ("/usr/local/opt", "postgresql@*/bin"),
    ("/usr", "pgsql-*/bin"),
)
_LOG_TAIL_LINES = 20
_SHARED_STATE_PREFIX = "embedded_postgres"


@dataclasses.dataclass(frozen=True)
class PostgresBinaries:
    """Paths to the local PostgreSQL server binaries.

    ``pg_ctl`` is optional; without it the server is stopped with signals.
    """

    initdb: Path
    postgres: Path
    pg_ctl: Path | None = None

    @classmethod
    def from_directory(cls, directory: Path) -> PostgresBinaries | None:
        """Return the binaries in ``directory``, or None when ``initdb`` or ``postgres`` is missing.

        Returns:
            The discovered binaries or None.
        """
        initdb = directory / "initdb"
        postgres = directory / "postgres"
        if not (_is_executable(initdb) and _is_executable(postgres)):
            return None
        pg_ctl = directory / "pg_ctl"
        return cls(initdb=initdb, postgres=postgres, pg_ctl=pg_ctl if _is_executable(pg_ctl) else None)


@dataclasses.dataclass
class EmbeddedPostgresService(PostgresTemplateSupport):
    """Connection metadata and helpers for an embedded PostgreSQL server.

    The cluster defaults to ``trust`` authentication with an empty ``password``. Template helpers
    (:meth:`ensure_template`, :meth:`create_worker_database_from_template`, :meth:`sweep_worker_databases`,
    :meth:`clone_template_database`, :meth:`drop_database_force`) behave as on the container service.
    """

    host: str
    port: int
    user: str
    database: str
    data_dir: Path
    binaries: PostgresBinaries
    process: subprocess.Popen[bytes] | None = None
    password: str = ""

    @property
    def dsn(self) -> str:
        """Libpq connection string for this database.

        Returns:
            The connection string.
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
        """Driver keyword arguments: ``host``, ``port``, ``user``, ``database``, and optional ``password``.

        Returns:
            The connection parameters.
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
        """Run ``sql`` against ``database`` (defaults to this service's database).

        Output mirrors ``psql -tA``; exit code ``1`` is an SQL error and ``2`` a connection failure.

        Returns:
            The exit code and output bytes.
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
        """Run ``sql`` against ``database``; output is always tuples-only.

        Returns:
            The exit code and output bytes.
        """
        return self.exec_sql(sql, database=database, tuples_only=tuples_only)


def resolve_postgres_binaries(bin_dir: Path | str | None = None) -> PostgresBinaries:
    """Find ``initdb`` and ``postgres`` (and ``pg_ctl`` when present).

    Search order: ``bin_dir``, ``PG_BIN_DIR``, the ``pgembed`` / ``pgserver`` packages, the ``PATH``,
    ``pg_config --bindir``, then common system install directories. A candidate missing either required binary is
    skipped.

    Returns:
        The discovered binaries.

    Raises:
        RuntimeError: If ``bin_dir`` lacks the binaries, or no candidate has them.
    """
    if bin_dir is not None:
        explicit = PostgresBinaries.from_directory(Path(bin_dir))
        if explicit is None:
            msg = f"PostgreSQL server binaries ('initdb', 'postgres') were not found in {bin_dir}."
            raise RuntimeError(msg)
        return explicit
    for candidate in _candidate_bin_dirs():
        discovered = PostgresBinaries.from_directory(candidate)
        if discovered is not None:
            return discovered
    msg = (
        "PostgreSQL server binaries ('initdb', 'postgres') were not found. Install the 'embedded-postgres' extra "
        "(pip install 'pytest-databases[embedded-postgres]'), put PostgreSQL on PATH, or set PG_BIN_DIR."
    )
    raise RuntimeError(msg)


def init_cluster(binaries: PostgresBinaries, data_dir: Path, *, user: str = "postgres") -> None:
    """Run ``initdb`` with trust authentication and append fast, non-durable settings.

    An existing cluster (``PG_VERSION`` present) is left alone.

    Raises:
        RuntimeError: If ``initdb`` fails.
    """
    data_dir.mkdir(parents=True, exist_ok=True)
    if (data_dir / "PG_VERSION").exists():
        return
    result = subprocess.run(
        [str(binaries.initdb), "-D", str(data_dir), "-U", user, "--auth=trust", "--no-sync", "--encoding=UTF8"],
        capture_output=True,
        check=False,
    )
    if result.returncode != 0:
        msg = f"initdb failed on {data_dir}: {result.stderr.decode(errors='replace').strip()}"
        raise RuntimeError(msg)
    with (data_dir / "postgresql.conf").open("a", encoding="utf-8") as conf_file:
        conf_file.write(
            "\nfsync = off\nsynchronous_commit = off\nfull_page_writes = off\nshared_buffers = 32MB\n"
            "max_connections = 100\n"
        )


def start_cluster(
    binaries: PostgresBinaries,
    data_dir: Path,
    *,
    host: str = "127.0.0.1",
    port: int = 0,
    user: str = "postgres",
    startup_timeout: float = 15.0,
) -> tuple[subprocess.Popen[bytes], int]:
    """Start ``postgres`` on ``host:port`` (a free port when ``port`` is 0) and wait for ``SELECT 1``.

    Unix sockets are disabled (``-k ""``). With a dynamic port, a server that exits during startup (usually a port
    race) is retried on a new port up to three times. The server log is ``data_dir/postgresql.log``.

    Returns:
        The server process and its port.

    Raises:
        RuntimeError: If the server exits during startup.
        TimeoutError: If the server does not answer within ``startup_timeout``; the message carries the last query
            result and the log tail.
    """
    attempts = 3 if port == 0 else 1
    log_file = data_dir / "postgresql.log"
    for attempt in range(attempts):
        allocated_port = port or _find_free_port(host)
        with log_file.open("ab") as log_fp:
            process = subprocess.Popen(
                [str(binaries.postgres), "-D", str(data_dir), "-h", host, "-p", str(allocated_port), "-k", ""],
                stdout=subprocess.DEVNULL,
                stderr=log_fp,
            )
        last_result: tuple[int, bytes] = (-1, b"server port not open yet")
        deadline = time.monotonic() + startup_timeout
        while time.monotonic() < deadline:
            if process.poll() is not None:
                break
            if tcp_port_open(host, allocated_port, timeout=0.2):
                last_result = run_simple_query(
                    host, allocated_port, user=user, database="postgres", sql="SELECT 1", timeout=2.0
                )
                if last_result == (0, b"1"):
                    return process, allocated_port
            time.sleep(0.1)
        else:
            _terminate(process, timeout=5.0)
            msg = (
                f"Embedded PostgreSQL on {host}:{allocated_port} did not answer SELECT 1 within {startup_timeout}s "
                f"(last result: exit {last_result[0]}, {last_result[1].decode(errors='replace').strip()!r}). "
                f"Log tail:\n{_log_tail(log_file)}"
            )
            raise TimeoutError(msg)
        if attempt < attempts - 1:
            continue
        msg = f"Embedded PostgreSQL exited with code {process.returncode} during startup. Log tail:\n{_log_tail(log_file)}"
        raise RuntimeError(msg)
    msg = "Embedded PostgreSQL did not start"
    raise RuntimeError(msg)


def stop_cluster(
    binaries: PostgresBinaries,
    data_dir: Path,
    process: subprocess.Popen[bytes] | None = None,
    timeout: float = 10.0,
) -> None:
    """Stop the server for ``data_dir`` with a fast shutdown and reap ``process`` when given.

    Uses ``pg_ctl stop -m fast`` when available, otherwise ``SIGINT`` to the postmaster (``process`` or the PID in
    ``postmaster.pid``), escalating to ``SIGKILL`` after ``timeout`` seconds.
    """
    if binaries.pg_ctl is not None and (data_dir / "postmaster.pid").exists():
        with contextlib.suppress(OSError, subprocess.SubprocessError):
            subprocess.run(
                [str(binaries.pg_ctl), "stop", "-D", str(data_dir), "-m", "fast", "-w", "-t", str(int(timeout))],
                capture_output=True,
                timeout=timeout + 5,
                check=False,
            )
    if process is not None:
        _terminate(process, timeout=timeout)
        return
    pid = _postmaster_pid(data_dir)
    if pid is None:
        return
    with contextlib.suppress(ProcessLookupError, PermissionError):
        os.kill(pid, signal.SIGINT)
    deadline = time.monotonic() + timeout
    while (data_dir / "postmaster.pid").exists() and time.monotonic() < deadline:
        time.sleep(0.1)
    if (data_dir / "postmaster.pid").exists():
        with contextlib.suppress(ProcessLookupError, PermissionError):
            os.kill(pid, signal.SIGKILL)


@contextmanager
def provide_embedded_postgres_service(
    *,
    data_dir: Path | str | None = None,
    bin_dir: Path | str | None = None,
    binaries: PostgresBinaries | None = None,
    host: str = "127.0.0.1",
    port: int = 0,
    user: str = "postgres",
    password: str = "",
    database: str = "postgres",
    cleanup_mode: Literal["delete", "keep"] = "delete",
    timeout: float = 15.0,
    init_sql: str | Path | Sequence[str | Path] | None = None,
) -> Generator[EmbeddedPostgresService, None, None]:
    """Start a private embedded PostgreSQL cluster for the duration of the context.

    Args:
        data_dir: Cluster directory; an existing cluster is reused and never deleted. None creates a temporary one.
        bin_dir: Directory holding ``initdb`` / ``postgres``; ignored when ``binaries`` is given.
        binaries: Already resolved binaries.
        host: Loopback address to listen on.
        port: TCP port, or 0 for a free port.
        user: Superuser created by ``initdb`` (trust authentication by default).
        password: Role password attached to :class:`EmbeddedPostgresService` (empty string for trust auth).
        database: Database to create and return; ``"postgres"`` uses the default database.
        cleanup_mode: ``"delete"`` removes the temporary ``data_dir`` on exit, ``"keep"`` leaves it for inspection.
        timeout: Seconds to wait for the server to answer.
        init_sql: Optional SQL statement, ``.sql`` path, or sequence executed directly against ``database``.

    Yields:
        The running service.
    """
    resolved = binaries or resolve_postgres_binaries(bin_dir)
    temporary_dir = None if data_dir is not None else Path(tempfile.mkdtemp(prefix="pytest_databases_pg_"))
    target_dir = Path(data_dir) if data_dir is not None else temporary_dir
    try:
        if target_dir is None:
            msg = "data_dir could not be determined"
            raise RuntimeError(msg)
        init_cluster(resolved, target_dir, user=user)
        process, allocated_port = start_cluster(
            resolved, target_dir, host=host, port=port, user=user, startup_timeout=timeout
        )
        stop_handler = functools.partial(stop_cluster, resolved, target_dir, process)
        atexit.register(stop_handler)
        try:
            service = EmbeddedPostgresService(
                host=host,
                port=allocated_port,
                user=user,
                database=database,
                data_dir=target_dir,
                binaries=resolved,
                process=process,
                password=password,
            )
            if database != "postgres":
                _create_database(service, database)
            _apply_embedded_init_sql(service, init_sql=init_sql)
            yield service
        finally:
            atexit.unregister(stop_handler)
            stop_handler()
    finally:
        if temporary_dir is not None and cleanup_mode == "delete":
            shutil.rmtree(temporary_dir, ignore_errors=True)


@pytest.fixture(scope="session")
def embedded_postgres_user() -> str:
    """Return the superuser name (trust authentication, no password)."""
    return "postgres"


@pytest.fixture(scope="session")
def embedded_postgres_database() -> str:
    """Return the base name of the database the service yields (``<name>_<worker>`` under xdist)."""
    return "pytest_databases"


@pytest.fixture(scope="session")
def embedded_postgres_port() -> int:
    """Return the server port (0 picks a free port)."""
    return 0


@pytest.fixture(scope="session")
def embedded_postgres_bin_dir() -> Path | str | None:
    """Return a directory holding ``initdb`` / ``postgres`` (None searches the usual locations)."""
    return None


@pytest.fixture(scope="session")
def xdist_embedded_postgres_isolation_level() -> PostgresXdistIsolationLevel:
    """Return the isolation level: ``"template"`` (default), ``"database"``, or ``"server"``."""
    return "template"


@pytest.fixture(scope="session")
def embedded_postgres_template_name() -> str | None:
    """Return the template name prefix (None means ``"pytest_databases_template"``)."""
    return None


@pytest.fixture(scope="session")
def embedded_postgres_template_setup() -> (
    Callable[[EmbeddedPostgresService], object] | str | Path | Sequence[str | Path] | None
):
    """Return the template setup: a callable receiving the staging service, or SQL statements / ``.sql`` paths."""
    return None


@pytest.fixture(scope="session")
def embedded_postgres_template_fingerprint_sources() -> Sequence[str | bytes | Path]:
    """Return extra strings, bytes, files, or directories folded into the template name digest."""
    return ()


@pytest.fixture(scope="session")
def embedded_postgres_template_lock_dir() -> Path | str | None:
    """Return the directory for template lock files (None means the system temp directory)."""
    return None


@pytest.fixture(scope="session")
def embedded_postgres_service(
    tmp_path_factory: pytest.TempPathFactory,
    embedded_postgres_user: str,
    embedded_postgres_database: str,
    embedded_postgres_port: int,
    embedded_postgres_bin_dir: Path | str | None,
    xdist_embedded_postgres_isolation_level: PostgresXdistIsolationLevel,
    embedded_postgres_template_name: str | None,
    embedded_postgres_template_setup: Callable[[EmbeddedPostgresService], object]
    | str
    | Path
    | Sequence[str | Path]
    | None,
    embedded_postgres_template_fingerprint_sources: Sequence[str | bytes | Path],
    embedded_postgres_template_lock_dir: Path | str | None,
) -> Generator[EmbeddedPostgresService, None, None]:
    """Provide an embedded PostgreSQL service.

    Without xdist, or with ``"server"`` isolation, each process starts its own cluster. Under xdist with
    ``"template"`` or ``"database"`` isolation, workers share one cluster and each gets its own database. With
    ``"template"`` the database is cloned from a template built once from ``embedded_postgres_template_setup``.

    Yields:
        The service pointed at this process's database.
    """
    isolation = xdist_embedded_postgres_isolation_level
    worker_id = get_xdist_worker_id()
    worker_num = get_xdist_worker_num()
    db_name = embedded_postgres_database
    if worker_num is not None and isolation != "server":
        db_name = f"{db_name}_{worker_num}"
    binaries = resolve_postgres_binaries(embedded_postgres_bin_dir)
    prepare = functools.partial(
        _prepare_database,
        db_name=db_name,
        isolation=isolation,
        template_name=embedded_postgres_template_name or DEFAULT_TEMPLATE_NAME,
        template_setup=embedded_postgres_template_setup,
        fingerprint_sources=embedded_postgres_template_fingerprint_sources,
        lock_dir=embedded_postgres_template_lock_dir,
    )
    if worker_id is None or isolation == "server":
        with provide_embedded_postgres_service(
            binaries=binaries, port=embedded_postgres_port, user=embedded_postgres_user
        ) as admin:
            yield prepare(admin)
        return
    with _SharedCluster(
        tmp_path_factory.getbasetemp().parent,
        worker_id=worker_id,
        binaries=binaries,
        user=embedded_postgres_user,
        port=embedded_postgres_port,
    ) as admin:
        try:
            yield prepare(admin)
        finally:
            with contextlib.suppress(RuntimeError):
                admin.drop_database_force(db_name)


def _is_fixture_registered(request: pytest.FixtureRequest, name: str) -> bool:
    """Return whether pytest has registered a fixture named ``name`` for the current node."""
    return bool(request.session._fixturemanager.getfixturedefs(name, request.node))


def _fixture_or_default(request: pytest.FixtureRequest, name: str, default: Any) -> Any:
    """Return registered fixture value for ``name`` or ``default`` when absent."""
    if _is_fixture_registered(request, name):
        return request.getfixturevalue(name)
    return default


@contextmanager
def provide_default_embedded_postgres_session(
    request: pytest.FixtureRequest,
    tmp_path_factory: pytest.TempPathFactory,
) -> Generator[EmbeddedPostgresService, None, None]:
    """Yield ``embedded_postgres_service`` if registered, else provision an xdist-safe embedded session cluster.

    Yields:
        Active :class:`EmbeddedPostgresService` pointed at the worker database.
    """
    if _is_fixture_registered(request, "embedded_postgres_service"):
        yield request.getfixturevalue("embedded_postgres_service")
        return

    binaries = resolve_postgres_binaries(_fixture_or_default(request, "embedded_postgres_bin_dir", None))
    user: str = _fixture_or_default(request, "embedded_postgres_user", "postgres")
    database: str = _fixture_or_default(request, "embedded_postgres_database", "pytest_databases")
    port: int = _fixture_or_default(request, "embedded_postgres_port", 0)
    isolation: PostgresXdistIsolationLevel = _fixture_or_default(
        request, "xdist_embedded_postgres_isolation_level", "template"
    )
    template_name: str = _fixture_or_default(request, "embedded_postgres_template_name", None) or DEFAULT_TEMPLATE_NAME
    template_setup = _fixture_or_default(request, "embedded_postgres_template_setup", None)
    fingerprint_sources = _fixture_or_default(request, "embedded_postgres_template_fingerprint_sources", ())
    lock_dir = _fixture_or_default(request, "embedded_postgres_template_lock_dir", None)
    worker_id = get_xdist_worker_id()
    worker_num = get_xdist_worker_num()
    db_name = f"{database}_{worker_num}" if (worker_num is not None and isolation != "server") else database

    if worker_id is None or isolation == "server":
        with provide_embedded_postgres_service(
            data_dir=tmp_path_factory.mktemp("embedded_postgres"),
            binaries=binaries,
            port=port,
            user=user,
            database="postgres",
            timeout=30.0,
        ) as admin:
            yield _prepare_database(
                admin,
                db_name=db_name,
                isolation=isolation,
                template_name=template_name,
                template_setup=template_setup,
                fingerprint_sources=fingerprint_sources,
                lock_dir=lock_dir,
            )
        return

    shared_dir = tmp_path_factory.getbasetemp().parent
    with _SharedCluster(shared_dir, worker_id=worker_id, binaries=binaries, user=user, port=port) as admin:
        try:
            yield _prepare_database(
                admin,
                db_name=db_name,
                isolation=isolation,
                template_name=template_name,
                template_setup=template_setup,
                fingerprint_sources=fingerprint_sources,
                lock_dir=lock_dir or shared_dir,
            )
        finally:
            with contextlib.suppress(RuntimeError):
                admin.drop_database_force(db_name)


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
        with provide_default_embedded_postgres_session(request, tmp_path_factory) as service:
            yield service
        return
    docker_pg_module = importlib.import_module("pytest_databases.docker.postgres")
    with docker_pg_module.provide_default_postgres_session(request) as service:
        yield service


class _SharedCluster:
    """One cluster shared by xdist workers and stopped by the last worker to leave.

    Each worker holds a marker file while it uses the cluster; the cluster state (port, PID, data directory) is a
    JSON file next to the markers, guarded by a file lock. Every worker registers an ``atexit`` handler that removes
    its marker and stops the cluster when no markers remain, so an aborted worker does not orphan the server.
    """

    def __init__(self, shared_dir: Path, *, worker_id: str, binaries: PostgresBinaries, user: str, port: int) -> None:
        self._shared_dir = shared_dir
        self._binaries = binaries
        self._user = user
        self._port = port
        self._lock_file = shared_dir / f"{_SHARED_STATE_PREFIX}_cluster.lock"
        self._state_file = shared_dir / f"{_SHARED_STATE_PREFIX}_cluster.json"
        self._marker = shared_dir / f"{_SHARED_STATE_PREFIX}_worker_{worker_id}.active"
        self._process: subprocess.Popen[bytes] | None = None
        self._exit_handler = functools.partial(self._release)

    def __enter__(self) -> EmbeddedPostgresService:
        self._marker.touch()
        atexit.register(self._exit_handler)
        try:
            with filelock.FileLock(str(self._lock_file), timeout=180.0):
                state = self._read_live_state()
                if state is None:
                    state = self._provision()
                    self._state_file.write_text(json.dumps(state), encoding="utf-8")
        except BaseException:
            atexit.unregister(self._exit_handler)
            self._release()
            raise
        return EmbeddedPostgresService(
            host=state["host"],
            port=state["port"],
            user=self._user,
            database="postgres",
            data_dir=Path(state["data_dir"]),
            binaries=self._binaries,
        )

    def __exit__(self, *_exc_info: object) -> None:
        atexit.unregister(self._exit_handler)
        self._release()

    def _provision(self) -> dict[str, Any]:
        """Initialize and start the shared cluster.

        Returns:
            The cluster state written to the JSON file.
        """
        data_dir = self._shared_dir / f"{_SHARED_STATE_PREFIX}_data"
        shutil.rmtree(data_dir, ignore_errors=True)
        init_cluster(self._binaries, data_dir, user=self._user)
        process, port = start_cluster(
            self._binaries, data_dir, host="127.0.0.1", port=self._port, user=self._user, startup_timeout=30.0
        )
        self._process = process
        return {"host": "127.0.0.1", "port": port, "data_dir": str(data_dir), "pid": process.pid}

    def _read_live_state(self) -> dict[str, Any] | None:
        """Return the recorded cluster state when its postmaster is alive and answers ``SELECT 1``.

        Returns:
            The state, or None when there is no usable cluster.
        """
        try:
            state = json.loads(self._state_file.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return None
        pid, port, host = state.get("pid"), state.get("port"), state.get("host", "127.0.0.1")
        if not isinstance(pid, int) or not isinstance(port, int):
            return None
        try:
            os.kill(pid, 0)
        except ProcessLookupError:
            return None
        except PermissionError:
            pass
        probe = run_simple_query(host, port, user=self._user, database="postgres", sql="SELECT 1", timeout=2.0)
        return state if probe == (0, b"1") else None

    def _release(self) -> None:
        """Remove this worker's marker and stop the cluster if no other worker holds one."""
        with contextlib.suppress(FileNotFoundError):
            self._marker.unlink()
        with filelock.FileLock(str(self._lock_file), timeout=60.0):
            if not any(self._shared_dir.glob(f"{_SHARED_STATE_PREFIX}_worker_*.active")):
                self._stop_recorded_cluster()
        if self._process is not None and self._process.poll() is not None:
            self._process = None

    def _stop_recorded_cluster(self) -> None:
        """Stop the cluster named in the state file, delete its data directory, and remove the state file."""
        try:
            state = json.loads(self._state_file.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return
        data_dir = state.get("data_dir")
        if isinstance(data_dir, str):
            stop_cluster(self._binaries, Path(data_dir), None)
            shutil.rmtree(data_dir, ignore_errors=True)
        with contextlib.suppress(FileNotFoundError):
            self._state_file.unlink()


def _prepare_database(
    admin: EmbeddedPostgresService,
    *,
    db_name: str,
    isolation: PostgresXdistIsolationLevel,
    template_name: str,
    template_setup: Callable[[EmbeddedPostgresService], object] | str | Path | Sequence[str | Path] | None,
    fingerprint_sources: Sequence[str | bytes | Path],
    lock_dir: Path | str | None,
    init_sql: str | Path | Sequence[str | Path] | None = None,
) -> EmbeddedPostgresService:
    """Create ``db_name`` from the template (``"template"`` isolation) or empty, replacing any leftover.

    Returns:
        A copy of ``admin`` pointed at ``db_name``.
    """
    if isolation == "template":
        setup_fn, setup_sql = split_template_setup(template_setup)
        template = admin.ensure_template(
            template_name,
            setup_fn=setup_fn,
            setup_sql=setup_sql,
            init_sql=init_sql,
            fingerprint_sources=fingerprint_sources,
            lock_dir=lock_dir,
        )
        admin.create_worker_database_from_template(template, db_name)
        return dataclasses.replace(admin, database=db_name)

    admin.drop_database_force(db_name)
    _create_database(admin, db_name)
    target = dataclasses.replace(admin, database=db_name)
    _apply_embedded_init_sql(target, init_sql=init_sql)
    return target


def _apply_embedded_init_sql(
    target: EmbeddedPostgresService,
    *,
    init_sql: str | Path | Sequence[str | Path] | None,
) -> None:
    """Execute ``init_sql`` scripts sequentially against ``target``."""
    for statement in read_init_scripts(init_sql):
        exit_code, output = target.exec_sql(statement)
        if exit_code != 0:
            detail = output.decode(errors="replace").strip()
            msg = f"Embedded PostgreSQL init_sql failed on {target.database!r} (exit {exit_code}): {detail}"
            raise RuntimeError(msg)


def _create_database(service: EmbeddedPostgresService, database: str) -> None:
    """Run ``CREATE DATABASE``.

    Raises:
        RuntimeError: If the statement fails.
    """
    name = validate_identifier(database)
    exit_code, output = service.exec_sql(f'CREATE DATABASE "{name}";', database="postgres")
    if exit_code != 0:
        msg = f"Failed to create database {name!r}: {output.decode(errors='replace').strip()}"
        raise RuntimeError(msg)


def _candidate_bin_dirs() -> list[Path]:
    """List directories that may hold the PostgreSQL server binaries, in search order.

    Returns:
        The candidate directories.
    """
    candidates: list[Path] = []
    env_dir = os.environ.get("PG_BIN_DIR")
    if env_dir:
        candidates.append(Path(env_dir))
    for module_name in _PACKAGE_BIN_MODULES:
        try:
            module = importlib.import_module(module_name)
        except ImportError:
            continue
        bin_path = getattr(module, "POSTGRES_BIN_PATH", None)
        if bin_path is not None:
            candidates.append(Path(bin_path))
    which_postgres = shutil.which("postgres")
    if which_postgres is not None:
        candidates.append(Path(which_postgres).parent)
    candidates.extend(_pg_config_bin_dirs())
    for root, pattern in _SYSTEM_BIN_GLOBS:
        root_path = Path(root)
        if root_path.is_dir():
            matches = [path for path in root_path.glob(pattern) if path.is_dir()]
            candidates.extend(sorted(matches, key=_version_key, reverse=True))
    return candidates


def _pg_config_bin_dirs() -> list[Path]:
    """Return the ``pg_config --bindir`` directory when ``pg_config`` is on the PATH.

    Returns:
        Zero or one directory.
    """
    pg_config = shutil.which("pg_config")
    if pg_config is None:
        return []
    try:
        result = subprocess.run([pg_config, "--bindir"], capture_output=True, text=True, check=False, timeout=10)
    except (OSError, subprocess.SubprocessError):
        return []
    bindir = result.stdout.strip()
    return [Path(bindir)] if result.returncode == 0 and bindir else []


def _version_key(path: Path) -> list[int | str]:
    """Sort key that orders embedded version numbers numerically.

    Returns:
        The key.
    """
    return [int(part) if part.isdigit() else part for part in re.split(r"(\d+)", str(path))]


def _is_executable(path: Path) -> bool:
    """Return whether ``path`` is an executable regular file.

    Returns:
        True when executable.
    """
    return path.is_file() and os.access(path, os.X_OK)


def _find_free_port(host: str) -> int:
    """Return a port that is free on ``host`` right now.

    Returns:
        The port number.
    """
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        sock.bind((host, 0))
        return int(sock.getsockname()[1])


def _log_tail(log_file: Path) -> str:
    """Return the last lines of the server log.

    Returns:
        The log tail, or a placeholder when the log is missing.
    """
    try:
        lines = log_file.read_text(encoding="utf-8", errors="replace").splitlines()
    except OSError:
        return "<no server log>"
    return "\n".join(lines[-_LOG_TAIL_LINES:])


def _postmaster_pid(data_dir: Path) -> int | None:
    """Read the postmaster PID from ``postmaster.pid``.

    Returns:
        The PID, or None when the file is missing or malformed.
    """
    try:
        first_line = (data_dir / "postmaster.pid").read_text(encoding="utf-8").splitlines()[0]
    except (OSError, IndexError):
        return None
    return int(first_line) if first_line.strip().isdigit() else None


def _terminate(process: subprocess.Popen[bytes], *, timeout: float) -> None:
    """Stop ``process`` with ``SIGINT`` (fast shutdown), then ``SIGKILL``, and reap it."""
    if process.poll() is None:
        with contextlib.suppress(ProcessLookupError):
            process.send_signal(signal.SIGINT)
        try:
            process.wait(timeout=timeout)
        except subprocess.TimeoutExpired:
            process.kill()
            process.wait(timeout=timeout)
