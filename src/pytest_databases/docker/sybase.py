"""SAP Sybase ASE (Adaptive Server Enterprise) container service fixtures."""

from __future__ import annotations

import dataclasses
import os
import posixpath
import re
import shlex
import tempfile
import time
from contextlib import ExitStack, contextmanager, suppress
from pathlib import Path
from typing import TYPE_CHECKING, NotRequired, TypedDict

import filelock
import pytest

from pytest_databases.helpers import (
    TRUE_VALUES,
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

__all__ = (
    "DEFAULT_SYBASE_IMAGE",
    "SYBASE_DATABASE",
    "SYBASE_MAX_DB_NAME_LENGTH",
    "SYBASE_PASSWORD",
    "SYBASE_PORT",
    "SYBASE_USER",
    "SYBASE_WORKER_DATABASE",
    "SYBASE_WORKER_DATABASE_SIZE",
    "SybaseService",
    "configure_sybase_monitoring",
    "create_worker_database",
    "exec_isql",
    "provide_sybase_service",
    "sybase_database",
    "sybase_enable_monitoring",
    "sybase_image",
    "sybase_password",
    "sybase_port",
    "sybase_service",
    "sybase_startup_timeout",
    "sybase_user",
    "validate_sybase_database_name",
    "xdist_sybase_isolation_level",
)

DEFAULT_SYBASE_IMAGE = "datagrip/sybase:16.0"
SYBASE_PORT = 5000
SYBASE_USER = "sa"
SYBASE_PASSWORD = "myPassword"
SYBASE_DATABASE = "master"
SYBASE_WORKER_DATABASE = "pytestdb"
SYBASE_WORKER_DATABASE_SIZE = "48M"
SYBASE_MAX_DB_NAME_LENGTH = 30
_SYBASE_NAME_PATTERN = re.compile(r"[A-Za-z][A-Za-z0-9_]{0,29}")
_SYBASE_ENV_SCRIPT = "/opt/sybase/SYBASE.sh"
_SYBASE_ERROR_LOG = "/opt/sybase/ASE-16_0/install/MYSYBASE.log"
_READINESS_SQL = "SELECT 4242"
_READINESS_ROW = "4242"
_ISQL_ERROR_PATTERN = re.compile(
    rb"^(?:Msg \d+, Level (?:1[1-9]|2\d)|CT-LIBRARY error:|The context allocation routine failed)", re.MULTILINE
)
_MODEL_IN_USE_PATTERN = re.compile(r"Msg\s+1807\b|MODEL database in use", re.IGNORECASE)
_CREATE_DB_MAX_ATTEMPTS = 10
_CREATE_DB_RETRY_DELAY = 1.0

ISQL_CANDIDATES: tuple[str, ...] = (
    "/opt/sybase/OCS-16_0/bin/isql64",
    "/opt/sybase/OCS-16_0/bin/isql",
    "/opt/sybase/OCS-15_0/bin/isql64",
    "/opt/sybase/OCS-15_0/bin/isql",
    "isql64",
    "isql",
)


@dataclasses.dataclass
class SybaseService(ServiceContainer):
    """Service handle for a running SAP Sybase ASE container."""

    user: str
    password: str
    database: str

    @property
    def connection_config(self) -> dict[str, str | int | bool]:
        """Connection configuration parameters compatible with Sybase drivers."""
        return {
            "server": self.host,
            "port": self.port,
            "user": self.user,
            "password": self.password,
            "database": self.database,
            "autocommit": True,
        }

    @property
    def dsn(self) -> str:
        """TDS connection string representation."""
        return (
            f"DRIVER={{FreeTDS}};SERVER={self.host};PORT={self.port};"
            f"DATABASE={self.database};UID={self.user};PWD={self.password};TDS_Version=5.0;"
        )

    def exec_sql(
        self,
        sql: str,
        *,
        database: str | None = None,
        user: str | None = None,
        password: str | None = None,
    ) -> tuple[int, bytes]:
        """Execute a SQL statement inside the Sybase ASE container via ``isql``.

        Returns:
            Tuple of ``(exit_code, output_bytes)``.
        """
        return exec_isql(
            self.container,
            sql,
            database=database or self.database,
            user=self.user if user is None else user,
            password=self.password if password is None else password,
        )

    def create_worker_database(self, db_name: str) -> None:
        """Create an isolated database inside the Sybase ASE container."""
        create_worker_database(
            self.container,
            db_name,
            user=self.user,
            password=self.password,
        )


def validate_sybase_database_name(db_name: str) -> str:
    """Validate that a Sybase database name conforms to ASE identifier limits.

    Args:
        db_name: Candidate Sybase database name.

    Returns:
        The validated database name.

    Raises:
        ValueError: If ``db_name`` exceeds length limits or has invalid characters.
    """
    if len(db_name) > SYBASE_MAX_DB_NAME_LENGTH or not _SYBASE_NAME_PATTERN.fullmatch(db_name):
        msg = (
            f"Invalid Sybase database name {db_name!r}: must start with a letter, contain only "
            f"ASCII letters, digits, or underscores, and be at most {SYBASE_MAX_DB_NAME_LENGTH} characters."
        )
        raise ValueError(msg)
    return db_name


def exec_isql(
    container: Container,
    sql: str,
    *,
    database: str = SYBASE_DATABASE,
    user: str = SYBASE_USER,
    password: str = SYBASE_PASSWORD,
    port: int = SYBASE_PORT,
) -> tuple[int, bytes]:
    """Execute a T-SQL batch inside a Sybase ASE container via the in-container ``isql``.

    The script sources ``/opt/sybase/SYBASE.sh`` when the image ships it, connects to ``127.0.0.1:<port>`` so no
    ``interfaces`` entry is needed, and runs ``isql --retserverror -b`` (no column headers). ``isql`` exits ``0``
    for some failures (for example when its localization files cannot be loaded), so a zero exit code is replaced by
    ``1`` when the output contains a server error of severity 11 or higher (``Msg <n>, Level <11-29>``) or a
    client library error.

    Args:
        container: Running Sybase ASE container.
        sql: SQL statements to execute.
        database: Target database name.
        user: Login username.
        password: User password.
        port: Server port inside the container.

    Returns:
        Tuple of (exit_code, output_bytes).
    """
    batch = sql.strip()
    if not batch.endswith(("go", "GO")):
        batch = f"{batch}\ngo"
    isql_args = (
        f"-S 127.0.0.1:{port} -U {shlex.quote(user)} -P {shlex.quote(password)} "
        f"-D {shlex.quote(database)} -w 2048 --retserverror -b"
    )
    script = (
        f"if [ -f {_SYBASE_ENV_SCRIPT} ]; then . {_SYBASE_ENV_SCRIPT} >/dev/null 2>&1; fi; "
        f"for bin in {' '.join(ISQL_CANDIDATES)}; do "
        f"if command -v $bin >/dev/null 2>&1; then "
        f"$bin {isql_args} <<'EOF'\n"
        f"{batch}\n"
        f"EOF\n"
        f"exit $?; "
        f"fi; "
        f"done; "
        f"exit 127"
    )
    result = container.exec_run(["sh", "-c", script])
    exit_code = result.exit_code if result.exit_code is not None else -1
    output = exec_output_to_bytes(result.output)
    if exit_code == 0 and _ISQL_ERROR_PATTERN.search(output):
        exit_code = 1
    return exit_code, output


def create_worker_database(
    container: Container,
    db_name: str,
    *,
    user: str = SYBASE_USER,
    password: str = SYBASE_PASSWORD,
    size: str = SYBASE_WORKER_DATABASE_SIZE,
) -> None:
    """Create a database and its own device inside the Sybase ASE container if they do not already exist.

    The ``master`` device of the default image has too little free space for a copy of ``model``, so each database
    gets a ``<db_name>_dev`` device (``DISK INIT``) next to the ``master`` device file.

    Args:
        container: Running Sybase container.
        db_name: Database name to create.
        user: Login username.
        password: User password.
        size: Size of the device and the database, for example ``48M``.

    Raises:
        RuntimeError: If the device or database cannot be created.
    """
    container_id = getattr(container, "id", None)
    lock_key = container_id[:12] if isinstance(container_id, str) and container_id else "default"
    lock_path = Path(tempfile.gettempdir()) / f"pytest-databases-sybase-{lock_key}.lock"
    valid_name = validate_sybase_database_name(db_name)
    device = f"{valid_name}_dev"
    with filelock.FileLock(lock_path):
        exit_code, output = exec_isql(
            container,
            "SELECT phyname FROM master.dbo.sysdevices WHERE name = 'master'",
            database="master",
            user=user,
            password=password,
        )
        master_path = next(
            (line.strip() for line in output.decode("utf-8", errors="replace").splitlines() if "/" in line), ""
        )
        if exit_code != 0 or not master_path:
            decoded = output.decode("utf-8", errors="replace").strip()
            msg = f"Failed to locate the Sybase master device (exit {exit_code}): {decoded}"
            raise RuntimeError(msg)
        device_path = posixpath.join(posixpath.dirname(master_path), f"{valid_name}.dat")
        sql = (
            f"IF NOT EXISTS (SELECT 1 FROM master.dbo.sysdevices WHERE name = '{device}')\n"
            f"    DISK INIT name = '{device}', physname = '{device_path}', size = '{size}'\n"
            f"go\n"
            f"IF NOT EXISTS (SELECT 1 FROM master.dbo.sysdatabases WHERE name = '{valid_name}')\n"
            f"    CREATE DATABASE {valid_name} ON {device} = '{size}'\n"
            f"go"
        )
        for attempt in range(_CREATE_DB_MAX_ATTEMPTS):
            exit_code, output = exec_isql(container, sql, database="master", user=user, password=password)
            if exit_code == 0:
                return
            decoded = output.decode("utf-8", errors="replace").strip()
            if _MODEL_IN_USE_PATTERN.search(decoded) and attempt < _CREATE_DB_MAX_ATTEMPTS - 1:
                time.sleep(_CREATE_DB_RETRY_DELAY)
                continue
            msg = f"Failed to create Sybase database {valid_name!r} (exit {exit_code}): {decoded}"
            raise RuntimeError(msg)


def configure_sybase_monitoring(
    container: Container,
    *,
    user: str = SYBASE_USER,
    password: str = SYBASE_PASSWORD,
    grant_to: str | None = None,
) -> None:
    """Enable SAP ASE Monitoring and Diagnostic Adapter (``mon*`` MDA tables) via ``sp_configure``.

    Applies the dynamic and pipe MDA configuration parameters once per container under a cross-worker
    lock, and optionally grants ``mon_role`` to a non-``sa`` login so ``master..mon*`` telemetry queries
    work out of the box.

    Args:
        container: Running Sybase ASE container handle.
        user: Administrative login executing ``sp_configure`` (defaults to ``"sa"``).
        password: Password for ``user``.
        grant_to: Optional non-``sa`` login to grant ``mon_role``.

    Raises:
        ValueError: If ``grant_to`` is not a valid Sybase identifier.
        RuntimeError: If ``sp_configure`` or ``grant role mon_role`` fails.
    """
    mda_settings: tuple[tuple[str, int], ...] = (
        ("enable monitoring", 1),
        ("per object statistics active", 1),
        ("statement statistics active", 1),
        ("wait event timing", 1),
        ("object lockwait timing", 1),
        ("SQL batch capture", 1),
        ("sql text pipe active", 1),
        ("sql text pipe max messages", 256),
        ("max SQL text monitored", 4096),
    )
    mda_sql = "\ngo\n".join(f"exec sp_configure '{param}', {val}" for param, val in mda_settings) + "\ngo"
    mda_digest = simple_string_hash(mda_sql)

    def _enable_mda() -> None:
        code, output = exec_isql(container, mda_sql, database="master", user=user, password=password)
        if code != 0:
            detail = output.decode("utf-8", errors="replace").strip()
            msg = f"Failed to enable Sybase MDA monitoring (exit {code}): {detail}"
            raise RuntimeError(msg)

    run_container_init_once(container, "sybase:mda", mda_digest, _enable_mda)

    if grant_to is not None and grant_to.lower() != "sa":
        valid_login = validate_sybase_database_name(grant_to)
        grant_sql = f"grant role mon_role to {valid_login}\ngo"

        def _grant_role() -> None:
            code, output = exec_isql(container, grant_sql, database="master", user=user, password=password)
            if code != 0:
                detail = output.decode("utf-8", errors="replace").strip()
                msg = f"Failed to grant Sybase mon_role to {valid_login!r} (exit {code}): {detail}"
                raise RuntimeError(msg)

        run_container_init_once(
            container,
            f"sybase:mon_role:{valid_login.lower()}",
            simple_string_hash(grant_sql),
            _grant_role,
        )


@contextmanager
def provide_sybase_service(
    container_service: ContainerService,
    sybase_image: str,
    sybase_user: str,
    sybase_password: str,
    sybase_database: str,
    sybase_startup_timeout: int,
    xdist_sybase_isolation_level: XdistIsolationLevel,
    *,
    enable_monitoring: bool = False,
    host_port: int | None = None,
    env: Mapping[str, str] | None = None,
    init_sql: str | Path | Sequence[str | Path] | None = None,
) -> Generator[SybaseService, None, None]:
    """Start and yield a ready SAP Sybase ASE service container.

    Yields:
        A configured SybaseService instance.
    """
    worker_num = get_xdist_worker_num()
    initial_db = _resolve_sybase_database(sybase_database, worker_num, xdist_sybase_isolation_level)
    name = f"sybase_{worker_num}" if worker_num is not None and xdist_sybase_isolation_level == "server" else "sybase"

    last_container: Container | None = None
    last_stage = "port"

    def check(service: ServiceContainer) -> bool:
        nonlocal last_container, last_stage
        last_container = service.container
        last_stage = "port"
        if not tcp_port_open(service.host, service.port, timeout=1.0):
            return False
        last_stage = "log"
        if sybase_image == DEFAULT_SYBASE_IMAGE and b"SYBASE INITIALIZED" not in service.container.logs():
            return False
        last_stage = "isql"
        return _is_sybase_ready(
            *exec_isql(
                service.container,
                _READINESS_SQL,
                database="master",
                user=sybase_user,
                password=sybase_password,
            )
        )

    with ExitStack() as stack:
        try:
            service = stack.enter_context(
                container_service.run(
                    **_build_sybase_run_kwargs(
                        sybase_image=sybase_image,
                        name=name,
                        sybase_password=sybase_password,
                        extra_env=env,
                        check=check,
                        timeout=sybase_startup_timeout,
                        transient=worker_num is not None and xdist_sybase_isolation_level == "server",
                        host_port=host_port,
                    )
                )
            )
        except ValueError as exc:
            raise _sybase_startup_timeout_error(exc, last_container, last_stage) from exc
        _finalize_sybase_database(
            service.container,
            initial_db=initial_db,
            user=sybase_user,
            password=sybase_password,
            enable_monitoring=enable_monitoring,
            init_sql=init_sql,
        )
        yield SybaseService(
            container=service.container,
            host=service.host,
            port=service.port,
            user=sybase_user,
            password=sybase_password,
            database=initial_db,
        )


@pytest.fixture(scope="session")
def sybase_image() -> str:
    """Docker image tag for SAP Sybase ASE."""
    return os.getenv("SYBASE_IMAGE", DEFAULT_SYBASE_IMAGE)


@pytest.fixture(scope="session")
def sybase_user() -> str:
    """Username for authenticating with the Sybase ASE container."""
    return os.getenv("SYBASE_USER", SYBASE_USER)


@pytest.fixture(scope="session")
def sybase_password() -> str:
    """Password for authenticating with the Sybase ASE container."""
    return os.getenv("SYBASE_PASSWORD", SYBASE_PASSWORD)


@pytest.fixture(scope="session")
def sybase_database() -> str:
    """Initial database name on the Sybase ASE container."""
    return os.getenv("SYBASE_DATABASE", SYBASE_DATABASE)


@pytest.fixture(scope="session")
def sybase_startup_timeout() -> int:
    """Maximum seconds to wait for Sybase ASE container startup."""
    return int(os.getenv("SYBASE_STARTUP_TIMEOUT", "300"))


@pytest.fixture(scope="session")
def sybase_enable_monitoring() -> bool:
    """Whether Sybase ASE enables ``mon*`` MDA monitoring tables automatically during startup."""
    return os.getenv("SYBASE_ENABLE_MONITORING", "false").strip().lower() in TRUE_VALUES


@pytest.fixture(scope="session")
def sybase_port() -> int | None:
    """Optional pinned host TCP port for Sybase ASE (``SYBASE_PORT``)."""
    return env_port("SYBASE_PORT")


@pytest.fixture(scope="session")
def xdist_sybase_isolation_level() -> XdistIsolationLevel:
    """Provide the pytest-xdist isolation level for Sybase ASE."""
    return "database"


@pytest.fixture(scope="session")
def sybase_service(
    container_service: ContainerService,
    sybase_image: str,
    sybase_user: str,
    sybase_password: str,
    sybase_database: str,
    sybase_startup_timeout: int,
    sybase_enable_monitoring: bool,
    sybase_port: int | None,
    xdist_sybase_isolation_level: XdistIsolationLevel,
) -> Generator[SybaseService, None, None]:
    """Provide a session-scoped Sybase ASE service container.

    Yields:
        A configured SybaseService instance.
    """
    with provide_sybase_service(
        container_service=container_service,
        sybase_image=sybase_image,
        sybase_user=sybase_user,
        sybase_password=sybase_password,
        sybase_database=sybase_database,
        sybase_startup_timeout=sybase_startup_timeout,
        enable_monitoring=sybase_enable_monitoring,
        host_port=sybase_port,
        xdist_sybase_isolation_level=xdist_sybase_isolation_level,
    ) as service:
        yield service


class _SybaseRunKwargs(TypedDict):
    image: str
    container_port: int
    name: str
    env: dict[str, str]
    check: Callable[[ServiceContainer], bool]
    timeout: int
    pause: float
    transient: bool
    host_port: NotRequired[int]


def _build_sybase_run_kwargs(
    *,
    sybase_image: str,
    name: str,
    sybase_password: str,
    extra_env: Mapping[str, str] | None,
    check: Callable[[ServiceContainer], bool],
    timeout: int,
    transient: bool,
    host_port: int | None,
) -> _SybaseRunKwargs:
    """Assemble keyword arguments forwarded to :meth:`ContainerService.run`."""
    container_env: dict[str, str] = {
        "SYBASE_PASSWORD": sybase_password,
        "SA_PASSWORD": sybase_password,
    }
    if extra_env:
        container_env.update(extra_env)
    kwargs: _SybaseRunKwargs = {
        "image": sybase_image,
        "container_port": SYBASE_PORT,
        "name": name,
        "env": container_env,
        "check": check,
        "timeout": timeout,
        "pause": 1.5,
        "transient": transient,
    }
    if host_port is not None:
        kwargs["host_port"] = host_port
    return kwargs


def _finalize_sybase_database(
    container: Container,
    *,
    initial_db: str,
    user: str,
    password: str,
    enable_monitoring: bool,
    init_sql: str | Path | Sequence[str | Path] | None,
) -> None:
    """Create worker database when needed, enable MDA monitoring if requested, and run ``init_sql``."""
    if initial_db != SYBASE_DATABASE:
        create_worker_database(container, initial_db, user=user, password=password)
    if enable_monitoring:
        configure_sybase_monitoring(container, user=user, password=password, grant_to=user)
    statements = read_init_scripts(init_sql)
    if not statements:
        return
    fingerprint = simple_string_hash("\ngo\n".join(statements))

    def _run() -> None:
        for statement in statements:
            code, output = exec_isql(container, statement, database=initial_db, user=user, password=password)
            if code != 0:
                detail = output.decode("utf-8", errors="replace").strip()
                msg = f"Sybase init_sql failed on database {initial_db!r} (exit {code}): {detail}"
                raise RuntimeError(msg)

    run_container_init_once(container, f"sybase:{initial_db}", fingerprint, _run)


def _resolve_sybase_database(sybase_database: str, worker_num: int | None, isolation_level: XdistIsolationLevel) -> str:
    """Return the database a Sybase ASE service uses for the current process.

    Under ``pytest-xdist`` with ``database`` isolation every worker gets ``<base>_<worker_num>``, where ``base`` is
    ``sybase_database``, or ``pytestdb`` when ``sybase_database`` is ``master``. Otherwise ``sybase_database`` is
    used as is.

    Args:
        sybase_database: Configured database name.
        worker_num: ``pytest-xdist`` worker number, or None outside xdist.
        isolation_level: Configured xdist isolation level.

    Returns:
        The validated database name.

    Raises:
        ValueError: If the resulting name is not a valid ASE identifier of at most 30 characters.
    """
    if worker_num is None or isolation_level != "database":
        return sybase_database if sybase_database == SYBASE_DATABASE else validate_sybase_database_name(sybase_database)
    base = SYBASE_WORKER_DATABASE if sybase_database == SYBASE_DATABASE else sybase_database
    return validate_sybase_database_name(f"{base}_{worker_num}")


def _is_sybase_ready(exit_code: int, output: bytes) -> bool:
    """Return whether ``isql`` output of the readiness query contains exactly the expected row.

    Args:
        exit_code: Exit code returned by ``exec_isql``.
        output: Output returned by ``exec_isql``.

    Returns:
        True when the query succeeded and one output line is exactly ``4242``.
    """
    if exit_code != 0:
        return False
    return any(line.strip() == _READINESS_ROW for line in output.decode("utf-8", errors="replace").splitlines())


def _sybase_startup_timeout_error(exc: ValueError, container: Container | None, stage: str) -> ValueError:
    """Attach container logs and ASE error log tail to a Sybase readiness timeout error.

    Args:
        exc: Original readiness timeout error.
        container: Sybase container instance captured during polling, if any.
        stage: Last readiness check stage reached (``port``, ``log``, or ``isql``).

    Returns:
        A ``ValueError`` with diagnostic details appended.
    """
    if container is None:
        return exc
    details = [str(exc), f"Last Sybase readiness stage: {stage}"]
    with suppress(Exception):
        container_logs = exec_output_to_bytes(container.logs(tail=40)).decode("utf-8", errors="replace").strip()
        if container_logs:
            details.append(f"Container logs (tail 40):\n{container_logs}")
    with suppress(Exception):
        diag = container.exec_run(["sh", "-c", f"ps -ef; tail -n 60 {_SYBASE_ERROR_LOG} 2>/dev/null || true"])
        diag_text = exec_output_to_bytes(diag.output).decode("utf-8", errors="replace").strip()
        if diag_text:
            details.append(f"Container diagnostics:\n{diag_text}")
    return ValueError("\n".join(details))
