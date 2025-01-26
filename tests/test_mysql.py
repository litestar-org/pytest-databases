from __future__ import annotations

from typing import TYPE_CHECKING

import pymysql

if TYPE_CHECKING:
    from pytest_databases.docker.mysql import MySQLService

pytest_plugins = [
    "pytest_databases.docker.mysql",
]


def check(service: MySQLService) -> bool:
    with pymysql.connect(
        host=service.host,
        port=service.port,
        user=service.user,
        database=service.db,
        password=service.password,
    ) as conn, conn.cursor() as cursor:
        cursor.execute("select 1 as is_available")
        resp = cursor.fetchone()
    return resp is not None and resp[0] == 1


def test_mysql_56_service(mysql56_service: MySQLService) -> None:
    assert check(mysql56_service)


def test_mysql_57_service(mysql57_service: MySQLService) -> None:
    assert check(mysql57_service)


def test_mysql_8_service(mysql8_service: MySQLService) -> None:
    assert check(mysql8_service)


def test_mysql_service(mysql_service: MySQLService) -> None:
    assert check(mysql_service)


def test_mysql_service_after_start(mysql_startup_connection: pymysql.Connection) -> None:
    with mysql_startup_connection.cursor() as cursor:
        cursor.execute("CREATE TABLE if not exists simple_table as SELECT 1 as the_value")
        cursor.execute("select * from simple_table")
        result = cursor.fetchall()
        assert bool(result is not None and result[0][0] == 1)


def test_mysql56_services_after_start(mysql56_startup_connection: pymysql.Connection) -> None:
    with mysql56_startup_connection.cursor() as cursor:
        cursor.execute("CREATE TABLE if not exists simple_table as SELECT 1 as the_value")
        cursor.execute("select * from simple_table")
        result = cursor.fetchall()
        assert bool(result is not None and result[0][0] == 1)


def test_mysql57_services_after_start(mysql57_startup_connection: pymysql.Connection) -> None:
    with mysql57_startup_connection.cursor() as cursor:
        cursor.execute("CREATE TABLE if not exists simple_table as SELECT 1 as the_value")
        cursor.execute("select * from simple_table")
        result = cursor.fetchall()
        assert bool(result is not None and result[0][0] == 1)


def test_mysql8_services_after_start(mysql8_startup_connection: pymysql.Connection) -> None:
    with mysql8_startup_connection.cursor() as cursor:
        cursor.execute("CREATE TABLE if not exists simple_table as SELECT 1 as the_value")
        cursor.execute("select * from simple_table")
        result = cursor.fetchall()
        assert bool(result is not None and result[0][0] == 1)
