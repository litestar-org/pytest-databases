from __future__ import annotations

import dataclasses
import time
from typing import TYPE_CHECKING

import pytest

from pytest_databases.helpers import get_xdist_worker_num
from pytest_databases.types import ServiceContainer

if TYPE_CHECKING:
    from collections.abc import Generator, Iterator

    from docker.models.containers import Container

    from pytest_databases._service import DockerService
    from pytest_databases.types import XdistIsolationLevel


MSSQL_USER = "sa"
MSSQL_PASSWORD = "Super-secret1"
MSSQL_DATABASE = "pytest_databases"
SQLCMD = "/opt/mssql-tools18/bin/sqlcmd"


def _output_to_bytes(output: bytes | str | Iterator[bytes]) -> bytes:
    if isinstance(output, bytes):
        return output
    if isinstance(output, str):
        return output.encode()
    return b"".join(output)


def _quote_identifier(value: str) -> str:
    return f"[{value.replace(']', ']]')}]"


def _quote_literal(value: str) -> str:
    return f"N'{value.replace(chr(39), chr(39) * 2)}'"


def _exec_sqlcmd(
    container: Container,
    sql: str,
    *,
    database: str = "master",
    user: str = MSSQL_USER,
    password: str = MSSQL_PASSWORD,
) -> tuple[int, bytes]:
    result = container.exec_run([
        SQLCMD,
        "-C",
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
    return result.exit_code if result.exit_code is not None else -1, _output_to_bytes(result.output)


def _make_login_sql(user: str, password: str) -> str:
    quoted_user = _quote_identifier(user)
    quoted_user_literal = _quote_literal(user)
    quoted_password = _quote_literal(password)
    return (
        f"IF SUSER_ID({quoted_user_literal}) IS NULL "
        f"CREATE LOGIN {quoted_user} WITH PASSWORD = {quoted_password}; "
        f"ELSE ALTER LOGIN {quoted_user} WITH PASSWORD = {quoted_password}, CHECK_POLICY = OFF;"
    )


def _make_database_sql(database: str) -> str:
    quoted_database = _quote_identifier(database)
    quoted_database_literal = _quote_literal(database)
    return f"IF DB_ID({quoted_database_literal}) IS NULL CREATE DATABASE {quoted_database};"


def _make_user_sql(database: str, user: str) -> str:
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
    setup_sql = [_make_database_sql(database)]
    if user != MSSQL_USER:
        setup_sql = [
            _make_login_sql(user, password),
            *setup_sql,
            _make_user_sql(database, user),
        ]

    last_output = b""
    for attempt in range(5):
        for sql in setup_sql:
            exit_code, output = _exec_sqlcmd(container, sql, password=password)
            if exit_code != 0:
                last_output = output
                break
        else:
            return
        time.sleep(1 + attempt * 0.5)

    msg = f"SQL Server database {database!r} could not be prepared. Last output: {last_output!r}"
    raise RuntimeError(msg)


@pytest.fixture(scope="session")
def xdist_mssql_isolation_level() -> XdistIsolationLevel:
    return "database"


@pytest.fixture(scope="session")
def mssql_image() -> str:
    return "mcr.microsoft.com/mssql/server:2022-latest"


@pytest.fixture(scope="session")
def mssql_user() -> str:
    return MSSQL_USER


@pytest.fixture(scope="session")
def mssql_password() -> str:
    return MSSQL_PASSWORD


@pytest.fixture(scope="session")
def mssql_database() -> str:
    return MSSQL_DATABASE


@dataclasses.dataclass
class MSSQLService(ServiceContainer):
    user: str
    password: str
    database: str

    @property
    def connection_string(self) -> str:
        return (
            "encrypt=no; "
            "TrustServerCertificate=yes; "
            f"driver={{ODBC Driver 18 for SQL Server}}; "
            f"server={self.host},{self.port}; "
            f"database={self.database}; "
            f"UID={self.user}; "
            f"PWD={self.password}"
        )


@pytest.fixture(autouse=False, scope="session")
def mssql_service(
    docker_service: DockerService,
    xdist_mssql_isolation_level: XdistIsolationLevel,
    mssql_image: str,
    mssql_user: str,
    mssql_password: str,
    mssql_database: str,
) -> Generator[MSSQLService, None, None]:
    def check(_service: ServiceContainer) -> bool:
        exit_code, output = _exec_sqlcmd(
            _service.container,
            "SET NOCOUNT ON; SELECT 1 AS is_available",
            password=mssql_password,
        )
        return exit_code == 0 and output.strip() == b"1"

    worker_num = get_xdist_worker_num()
    db_name = mssql_database
    name = "mssql"
    if worker_num is not None:
        suffix = f"_{worker_num}"
        if xdist_mssql_isolation_level == "server":
            name += suffix
        else:
            db_name += suffix

    with docker_service.run(
        image=mssql_image,
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
