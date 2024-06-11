from __future__ import annotations

from typing import TYPE_CHECKING

import pytest

from pytest_databases.docker.mssql import mssql_responsive

if TYPE_CHECKING:
    import aioodbc

    from pytest_databases.docker import DockerServiceRegistry

pytestmark = pytest.mark.anyio
pytest_plugins = [
    "pytest_databases.docker.mssql",
]


async def test_mssql_default_config(
    default_mssql_service_name: str,
    mssql_port: int,
    mssql_database: str,
    mssql_user: str,
    mssql_password: str,
) -> None:
    assert default_mssql_service_name == "mssql2022"
    assert mssql_port == 4133
    assert mssql_database == "master"
    assert mssql_user == "sa"
    assert mssql_password == "Super-secret1"


async def test_mssql_2022_config(
    mssql2022_port: int,
    mssql_database: str,
    mssql_user: str,
    mssql_password: str,
) -> None:
    assert mssql2022_port == 4133
    assert mssql_database == "master"
    assert mssql_user == "sa"
    assert mssql_password == "Super-secret1"


async def test_mssql_services(
    mssql_docker_ip: str,
    mssql_service: DockerServiceRegistry,
    mssql_port: int,
    mssql_database: str,
    mssql_user: str,
    mssql_password: str,
) -> None:
    connstring = f"encrypt=no; TrustServerCertificate=yes; driver={{ODBC Driver 18 for SQL Server}}; server={mssql_docker_ip},{mssql_port}; database={mssql_database}; UID={mssql_user}; PWD={mssql_password}"

    ping = await mssql_responsive(mssql_docker_ip, connstring=connstring)
    assert ping


async def test_mssql_2022_services(
    mssql_docker_ip: str,
    mssql2022_service: DockerServiceRegistry,
    mssql2022_port: int,
    mssql_database: str,
    mssql_user: str,
    mssql_password: str,
) -> None:
    connstring = f"encrypt=no; TrustServerCertificate=yes; driver={{ODBC Driver 18 for SQL Server}}; server={mssql_docker_ip},{mssql2022_port}; database={mssql_database}; UID={mssql_user}; PWD={mssql_password}"

    ping = await mssql_responsive(mssql_docker_ip, connstring=connstring)
    assert ping


async def test_mssql_services_after_start(
    mssql_startup_connection: aioodbc.Connection,
) -> None:
    async with mssql_startup_connection.cursor() as cursor:
        await cursor.execute("CREATE view simple_table as SELECT 1 as the_value")
        await cursor.execute("select * from simple_table")
        result = await cursor.fetchall()
        assert bool(result is not None and result[0][0] == 1)
        await cursor.execute("drop view simple_table")


async def test_mssql2022_services_after_start(
    mssql2022_startup_connection: aioodbc.Connection,
) -> None:
    async with mssql2022_startup_connection.cursor() as cursor:
        await cursor.execute("CREATE view simple_table as SELECT 1 as the_value")
        await cursor.execute("select * from simple_table")
        result = await cursor.fetchall()
        assert bool(result is not None and result[0][0] == 1)
        await cursor.execute("drop view simple_table")
