from __future__ import annotations

from typing import TYPE_CHECKING

from pytest_databases.docker.mssql import mssql_responsive

if TYPE_CHECKING:
    import pyodbc

    from pytest_databases.docker import DockerServiceRegistry

pytest_plugins = [
    "pytest_databases.docker.mssql",
]


def test_mssql_default_config(
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


def test_mssql_2022_config(
    mssql2022_port: int,
    mssql_database: str,
    mssql_user: str,
    mssql_password: str,
) -> None:
    assert mssql2022_port == 4133
    assert mssql_database == "master"
    assert mssql_user == "sa"
    assert mssql_password == "Super-secret1"


def test_mssql_services(
    mssql_docker_ip: str,
    mssql_service: DockerServiceRegistry,
    mssql_port: int,
    mssql_database: str,
    mssql_user: str,
    mssql_password: str,
) -> None:
    ping = mssql_responsive(
        mssql_docker_ip,
        port=mssql_port,
        database=mssql_database,
        user=mssql_user,
        password=mssql_password,
    )
    assert ping


def test_mssql_2022_services(
    mssql_docker_ip: str,
    mssql2022_service: DockerServiceRegistry,
    mssql2022_port: int,
    mssql_database: str,
    mssql_user: str,
    mssql_password: str,
) -> None:
    ping = mssql_responsive(
        mssql_docker_ip,
        port=mssql2022_port,
        database=mssql_database,
        user=mssql_user,
        password=mssql_password,
    )
    assert ping


def test_mssql_services_after_start(
    mssql_startup_connection: pyodbc.Connection,
) -> None:
    with mssql_startup_connection.cursor() as cursor:
        cursor.execute("CREATE view simple_table as SELECT 1 as the_value")
        cursor.execute("select * from simple_table")
        result = cursor.fetchall()
        assert bool(result is not None and result[0][0] == 1)
        cursor.execute("drop view simple_table")


async def test_mssql2022_services_after_start(
    mssql2022_startup_connection: pyodbc.Connection,
) -> None:
    with mssql2022_startup_connection.cursor() as cursor:
        cursor.execute("CREATE view simple_table as SELECT 1 as the_value")
        cursor.execute("select * from simple_table")
        result = cursor.fetchall()
        assert bool(result is not None and result[0][0] == 1)
        cursor.execute("drop view simple_table")
