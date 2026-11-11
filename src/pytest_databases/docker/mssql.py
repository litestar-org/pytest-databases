"""Microsoft SQL Server container service fixtures."""

from __future__ import annotations

import contextlib
import dataclasses
import os
import re
import tempfile
import time
import uuid
from pathlib import Path
from typing import TYPE_CHECKING

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
from pytest_databases.types import ServiceContainer, copy_to_container

if TYPE_CHECKING:
    from collections.abc import Generator, Mapping, Sequence

    from docker.models.containers import Container

    from pytest_databases._service import DockerService
    from pytest_databases.types import XdistIsolationLevel

__all__ = [
    "MSSQL_DATABASE",
    "MSSQL_PASSWORD",
    "MSSQL_USER",
    "SQLCMD",
    "SQLCMD_CANDIDATES",
    "MSSQLService",
    "exec_sqlcmd",
    "mssql_2022_image",
    "mssql_2022_service",
    "mssql_2025_image",
    "mssql_2025_service",
    "mssql_database",
    "mssql_image",
    "mssql_password",
    "mssql_port",
    "mssql_service",
    "mssql_user",
    "provide_mssql_service",
    "xdist_mssql_isolation_level",
]

MSSQL_USER = "sa"
MSSQL_PASSWORD = "Super-secret1"
MSSQL_DATABASE = "pytest_databases"
SQLCMD = "/opt/mssql-tools18/bin/sqlcmd"
SQLCMD_CANDIDATES: tuple[tuple[str, tuple[str, ...]], ...] = (
    ("/opt/mssql-tools18/bin/sqlcmd", ("-C",)),
    ("/opt/mssql-tools/bin/sqlcmd", ()),
    ("sqlcmd", ("-C",)),
    ("sqlcmd", ()),
)
_GO_BATCH_RE = re.compile(r"^\s*GO(?:\s+\d+)?\s*(?:--.*)?$", re.IGNORECASE | re.MULTILINE)
_STAGED_SCRIPT_DIR = "/var/opt/mssql"


@dataclasses.dataclass
class MSSQLService(ServiceContainer):
    """Service handle for a running SQL Server container."""

    user: str
    password: str
    database: str

    @property
    def connection_string(self) -> str:
        """ODBC connection string for this SQL Server container."""
        return (
            "encrypt=no; "
            "TrustServerCertificate=yes; "
            f"driver={{ODBC Driver 18 for SQL Server}}; "
            f"server={self.host},{self.port}; "
            f"database={self.database}; "
            f"UID={self.user}; "
            f"PWD={self.password}"
        )

    def exec_sql(
        self,
        sql: str | None = None,
        *,
        sql_file: str | Path | None = None,
        database: str | None = None,
        user: str | None = None,
        password: str | None = None,
        query_timeout: int | None = None,
    ) -> tuple[int, bytes]:
        """Execute single- or multi-batch T-SQL via ``sqlcmd`` inside this container.

        Returns:
            Tuple of ``(exit_code, output_bytes)``.
        """
        return exec_sqlcmd(
            self.container,
            sql,
            sql_file=sql_file,
            database=self.database if database is None else database,
            user=self.user if user is None else user,
            password=self.password if password is None else password,
            query_timeout=query_timeout,
        )


