"""IBM Db2 Community Edition container service fixtures and in-container CLI helpers."""

from __future__ import annotations

import contextlib
import os
import re
import shlex
import tempfile
from contextlib import contextmanager
from dataclasses import dataclass, field
from pathlib import Path
from typing import TYPE_CHECKING, NotRequired, TypedDict

import filelock
import pytest

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
    from collections.abc import Callable, Generator, Mapping, Sequence

    from docker.models.containers import Container

    from pytest_databases._service import ContainerService

__all__ = [
    "DB2_MAX_DB_NAME_LENGTH",
    "DB2_PORT",
    "DEFAULT_DB2_IMAGE",
    "DEFAULT_DB2_IPC_MODE",
    "Db2Service",
    "activate_db2_database",
    "create_worker_database",
    "db2_4k_device_support",
    "db2_activate_database",
    "db2_dbname",
    "db2_image",
    "db2_ipc_mode",
    "db2_password",
    "db2_port",
    "db2_service",
    "db2_startup_timeout",
    "db2_username",
    "db2_volumes",
    "exec_db2_sql",
    "provide_db2_service",
    "validate_db2_database_name",
    "xdist_db2_isolation_level",
]

DEFAULT_DB2_IMAGE = "icr.io/db2_community/db2:12.1.5.0"
DEFAULT_DB2_IPC_MODE = "host"
DB2_PORT = 50000
DB2_MAX_DB_NAME_LENGTH = 8
_DB2_INIT_LOCK_TIMEOUT = 300.0
_DB2_CONTAINER_LOCK_FILE = f"/{'tmp'}/pytest_databases_db2_init.lock"
_DB2_4K_REGISTRY_SETTINGS: tuple[tuple[str, str], ...] = (("DB2_4K_DEVICE_SUPPORT", "ON"), ("DB2_DIRECT_IO", "NO"))
_CLP_MAX_SUCCESS_EXIT_CODE = 3
_CLP_MAX_ACTIVATE_EXIT_CODE = 2
_DB2_NAME_PATTERN = re.compile(r"^[A-Za-z][A-Za-z0-9_]{0,7}$")
_DB2_REGISTRY_KEY_PATTERN = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")
_DB2_FALSE_VALUES = frozenset({"0", "false", "no", "off"})
_DB2_SETUP_SCRIPT = "/var/db2_setup/lib/setup_db2_instance.sh"
_DB2_SETUP_FUNCTIONS = "/var/db2_setup/include/db2_common_functions"
_DB2_4K_MISSING_DATABASE_MARKERS: tuple[str, ...] = ("SQL1013N", "SQL0293N", "42705")
_DB2_FATAL_STARTUP_MARKERS: tuple[str, ...] = ("SQL1042C", "57019")


@dataclass
class Db2Service(ServiceContainer):
    """Connection metadata and CLI helpers for an IBM Db2 container service."""

    db_name: str
    username: str
    password: str
    _lock_path: Path | None = field(default=None, repr=False, compare=False)

    @property
    def dsn(self) -> str:
        """The CLI/ODBC-style DSN string compatible with ``ibm_db.connect``."""
        return (
            f"DATABASE={self.db_name};"
            f"HOSTNAME={self.host};"
            f"PORT={self.port};"
            "PROTOCOL=TCPIP;"
            f"UID={self.username};"
            f"PWD={self.password};"
        )

    @property
    def connection_config(self) -> dict[str, str | int]:
        """Dictionary of connection parameters compatible with Db2 driver configurations."""
        return {
            "database": self.db_name,
            "hostname": self.host,
            "port": self.port,
            "protocol": "TCPIP",
            "user": self.username,
            "password": self.password,
        }

    def exec_sql(self, sql: str, *, db_name: str | None = None) -> str:
        """Execute a SQL statement inside the Db2 container without a host Python driver."""
        return exec_db2_sql(
            self.container,
            sql,
            db_name=db_name or self.db_name,
            instance_user=self.username,
        )

    def create_worker_database(self, db_name: str) -> None:
        """Create an isolated Db2 database inside the container."""
        create_worker_database(self.container, db_name, instance_user=self.username, lock_path=self._lock_path)

    def activate_database(self, db_name: str | None = None) -> str:
        """Pin ``db_name`` (defaults to ``self.db_name``) active in Db2 shared memory.

        Returns:
            Decoded output from ``db2 activate database``.
        """
        return activate_db2_database(
            self.container,
            db_name or self.db_name,
            instance_user=self.username,
        )


