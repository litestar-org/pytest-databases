from __future__ import annotations

import dataclasses
from typing import TYPE_CHECKING

import pymssql
import pytest

from pytest_databases.helpers import get_xdist_worker_num
from pytest_databases.types import ServiceContainer, XdistIsolationLevel

if TYPE_CHECKING:
    from collections.abc import Generator

    from pytest_databases._service import DockerService


@pytest.fixture(scope="session")
def xdist_mssql_isolation_level() -> XdistIsolationLevel:
    return "database"


@pytest.fixture(scope="session")
def mssql_image() -> str:
    return "mcr.microsoft.com/mssql/server:2022-latest"


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
) -> Generator[MSSQLService, None, None]:
    password = "Super-secret1"

    def check(_service: ServiceContainer) -> bool:
        try:
            with pymssql.connect(
                user="sa",
                password=password,
                database="master",
                host=_service.host,
                port=str(_service.port),
                timeout=2,
            ) as conn, conn.cursor() as cursor:
                cursor.execute("select 1 as is_available")
                resp = cursor.fetchone()
            return resp[0] == 1 if resp is not None else False
        except Exception:  # noqa: BLE001
            return False

    worker_num = get_xdist_worker_num()
    db_name = "pytest_databases"
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
            "SA_PASSWORD": password,
            "MSSQL_PID": "Developer",
            "ACCEPT_EULA": "Y",
            "MSSQL_TCP_PORT": "1433",
        },
        timeout=100,
        pause=1,
        transient=xdist_mssql_isolation_level == "server",
    ) as service:
        with pymssql.connect(
            user="sa",
            password=password,
            database="master",
            host=service.host,
            port=str(service.port),
            timeout=2,
            autocommit=True,
        ) as conn, conn.cursor() as cursor:
            cursor.execute(f"CREATE DATABASE {db_name}")

        yield MSSQLService(
            database=db_name,
            host=service.host,
            port=service.port,
            user="sa",
            password=password,
        )


@pytest.fixture(autouse=False, scope="session")
def mssql_connection(mssql_service: MSSQLService) -> Generator[pymssql.Connection, None, None]:
    with pymssql.connect(
        host=mssql_service.host,
        port=str(mssql_service.port),
        database=mssql_service.database,
        user=mssql_service.user,
        password=mssql_service.password,
        timeout=2,
    ) as db_connection:
        yield db_connection