def exec_sqlcmd(
    container: Container,
    sql: str | None = None,
    *,
    sql_file: str | Path | None = None,
    database: str = "master",
    user: str = MSSQL_USER,
    password: str = MSSQL_PASSWORD,
    query_timeout: int | None = None,
) -> tuple[int, bytes]:
    """Execute T-SQL inside a SQL Server container across ``sqlcmd`` tool generations.

    Non-empty passwords are supplied via ``SQLCMDPASSWORD`` so credentials are not exposed on
    the command line. Multi-batch scripts containing standalone ``GO`` separators or ``sql_file``
    paths are staged into ``/var/opt/mssql`` with ``0600`` permissions and executed via ``-i``,
    removing the temporary script on completion.

    Args:
        container: Running SQL Server container handle.
        sql: Inline T-SQL string (mutually exclusive with ``sql_file``).
        sql_file: Host ``.sql`` file path to copy and execute (mutually exclusive with ``sql``).
        database: Target database passed to ``-d``.
        user: Login passed to ``-U``.
        password: Login password supplied via ``SQLCMDPASSWORD`` (or ``-P ""`` when empty).
        query_timeout: Optional query timeout in seconds passed to ``-t``.

    Returns:
        Tuple of ``(exit_code, output_bytes)``.

    Raises:
        ValueError: If neither or both of ``sql`` and ``sql_file`` are given, or ``query_timeout < 0``.
    """
    if (sql is None) == (sql_file is None):
        msg = "Provide exactly one of 'sql' or 'sql_file' to exec_sqlcmd."
        raise ValueError(msg)
    if query_timeout is not None and query_timeout < 0:
        msg = f"query_timeout must be >= 0, got {query_timeout}."
        raise ValueError(msg)

    if sql_file is not None:
        return _exec_staged_sqlcmd(
            container,
            Path(sql_file),
            database=database,
            user=user,
            password=password,
            query_timeout=query_timeout,
        )
    if sql is None:
        msg = "Provide 'sql' or 'sql_file' to exec_sqlcmd."
        raise ValueError(msg)
    if _GO_BATCH_RE.search(sql):
        with tempfile.TemporaryDirectory(prefix="pytest-databases-mssql-") as tmp_dir:
            staged_host_file = Path(tmp_dir) / "batch.sql"
            staged_host_file.write_text(sql, encoding="utf-8")
            return _exec_staged_sqlcmd(
                container,
                staged_host_file,
                database=database,
                user=user,
                password=password,
                query_timeout=query_timeout,
            )
    return _run_sqlcmd_candidates(
        container,
        mode_args=("-Q", sql),
        database=database,
        user=user,
        password=password,
        query_timeout=query_timeout,
    )


@contextlib.contextmanager
def provide_mssql_service(
    docker_service: DockerService,
    xdist_mssql_isolation_level: XdistIsolationLevel,
    image: str,
    name: str,
    mssql_user: str,
    mssql_password: str,
    mssql_database: str,
    *,
    host_port: int | None = None,
    env: Mapping[str, str] | None = None,
    mem_limit: str | None = None,
    shm_size: int | str | None = None,
    init_sql: str | Path | Sequence[str | Path] | None = None,
    timeout: int = 180,
    pause: float = 1.0,
) -> Generator[MSSQLService, None, None]:
    """Start and manage a SQL Server container service.

    Readiness verifies both an in-container ``sqlcmd`` query and host TCP reachability. Optional
    ``env`` values (such as ``MSSQL_AGENT_ENABLED="true"``, ``MSSQL_PID``, or ``MSSQL_COLLATION``)
    merge over the default container environment, and ``init_sql`` runs once per database.

    Yields:
        Active :class:`MSSQLService` instance.
    """
    resolved_name, db_name = _resolve_mssql_targets(name, mssql_database, xdist_mssql_isolation_level)
    sa_password = str(env["MSSQL_SA_PASSWORD"]) if env and "MSSQL_SA_PASSWORD" in env else mssql_password

    def check(_service: ServiceContainer) -> bool:
        exit_code, output = exec_sqlcmd(
            _service.container,
            "SET NOCOUNT ON; SELECT 1 AS is_available",
            password=sa_password,
        )
        return exit_code == 0 and output.strip() == b"1" and tcp_port_open(_service.host, _service.port)

    container_env: dict[str, str] = {
        "MSSQL_SA_PASSWORD": mssql_password,
        "MSSQL_PID": "Developer",
        "ACCEPT_EULA": "Y",
        "MSSQL_TCP_PORT": "1433",
    }
    if env:
        container_env.update(env)

    with docker_service.run(
        image=image,
        check=check,
        container_port=1433,
        name=resolved_name,
        env=container_env,
        timeout=timeout,
        pause=pause,
        transient=xdist_mssql_isolation_level == "server",
        host_port=host_port,
        mem_limit=mem_limit,
        shm_size=shm_size,
    ) as service:
        _prepare_database(service.container, db_name, mssql_user, mssql_password, sa_password=sa_password)
        _apply_mssql_init_sql(service.container, db_name=db_name, sa_password=sa_password, init_sql=init_sql)

        yield MSSQLService(
            host=service.host,
            port=service.port,
            container=service.container,
            database=db_name,
            user=mssql_user,
            password=mssql_password,
        )