def validate_db2_database_name(db_name: str) -> str:
    """Validate that a Db2 database name conforms to the 8-character identifier rule.

    Args:
        db_name: Candidate Db2 database name.

    Returns:
        The validated database name.

    Raises:
        ValueError: If ``db_name`` exceeds 8 characters or contains invalid characters.
    """
    if len(db_name) > DB2_MAX_DB_NAME_LENGTH or not _DB2_NAME_PATTERN.match(db_name):
        msg = (
            f"Invalid Db2 database name {db_name!r}: must start with a letter, contain only "
            f"ASCII letters, digits, or underscores, and be at most {DB2_MAX_DB_NAME_LENGTH} characters."
        )
        raise ValueError(msg)
    return db_name


def exec_db2_sql(
    container: Container,
    sql: str,
    *,
    db_name: str,
    instance_user: str = "db2inst1",
) -> str:
    """Execute a SQL statement inside a running Db2 container via the ``db2`` CLI.

    The command line processor exits with 1 when a statement finds no rows (``SQL0100W``) and with 2 for other
    warnings. Both count as success, and the CLP message text is part of the returned output so callers can inspect
    it. Exit codes of 4 and above (errors) raise. All ``db2`` calls run in one shell process because the CLP back end,
    and therefore the connection, is tied to the calling shell; the connect output goes to a file instead of a command
    substitution for that reason.

    Args:
        container: Running Db2 container.
        sql: SQL statement to execute.
        db_name: Target Db2 database name (at most 8 characters).
        instance_user: Db2 instance owner OS user inside the container.

    Returns:
        Decoded stdout/stderr from the ``db2`` command sequence, including any warning text.

    Raises:
        RuntimeError: If connecting or executing the statement fails with a CLP exit code of 4 or higher.
    """
    validate_db2_database_name(db_name)
    inner_cmd = (
        'log="$HOME/.pytest-databases-connect.$$"; '
        f'db2 connect to {shlex.quote(db_name)} > "$log" 2>&1; rc=$?; '
        f'if [ "$rc" -gt {_CLP_MAX_SUCCESS_EXIT_CODE} ]; then cat "$log"; rm -f "$log"; exit "$rc"; fi; '
        'rm -f "$log"; '
        f"db2 -x {shlex.quote(sql)}; rc=$?; "
        'db2 connect reset >/dev/null; exit "$rc"'
    )
    result = container.exec_run(["su", "-", instance_user, "-c", inner_cmd])
    output = exec_output_to_bytes(result.output).decode("utf-8", errors="replace")
    if result.exit_code is None or result.exit_code > _CLP_MAX_SUCCESS_EXIT_CODE:
        msg = f"Db2 SQL command failed (exit {result.exit_code}): {output.strip()}"
        raise RuntimeError(msg)
    return output.strip()


def create_worker_database(
    container: Container,
    db_name: str,
    *,
    instance_user: str = "db2inst1",
    lock_path: Path | None = None,
) -> None:
    """Create a Db2 database inside the container if it does not already exist.

    Args:
        container: Running Db2 container.
        db_name: Target Db2 database name (at most 8 characters).
        instance_user: Db2 instance owner OS user inside the container.
        lock_path: Optional cross-worker host lock file path serializing catalog writes.
    """
    validate_db2_database_name(db_name)
    inner_cmd = _wrap_with_container_flock(
        f"db2 list db directory | grep -Eiq '^[[:space:]]*Database name[[:space:]]*= {db_name}[[:space:]]*$' "
        f"|| db2 create database {shlex.quote(db_name)}"
    )
    lock_cm: contextlib.AbstractContextManager[object] = (
        filelock.FileLock(str(lock_path), timeout=_DB2_INIT_LOCK_TIMEOUT)
        if lock_path is not None
        else contextlib.nullcontext()
    )
    with lock_cm:
        result = container.exec_run(["su", "-", instance_user, "-c", inner_cmd])
    if result.exit_code != 0:
        output = exec_output_to_bytes(result.output).decode("utf-8", errors="replace")
        msg = f"Failed to create Db2 database {db_name!r} (exit {result.exit_code}): {output.strip()}"
        raise RuntimeError(msg)


