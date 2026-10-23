"""Microsoft SQL Server container service fixtures."""

from __future__ import annotations

import contextlib
import dataclasses
import time
from typing import TYPE_CHECKING

import pytest

from pytest_databases.helpers import exec_output_to_bytes, get_xdist_worker_num
from pytest_databases.types import ServiceContainer

if TYPE_CHECKING:
    from collections.abc import Generator

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


def exec_sqlcmd(
    container: Container,
    sql: str,
    *,
    database: str = "master",
    user: str = MSSQL_USER,
    password: str = MSSQL_PASSWORD,
) -> tuple[int, bytes]:
    """Execute a T-SQL statement inside a SQL Server container across sqlcmd tool generations.

    Returns:
        Tuple of (exit_code, output_bytes).
    """
    last_code = -1
    last_out = b""
    for binary, extra_flags in SQLCMD_CANDIDATES:
        result = container.exec_run([
            binary,
            *extra_flags,
            "-b",
            "-S",
            "localhost,1433",
            "-U",
            user,
            "-P",
            password,
            "-d",
            database,
            "-l",
            "2",
            "-h",
            "-1",
            "-W",
            "-Q",
            sql,
        ])
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


@contextlib.contextmanager
def provide_mssql_service(
    docker_service: DockerService,
    xdist_mssql_isolation_level: XdistIsolationLevel,
    image: str,
    name: str,
    mssql_user: str,
    mssql_password: str,
    mssql_database: str,
) -> Generator[MSSQLService, None, None]:
    """Start and manage a SQL Server container service.

    Yields:
        Active MSSQLService instance.
    """

    def check(_service: ServiceContainer) -> bool:
        exit_code, output = exec_sqlcmd(
            _service.container,
            "SET NOCOUNT ON; SELECT 1 AS is_available",
            password=mssql_password,
        )
        return exit_code == 0 and output.strip() == b"1"

    worker_num = get_xdist_worker_num()
    db_name = mssql_database
    if worker_num is not None:
        suffix = f"_{worker_num}"
        if xdist_mssql_isolation_level == "server":
            name += suffix
        else:
            db_name += suffix

    with docker_service.run(
        image=image,
        check=check,
        container_port=1433,
        name=name,
        env={
            "MSSQL_SA_PASSWORD": mssql_password,
            "MSSQL_PID": "Developer",
            "ACCEPT_EULA": "Y",
            "MSSQL_TCP_PORT": "1433",
        },
        timeout=100,
        pause=1,
        transient=xdist_mssql_isolation_level == "server",
    ) as service:
        _prepare_database(service.container, db_name, mssql_user, mssql_password)

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
    return MSSQL_USER


@pytest.fixture(scope="session")
def mssql_password() -> str:
    """Return the SQL Server SA password."""
    return MSSQL_PASSWORD


@pytest.fixture(scope="session")
def mssql_database() -> str:
    """Return the SQL Server database name."""
    return MSSQL_DATABASE


@pytest.fixture(autouse=False, scope="session")
def mssql_2022_service(
    docker_service: DockerService,
    xdist_mssql_isolation_level: XdistIsolationLevel,
    mssql_2022_image: str,
    mssql_user: str,
    mssql_password: str,
    mssql_database: str,
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
    ) as service:
        yield service


@pytest.fixture(autouse=False, scope="session")
def mssql_service(
    docker_service: DockerService,
    xdist_mssql_isolation_level: XdistIsolationLevel,
    mssql_image: str,
    mssql_user: str,
    mssql_password: str,
    mssql_database: str,
) -> Generator[MSSQLService, None, None]:
    """Provide the default SQL Server container service.

    Yields:
        Active MSSQLService instance.
    """
    with provide_mssql_service(
        docker_service=docker_service,
        xdist_mssql_isolation_level=xdist_mssql_isolation_level,
        image=mssql_image,
        name="mssql",
        mssql_user=mssql_user,
        mssql_password=mssql_password,
        mssql_database=mssql_database,
    ) as service:
        yield service


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
) -> None:
    """Ensure the SQL Server database and user exist and the database is ONLINE.

    Raises:
        RuntimeError: If the database does not reach ONLINE state within retries.
    """
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

    last_output = b""
    for attempt in range(10):
        for sql in setup_sql:
            exit_code, output = exec_sqlcmd(container, sql, password=password)
            if exit_code != 0:
                last_output = output
                break
        else:
            verify_code, verify_out = exec_sqlcmd(container, online_check_sql, password=password)
            if verify_code == 0 and verify_out.strip() == b"1":
                return
            last_output = verify_out
        time.sleep(1 + attempt * 0.5)

    msg = f"SQL Server database {database!r} could not be prepared. Last output: {last_output!r}"
    raise RuntimeError(msg)