@pytest.fixture(scope="session")
def xdist_mssql_isolation_level() -> XdistIsolationLevel:
    """Return the pytest-xdist isolation level for SQL Server."""
    return "database"


@pytest.fixture(scope="session")
def mssql_2022_image() -> str:
    """Return the SQL Server 2022 container image."""
    return "mcr.microsoft.com/mssql/server:2022-latest"


@pytest.fixture(scope="session")
def mssql_2025_image() -> str:
    """Return the SQL Server 2025 container image."""
    return "mcr.microsoft.com/mssql/server:2025-latest"


@pytest.fixture(scope="session")
def mssql_image(mssql_2022_image: str) -> str:
    """Return the default SQL Server container image."""
    return mssql_2022_image


@pytest.fixture(scope="session")
def mssql_user() -> str:
    """Return the SQL Server user."""
    return os.getenv("MSSQL_USER", MSSQL_USER)


@pytest.fixture(scope="session")
def mssql_password() -> str:
    """Return the SQL Server SA password."""
    return os.getenv("MSSQL_PASSWORD", MSSQL_PASSWORD)


@pytest.fixture(scope="session")
def mssql_database() -> str:
    """Return the SQL Server database name."""
    return os.getenv("MSSQL_DATABASE", MSSQL_DATABASE)


@pytest.fixture(scope="session")
def mssql_port() -> int | None:
    """Return an optional pinned host port for SQL Server containers from ``MSSQL_PORT``."""
    return env_port("MSSQL_PORT")


@pytest.fixture(autouse=False, scope="session")
def mssql_2022_service(
    docker_service: DockerService,
    xdist_mssql_isolation_level: XdistIsolationLevel,
    mssql_2022_image: str,
    mssql_user: str,
    mssql_password: str,
    mssql_database: str,
    mssql_port: int | None,
) -> Generator[MSSQLService, None, None]:
    """Provide a running SQL Server 2022 container service.

    Yields:
        Active MSSQLService instance.
    """
    with provide_mssql_service(
        docker_service=docker_service,
        xdist_mssql_isolation_level=xdist_mssql_isolation_level,
        image=mssql_2022_image,
        name="mssql-2022",
        mssql_user=mssql_user,
        mssql_password=mssql_password,
        mssql_database=mssql_database,
        host_port=mssql_port,
    ) as service:
        yield service


@pytest.fixture(autouse=False, scope="session")
def mssql_2025_service(
    docker_service: DockerService,
    xdist_mssql_isolation_level: XdistIsolationLevel,
    mssql_2025_image: str,
    mssql_user: str,
    mssql_password: str,
    mssql_database: str,
    mssql_port: int | None,
) -> Generator[MSSQLService, None, None]:
    """Provide a running SQL Server 2025 container service.

    Yields:
        Active MSSQLService instance.
    """
    with provide_mssql_service(
        docker_service=docker_service,
        xdist_mssql_isolation_level=xdist_mssql_isolation_level,
        image=mssql_2025_image,
        name="mssql-2025",
        mssql_user=mssql_user,
        mssql_password=mssql_password,
        mssql_database=mssql_database,
        host_port=mssql_port,
    ) as service:
        yield service