def activate_db2_database(
    container: Container,
    db_name: str,
    *,
    instance_user: str = "db2inst1",
) -> str:
    """Explicitly activate ``db_name`` inside a Db2 container so ``MON_GET_*`` metrics persist across disconnects.

    Without explicit activation, Db2 deactivates a database when the last client disconnects and resets
    in-memory bufferpool, lock, tablespace, and package-cache counters. CLP exit codes ``0`` through ``2``
    (including ``SQL1490W`` when already active) are treated as idempotent success.

    Args:
        container: Running Db2 container.
        db_name: Target Db2 database name (at most 8 characters).
        instance_user: Db2 instance owner OS user inside the container.

    Returns:
        Decoded CLP stdout/stderr message text.

    Raises:
        RuntimeError: If ``db2 activate database`` fails with an error exit code.
    """
    validate_db2_database_name(db_name)
    inner_cmd = f"db2 activate database {shlex.quote(db_name)}"
    result = container.exec_run(["su", "-", instance_user, "-c", inner_cmd])
    output = exec_output_to_bytes(result.output).decode("utf-8", errors="replace").strip()
    exit_code = result.exit_code
    if exit_code is None or (exit_code > _CLP_MAX_ACTIVATE_EXIT_CODE and "SQL1490W" not in output):
        msg = f"Failed to activate Db2 database {db_name!r} (exit {exit_code}): {output}"
        raise RuntimeError(msg)
    return output


@contextmanager
def provide_db2_service(
    container_service: ContainerService,
    db2_image: str,
    db2_dbname: str,
    db2_username: str,
    db2_password: str,
    db2_startup_timeout: int,
    xdist_db2_isolation_level: XdistIsolationLevel,
    *,
    enable_4k_device_support: bool = True,
    activate_database: bool = True,
    host_port: int | None = None,
    env: Mapping[str, str] | None = None,
    registry_vars: Mapping[str, str] | None = None,
    shm_size: int | str | None = None,
    mem_limit: str | None = None,
    platform: str | None = None,
    ipc_mode: str | None = DEFAULT_DB2_IPC_MODE,
    volumes: dict[str, dict[str, str]] | list[str] | None = None,
    init_sql: str | Path | Sequence[str | Path] | None = None,
) -> Generator[Db2Service, None, None]:
    """Start and yield a ready IBM Db2 Community Edition service container.

    With ``enable_4k_device_support`` (the default) the instance runs with ``DB2_4K_DEVICE_SUPPORT=ON`` and
    ``DB2_DIRECT_IO=NO`` so database creation works when the container storage has 4096-byte logical sectors.
    Additional ``db2set`` settings in ``registry_vars`` are chained onto the same pre-``db2start`` setup hook.
    With ``activate_database`` (the default), ``db2 activate database`` keeps the database pinned in memory so
    ``MON_GET_*`` monitoring snapshots persist across short-lived client connections.

    Args:
        container_service: The container service manager.
        db2_image: IBM Db2 Community Edition container image.
        db2_dbname: Database name for the active worker.
        db2_username: Db2 instance owner username.
        db2_password: Db2 instance owner password.
        db2_startup_timeout: Startup timeout in seconds.
        xdist_db2_isolation_level: xdist isolation strategy (database or server).
        enable_4k_device_support: Whether to apply the 4096-byte sector registry settings.
        activate_database: Whether to run ``db2 activate database`` on the ready database.
        host_port: Optional pinned host TCP port for Db2 port 50000.
        env: Optional extra container environment variables merged over defaults.
        registry_vars: Optional extra ``db2set`` registry ``KEY=VALUE`` settings applied before ``db2start``.
        shm_size: Optional ``/dev/shm`` size forwarded to container creation.
        mem_limit: Optional memory limit forwarded to container creation.
        platform: Optional OCI platform override (for example ``"linux/amd64"`` on Apple Silicon).
        ipc_mode: Container IPC mode (defaults to ``"host"``; pass ``None`` or ``""`` to omit).
        volumes: Optional container volume mounts (for example ``/database`` persistence).
        init_sql: Optional SQL statement, ``.sql`` path, or sequence executed once per database.

    Yields:
        A configured Db2Service instance.
    """
    name, initial_db, transient = _resolve_db2_targets(db2_dbname, xdist_db2_isolation_level)
    settings = _collect_db2_registry_settings(
        enable_4k_device_support=enable_4k_device_support,
        registry_vars=registry_vars,
    )
    recreate_attempted = False

    def check(service: ServiceContainer) -> bool:
        nonlocal recreate_attempted
        if not tcp_port_open(service.host, service.port):
            return False
        try:
            output = exec_db2_sql(
                service.container,
                "SELECT 1 FROM SYSIBM.SYSDUMMY1",
                db_name=initial_db,
                instance_user=db2_username,
            )
        except RuntimeError as exc:
            err_text = str(exc)
            _raise_if_fatal_db2_failure(service.container, initial_db, err_text)
            if settings and _is_missing_db2_database_error(err_text) and not recreate_attempted:
                recreate_attempted = True
                probe_lock = _resolve_db2_lock_path(container_service, service.container)
                lock_cm: contextlib.AbstractContextManager[object] = (
                    filelock.FileLock(str(probe_lock), timeout=_DB2_INIT_LOCK_TIMEOUT)
                    if probe_lock is not None
                    else contextlib.nullcontext()
                )
                with lock_cm:
                    try:
                        reprobe = exec_db2_sql(
                            service.container,
                            "SELECT 1 FROM SYSIBM.SYSDUMMY1",
                            db_name=initial_db,
                            instance_user=db2_username,
                        )
                    except RuntimeError as reprobe_exc:
                        reprobe_text = str(reprobe_exc)
                        _raise_if_fatal_db2_failure(service.container, initial_db, reprobe_text)
                        if _is_missing_db2_database_error(reprobe_text):
                            _create_database_with_registry_settings(
                                service.container,
                                initial_db,
                                instance_user=db2_username,
                                settings=settings,
                            )
                    else:
                        if reprobe == "1":
                            return True
            return False
        return output == "1"

    entrypoint, command = _build_db2_startup_command(settings)
    with container_service.run(
        **_build_db2_run_kwargs(
            db2_image=db2_image,
            name=name,
            command=command,
            entrypoint=entrypoint,
            db2_password=db2_password,
            initial_db=initial_db,
            extra_env=env,
            check=check,
            db2_startup_timeout=db2_startup_timeout,
            transient=transient,
            host_port=host_port,
            shm_size=shm_size,
            mem_limit=mem_limit,
            platform=platform,
            ipc_mode=ipc_mode,
            volumes=volumes,
        )
    ) as service:
        lock_path = _resolve_db2_lock_path(container_service, service.container)
        _finalize_db2_database(
            service.container,
            db2_dbname=db2_dbname,
            initial_db=initial_db,
            instance_user=db2_username,
            activate=activate_database,
            init_sql=init_sql,
            lock_path=lock_path,
        )
        yield Db2Service(
            container=service.container,
            host=service.host,
            port=service.port,
            db_name=db2_dbname,
            username=db2_username,
            password=db2_password,
            _lock_path=lock_path,
        )


