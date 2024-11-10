from __future__ import annotations

from typing import TYPE_CHECKING, Any

from pytest_databases.docker.mariadb import MariaDBService
from tests.docker.test_mysql import check




pytest_plugins = [
    "pytest_databases.docker.mariadb",
]


def test_mariadb_services(mariadb_service: MariaDBService) -> None:
    assert check(mariadb_service)


def test_mariadb_113_services(mariadb113_service: MariaDBService) -> None:
    assert check(mariadb113_service)


def test_mariadb_services_after_start(
    mariadb_startup_connection: Any,
) -> None:
    with mariadb_startup_connection.cursor() as cursor:
        cursor.execute("CREATE TABLE if not exists simple_table as SELECT 1 as the_value")
        cursor.execute("select * from simple_table")
        result = cursor.fetchall()
        assert bool(result is not None and result[0][0] == 1)


def test_mariadb113_services_after_start(
    mariadb113_startup_connection: Any,
) -> None:
    with mariadb113_startup_connection.cursor() as cursor:
        cursor.execute("CREATE TABLE if not exists simple_table as SELECT 1 as the_value")
        cursor.execute("select * from simple_table")
        result = cursor.fetchall()
        assert bool(result is not None and result[0][0] == 1)