@pytest.fixture(autouse=False, scope="session")
def mssql_service(
    docker_service: DockerService,
    xdist_mssql_isolation_level: XdistIsolationLevel,
    mssql_image: str,
    mssql_2022_image: str,
    mssql_user: str,
    mssql_password: str,
    mssql_database: str,
    mssql_port: int | None,
) -> Generator[MSSQLService, None, None]:
    """Provide the default SQL Server container service.

    When ``mssql_image`` matches ``mssql_2022_image`` the service reuses the
    ``mssql_2022_service`` container instead of starting a second SQL Server 2022 instance.

    Yields:
        Active MSSQLService instance.
    """
    with provide_mssql_service(
        docker_service=docker_service,
        xdist_mssql_isolation_level=xdist_mssql_isolation_level,
        image=mssql_image,
        name="mssql-2022" if mssql_image == mssql_2022_image else "mssql",
        mssql_user=mssql_user,
        mssql_password=mssql_password,
        mssql_database=mssql_database,
        host_port=mssql_port,
    ) as service:
        yield service


def _exec_staged_sqlcmd(
    container: Container,
    source_path: Path,
    *,
    database: str,
    user: str,
    password: str,
    query_timeout: int | None,
) -> tuple[int, bytes]:
    """Upload ``source_path`` into ``/var/opt/mssql``, execute via ``sqlcmd -i``, and remove it."""
    arcname = f"ptdb_{uuid.uuid4().hex}.sql"
    remote_path = f"{_STAGED_SCRIPT_DIR}/{arcname}"
    try:
        copy_to_container(container, source_path, _STAGED_SCRIPT_DIR, arcname=arcname, mode=0o600)
    except (APIError, NotFound, OSError, RuntimeError) as exc:
        return -1, str(exc).encode()
    try:
        return _run_sqlcmd_candidates(
            container,
            mode_args=("-i", remote_path),
            database=database,
            user=user,
            password=password,
            query_timeout=query_timeout,
        )
    finally:
        with contextlib.suppress(APIError, NotFound):
            container.exec_run(["rm", "-f", remote_path])


def _run_sqlcmd_candidates(
    container: Container,
    *,
    mode_args: tuple[str, str],
    database: str,
    user: str,
    password: str,
    query_timeout: int | None,
) -> tuple[int, bytes]:
    """Run ``sqlcmd`` across candidate installation paths with ``SQLCMDPASSWORD`` env isolation."""
    auth_args = ("-P", "") if password == "" else ()
    env = {"SQLCMDPASSWORD": password} if password != "" else None
    timeout_args = ("-t", str(query_timeout)) if query_timeout is not None else ()
    last_code = -1
    last_out = b""
    for binary, extra_flags in SQLCMD_CANDIDATES:
        cmd = [
            binary,
            *extra_flags,
            "-b",
            "-S",
            "localhost,1433",
            "-U",
            user,
            *auth_args,
            "-d",
            database,
            "-l",
            "2",
            *timeout_args,
            "-h",
            "-1",
            "-W",
            *mode_args,
        ]
        try:
            result = container.exec_run(cmd, environment=env)
        except (APIError, NotFound) as exc:
            return -1, str(exc).encode()
        code = result.exit_code if result.exit_code is not None else -1
        out = exec_output_to_bytes(result.output)
        if code == 0:
            return code, out
        last_code = code
        last_out = out
        lower_out = out.lower()
        if (
            code not in {126, 127}
            and b"executable file not found" not in lower_out
            and b"no such file" not in lower_out
        ):
            return code, out
    return last_code, last_out


def _resolve_mssql_targets(
    name: str,
    base_db: str,
    isolation_level: XdistIsolationLevel,
) -> tuple[str, str]:
    """Compute container logical name and target database name for the active xdist worker."""
    worker_num = get_xdist_worker_num()
    if worker_num is None:
        return name, base_db
    suffix = f"_{worker_num}"
    if isolation_level == "server":
        return f"{name}{suffix}", base_db
    return name, f"{base_db}{suffix}"


def _quote_identifier(value: str) -> str:
    """Quote a SQL Server bracketed identifier."""
    return f"[{value.replace(']', ']]')}]"


def _quote_literal(value: str) -> str:
    """Quote a SQL Server Unicode string literal."""
    return f"N'{value.replace(chr(39), chr(39) * 2)}'"