@pytest.fixture(scope="session")
def xdist_db2_isolation_level() -> XdistIsolationLevel:
    """Provide the pytest-xdist isolation level for Db2."""
    return "database"


@pytest.fixture(scope="session")
def db2_4k_device_support() -> bool:
    """Whether Db2 runs with ``DB2_4K_DEVICE_SUPPORT=ON`` and ``DB2_DIRECT_IO=NO``.

    Enabled by default so database creation works on storage with 4096-byte logical sectors. Set the
    ``DB2_4K_DEVICE_SUPPORT`` environment variable to ``0``/``false``/``no``/``off`` or override this fixture to
    return ``False`` to keep the image defaults.
    """
    return os.getenv("DB2_4K_DEVICE_SUPPORT", "on").strip().lower() not in _DB2_FALSE_VALUES


@pytest.fixture(scope="session")
def db2_activate_database() -> bool:
    """Whether Db2 explicitly activates the database so ``MON_GET_*`` metrics persist across disconnects."""
    return os.getenv("DB2_ACTIVATE_DATABASE", "on").strip().lower() not in _DB2_FALSE_VALUES


@pytest.fixture(scope="session")
def db2_image() -> str:
    """Provide the IBM Db2 Community Edition container image."""
    return os.getenv("DB2_IMAGE", DEFAULT_DB2_IMAGE)


@pytest.fixture(scope="session")
def db2_username() -> str:
    """Provide the Db2 instance owner username."""
    return os.getenv("DB2_USER", "db2inst1")


