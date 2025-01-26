from __future__ import annotations

from typing import TYPE_CHECKING

import pymssql
import pytest

if TYPE_CHECKING:
    import pyodbc

    from pytest_databases.docker.mssql import MSSQLService

pytest_plugins = [
    "pytest_databases.docker.mssql",
]


def check(service: MSSQLService) -> bool:
    conn = pymssql.connect(
        host=service.host,
        port=str(service.port),
        database=service.database,
        user=service.user,
        password=service.password,
        timeout=2,
    )
    with conn.cursor() as cursor:
        cursor.execute("select 1 as is_available")
        resp = cursor.fetchone()
        return resp[0] == 1 if resp is not None else False


def test_mssql_service(mssql_service: MSSQLService) -> None:
    ping = check(mssql_service)
    assert ping


def test_mssql_2022_services(mssql2022_service: MSSQLService) -> None:
    ping = check(mssql2022_service)
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


@pytest.mark.xfail(reason="no idea what's going on here")
def test_mssql2022_services_after_start(
    mssql2022_startup_connection: pyodbc.Connection,
) -> None:
    with mssql2022_startup_connection.cursor() as cursor:
        cursor.execute("CREATE view simple_table as SELECT 1 as the_value")
        cursor.execute("select * from simple_table")
        result = cursor.fetchall()
        assert bool(result is not None and result[0][0] == 1)
        cursor.execute("drop view simple_table")