def _make_login_sql(user: str, password: str) -> str:
    """Build T-SQL to create or update a SQL Server login."""
    quoted_user = _quote_identifier(user)
    quoted_user_literal = _quote_literal(user)
    quoted_password = _quote_literal(password)
    return (
        f"IF SUSER_ID({quoted_user_literal}) IS NULL "
        f"CREATE LOGIN {quoted_user} WITH PASSWORD = {quoted_password}; "
        f"ELSE ALTER LOGIN {quoted_user} WITH PASSWORD = {quoted_password}, CHECK_POLICY = OFF;"
    )


def _make_database_sql(database: str) -> str:
    """Build T-SQL to create a SQL Server database if it does not exist."""
    quoted_database = _quote_identifier(database)
    quoted_database_literal = _quote_literal(database)
    return f"IF DB_ID({quoted_database_literal}) IS NULL CREATE DATABASE {quoted_database};"


def _make_user_sql(database: str, user: str) -> str:
    """Build T-SQL to provision a database user and grant db_owner membership."""
    quoted_database = _quote_identifier(database)
    quoted_user = _quote_identifier(user)
    quoted_user_literal = _quote_literal(user)
    return (
        f"USE {quoted_database}; "
        f"IF USER_ID({quoted_user_literal}) IS NULL CREATE USER {quoted_user} FOR LOGIN {quoted_user}; "
        f"IF IS_ROLEMEMBER(N'db_owner', {quoted_user_literal}) = 0 "
        f"ALTER ROLE db_owner ADD MEMBER {quoted_user};"
    )


def _prepare_database(
    container: Container,
    database: str,
    user: str,
    password: str,
    *,
    sa_password: str | None = None,
) -> None:
    """Ensure the SQL Server database and user exist and the database is ONLINE.

    Raises:
        RuntimeError: If the database does not reach ONLINE state within retries.
    """
    admin_pw = password if sa_password is None else sa_password
    setup_sql = [_make_database_sql(database)]
    if user != MSSQL_USER:
        setup_sql = [
            _make_login_sql(user, password),
            *setup_sql,
            _make_user_sql(database, user),
        ]

    quoted_db = _quote_literal(database)
    online_check_sql = (
        f"SET NOCOUNT ON; SELECT 1 FROM sys.databases WHERE name = {quoted_db} AND state_desc = N'ONLINE';"
    )
    container_id = getattr(container, "id", None)
    lock_cm: contextlib.AbstractContextManager[object]
    if isinstance(container_id, str) and container_id:
        lock_path = Path(tempfile.gettempdir()) / f"pytest-databases-mssql-{container_id[:12]}.lock"
        lock_cm = filelock.FileLock(str(lock_path), timeout=120)
    else:
        lock_cm = contextlib.nullcontext()

    last_output = b""
    with lock_cm:
        for attempt in range(15):
            for sql in setup_sql:
                exit_code, output = exec_sqlcmd(container, sql, password=admin_pw)
                if exit_code != 0:
                    last_output = output
                    break
            else:
                verify_code, verify_out = exec_sqlcmd(container, online_check_sql, password=admin_pw)
                if verify_code == 0 and verify_out.strip() == b"1":
                    return
                last_output = verify_out
            time.sleep(1 + attempt * 0.5)

    msg = f"SQL Server database {database!r} could not be prepared. Last output: {last_output!r}"
    raise RuntimeError(msg)


def _apply_mssql_init_sql(
    container: Container,
    *,
    db_name: str,
    sa_password: str,
    init_sql: str | Path | Sequence[str | Path] | None,
) -> None:
    """Execute ``init_sql`` scripts once per ``(container, db_name)`` as ``sa``."""
    statements = read_init_scripts(init_sql)
    if not statements:
        return
    fingerprint = simple_string_hash("\nGO\n".join(statements))

    def _run() -> None:
        for statement in statements:
            code, output = exec_sqlcmd(
                container,
                statement,
                database=db_name,
                user=MSSQL_USER,
                password=sa_password,
            )
            if code != 0:
                detail = output.decode(errors="replace").strip()
                msg = f"SQL Server init_sql failed on database {db_name!r} (exit {code}): {detail}"
                raise RuntimeError(msg)

    run_container_init_once(container, f"mssql:{db_name}", fingerprint, _run)