@pytest.fixture(scope="session")
def db2_password() -> str:
    """Provide the Db2 instance owner password."""
    return os.getenv("DB2_PASSWORD", "pytest_db2_pwd")


@pytest.fixture(scope="session")
def db2_port() -> int | None:
    """Provide an optional pinned host TCP port for Db2 (``DB2_PORT``)."""
    return env_port("DB2_PORT")


@pytest.fixture(scope="session")
def db2_dbname(xdist_db2_isolation_level: XdistIsolationLevel) -> str:
    """Provide an 8-character-compliant Db2 database name."""
    worker_num = get_xdist_worker_num()
    if worker_num is not None and xdist_db2_isolation_level == "database":
        return validate_db2_database_name(f"ptdb_{worker_num}")
    return validate_db2_database_name(os.getenv("DB2_DBNAME", "pytestdb"))


@pytest.fixture(scope="session")
def db2_startup_timeout() -> int:
    """Provide the startup timeout in seconds for Db2 container initialization."""
    return int(os.getenv("DB2_STARTUP_TIMEOUT", "600"))


@pytest.fixture(scope="session")
def db2_ipc_mode() -> str | None:
    """Provide the container IPC mode for Db2 (defaults to ``"host"``; empty string omits ``ipc_mode``)."""
    return os.getenv("DB2_IPC_MODE", DEFAULT_DB2_IPC_MODE) or None


@pytest.fixture(scope="session")
def db2_volumes() -> dict[str, dict[str, str]] | list[str] | None:
    """Optional container volume mounts for Db2 (for example ``{"/host/db2": {"bind": "/database", "mode": "rw"}}``)."""
    return None


@pytest.fixture(scope="session")
def db2_service(
    container_service: ContainerService,
    db2_image: str,
    db2_dbname: str,
    db2_username: str,
    db2_password: str,
    db2_startup_timeout: int,
    xdist_db2_isolation_level: XdistIsolationLevel,
    db2_4k_device_support: bool,
    db2_activate_database: bool,
    db2_port: int | None,
    db2_ipc_mode: str | None,
    db2_volumes: dict[str, dict[str, str]] | list[str] | None,
) -> Generator[Db2Service, None, None]:
    """Start and yield a ready IBM Db2 Community Edition service container.

    Yields:
        A configured Db2Service instance.
    """
    with provide_db2_service(
        container_service=container_service,
        db2_image=db2_image,
        db2_dbname=db2_dbname,
        db2_username=db2_username,
        db2_password=db2_password,
        db2_startup_timeout=db2_startup_timeout,
        xdist_db2_isolation_level=xdist_db2_isolation_level,
        enable_4k_device_support=db2_4k_device_support,
        activate_database=db2_activate_database,
        host_port=db2_port,
        ipc_mode=db2_ipc_mode,
        volumes=db2_volumes,
    ) as service:
        yield service


def _resolve_db2_targets(
    db2_dbname: str,
    isolation_level: XdistIsolationLevel,
) -> tuple[str, str, bool]:
    """Return ``(container_name, initial_db, transient)`` for the active worker."""
    worker_num = get_xdist_worker_num()
    if worker_num is None:
        return "db2", validate_db2_database_name(db2_dbname), False
    if isolation_level == "server":
        return f"db2_{worker_num}", validate_db2_database_name(db2_dbname), True
    initial_db = validate_db2_database_name(os.getenv("DB2_DBNAME", "pytestdb"))
    return "db2", initial_db, False


def _collect_db2_registry_settings(
    *,
    enable_4k_device_support: bool,
    registry_vars: Mapping[str, str] | None,
) -> tuple[tuple[str, str], ...]:
    """Validate and merge Db2 ``db2set`` registry variables in deterministic application order."""
    merged: dict[str, str] = {}
    if enable_4k_device_support:
        merged.update(_DB2_4K_REGISTRY_SETTINGS)
    if registry_vars:
        for key, raw_val in registry_vars.items():
            if not _DB2_REGISTRY_KEY_PATTERN.fullmatch(key):
                msg = f"Invalid Db2 registry variable name {key!r}."
                raise ValueError(msg)
            value = str(raw_val)
            if not value or any(ch in value for ch in ("\x00", "\n", "\r", "'", '"', "`", "$", ";", "&", "|")):
                msg = f"Invalid Db2 registry variable value for {key!r}: {raw_val!r}."
                raise ValueError(msg)
            merged[key] = value
    return tuple(merged.items())


def _build_db2_startup_command(
    settings: tuple[tuple[str, str], ...],
) -> tuple[list[str] | None, list[str] | None]:
    """Return ``(entrypoint, command)`` patching Db2 setup when registry settings are active."""
    if not settings:
        return None, None
    return ["/bin/bash", "-c"], [_db2_registry_setup_command(settings)]


def _db2_4k_setup_command() -> str:
    """Build the container command that applies the 4096-byte sector registry settings before Db2 setup runs."""
    return _db2_registry_setup_command(_DB2_4K_REGISTRY_SETTINGS)


def _db2_registry_setup_command(settings: tuple[tuple[str, str], ...]) -> str:
    """Build a ``bash -c`` command patching ``db2_common_functions`` to set ``settings`` before ``db2start``."""

    def _escape_sed_rhs(text: str) -> str:
        return text.replace("\\", "\\\\").replace("&", "\\&").replace("/", "\\/")

    extra = "".join(f" \\&\\& db2set {key}={_escape_sed_rhs(value)}" for key, value in settings)
    expression = f"s/db2set DB2COMM=TCPIP/db2set DB2COMM=TCPIP{extra}/"
    return f"sed -i {shlex.quote(expression)} {_DB2_SETUP_FUNCTIONS} && exec {_DB2_SETUP_SCRIPT}"


class _Db2RunKwargs(TypedDict):
    image: str
    container_port: int
    name: str
    command: list[str] | None
    entrypoint: list[str] | None
    env: dict[str, str]
    wait_for_log: str
    check: Callable[[ServiceContainer], bool]
    timeout: int
    pause: float
    transient: bool
    privileged: bool
    host_port: NotRequired[int]
    shm_size: NotRequired[int | str]
    mem_limit: NotRequired[str]
    platform: NotRequired[str]
    ipc_mode: NotRequired[str]
    volumes: NotRequired[dict[str, dict[str, str]] | list[str]]


def _build_db2_run_kwargs(
    *,
    db2_image: str,
    name: str,
    command: list[str] | None,
    entrypoint: list[str] | None,
    db2_password: str,
    initial_db: str,
    extra_env: Mapping[str, str] | None,
    check: Callable[[ServiceContainer], bool],
    db2_startup_timeout: int,
    transient: bool,
    host_port: int | None,
    shm_size: int | str | None,
    mem_limit: str | None,
    platform: str | None,
    ipc_mode: str | None,
    volumes: dict[str, dict[str, str]] | list[str] | None,
) -> _Db2RunKwargs:
    """Assemble keyword arguments forwarded to :meth:`ContainerService.run` without clobbering defaults."""
    container_env: dict[str, str] = {
        "LICENSE": "accept",
        "DB2INST1_PASSWORD": db2_password,
        "DBNAME": initial_db,
        "SAMPLEDB": "false",
        "AUTOCONFIG": "false",
        "ARCHIVE_LOGS": "false",
        "TO_CREATE_SAMPLEDB": "false",
        "REPODB": "false",
    }
    if extra_env:
        container_env.update(extra_env)
    kwargs: _Db2RunKwargs = {
        "image": db2_image,
        "container_port": DB2_PORT,
        "name": name,
        "command": command,
        "entrypoint": entrypoint,
        "env": container_env,
        "wait_for_log": "Setup has completed",
        "check": check,
        "timeout": db2_startup_timeout,
        "pause": 2.0,
        "transient": transient,
        "privileged": True,
    }
    if host_port is not None:
        kwargs["host_port"] = host_port
    if shm_size is not None:
        kwargs["shm_size"] = shm_size
    if mem_limit is not None:
        kwargs["mem_limit"] = mem_limit
    if platform is not None:
        kwargs["platform"] = platform
    if ipc_mode:
        kwargs["ipc_mode"] = ipc_mode
    if volumes is not None:
        kwargs["volumes"] = volumes
    return kwargs


def _resolve_db2_lock_path(container_service: ContainerService, container: Container) -> Path | None:
    """Resolve the shared host lock path for Db2 catalog operations inside ``container``."""
    container_id = getattr(container, "id", None)
    if not isinstance(container_id, str) or not container_id.strip():
        return None
    base_dir = container_service.temp_dir
    base_dir.mkdir(parents=True, exist_ok=True)
    return base_dir / f"{container_id.strip()}_db2_init.lock"


def _wrap_with_container_flock(inner_cmd: str) -> str:
    """Serialize in-container Db2 catalog writes behind a non-blocking-safe fd ``flock`` guard."""
    timeout_s = int(_DB2_INIT_LOCK_TIMEOUT)
    return (
        f"if command -v flock >/dev/null 2>&1; then "
        f"exec 9>{_DB2_CONTAINER_LOCK_FILE} && flock -w {timeout_s} 9 || exit 1; "
        f"fi; {inner_cmd}"
    )


def _is_missing_db2_database_error(err_text: str) -> bool:
    """Return whether ``err_text`` indicates a missing or 4K-sector-uninitialized Db2 database."""
    upper_err = err_text.upper()
    return any(marker in upper_err for marker in _DB2_4K_MISSING_DATABASE_MARKERS)


def _raise_if_fatal_db2_failure(container: Container, db_name: str, err_text: str) -> None:
    """Raise ``RuntimeError`` immediately when CLP output or container logs contain a fatal Db2 startup marker."""
    raw_logs: object = None
    with contextlib.suppress(Exception):
        raw_logs = container.logs(tail=100)
    log_text = ""
    if isinstance(raw_logs, (bytes, bytearray)):
        log_text = raw_logs.decode("utf-8", errors="replace")
    elif isinstance(raw_logs, str):
        log_text = raw_logs
    upper_combined = f"{err_text}\n{log_text}".upper()
    matched = next((marker for marker in _DB2_FATAL_STARTUP_MARKERS if marker in upper_combined), None)
    if matched is None:
        return
    diag_lines = [line.strip() for line in (*err_text.splitlines(), *log_text.splitlines()) if line.strip()]
    tail = "\n".join(diag_lines[-10:])
    msg = f"Fatal Db2 startup error ({matched}) probing database {db_name!r}:\n{tail}"
    raise RuntimeError(msg)


def _create_database_with_registry_settings(
    container: Container,
    db_name: str,
    *,
    instance_user: str,
    settings: tuple[tuple[str, str], ...],
) -> None:
    """Apply ``settings``, restart the Db2 instance, and create ``db_name`` if missing."""
    validate_db2_database_name(db_name)
    registry = " && ".join(f"db2set {key}={shlex.quote(value) if '/' in value else value}" for key, value in settings)
    inner_cmd = _wrap_with_container_flock(
        f"db2 list db directory | grep -Eiq '^[[:space:]]*Database name[[:space:]]*= {db_name}[[:space:]]*$' "
        f"|| ({registry} && db2stop force && db2start && db2 create database {shlex.quote(db_name)})"
    )
    result = container.exec_run(["su", "-", instance_user, "-c", inner_cmd])
    if result.exit_code != 0:
        output = exec_output_to_bytes(result.output).decode("utf-8", errors="replace")
        msg = f"Failed to create Db2 database {db_name!r} (exit {result.exit_code}): {output.strip()}"
        raise RuntimeError(msg)


def _finalize_db2_database(
    container: Container,
    *,
    db2_dbname: str,
    initial_db: str,
    instance_user: str,
    activate: bool,
    init_sql: str | Path | Sequence[str | Path] | None,
    lock_path: Path | None = None,
) -> None:
    """Create worker database when isolated, optionally pin it active in memory, and execute ``init_sql``."""
    target_db = validate_db2_database_name(db2_dbname)
    if target_db != initial_db:
        create_worker_database(container, target_db, instance_user=instance_user, lock_path=lock_path)
    if activate:
        container_id = getattr(container, "id", None)
        lock_cm: contextlib.AbstractContextManager[object] = contextlib.nullcontext()
        if isinstance(container_id, str) and container_id:
            lock_path = Path(tempfile.gettempdir()) / f"pytest-databases-db2-act-{container_id[:12]}-{target_db}.lock"
            lock_cm = filelock.FileLock(str(lock_path), timeout=120.0)
        with lock_cm:
            activate_db2_database(container, target_db, instance_user=instance_user)
    statements = read_init_scripts(init_sql)
    if not statements:
        return
    fingerprint = simple_string_hash("\n;\n".join(statements))

    def _run() -> None:
        for statement in statements:
            exec_db2_sql(container, statement, db_name=target_db, instance_user=instance_user)

    run_container_init_once(container, f"db2:{target_db}", fingerprint, _run)
