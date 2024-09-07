from __future__ import annotations

from typing import TYPE_CHECKING, Any

from pytest_databases.docker.mysql import mysql_responsive

if TYPE_CHECKING:
    from pytest_databases.docker import DockerServiceRegistry

pytest_plugins = [
    "pytest_databases.docker.mysql",
]


def test_mysql_default_config(
    default_mysql_service_name: str,
    mysql_port: int,
    mysql_database: str,
    mysql_user: str,
    mysql_password: str,
) -> None:
    assert default_mysql_service_name == "mysql8"
    assert mysql_port == 3360
    assert mysql_database == "db"
    assert mysql_user == "app"
    assert mysql_password == "super-secret"


def test_mysql_8_config(
    mysql8_port: int,
    mysql_database: str,
    mysql_user: str,
    mysql_password: str,
) -> None:
    assert mysql8_port == 3360
    assert mysql_database == "db"
    assert mysql_user == "app"
    assert mysql_password == "super-secret"


def test_mysql_57_config(
    mysql57_port: int,
    mysql_database: str,
    mysql_user: str,
    mysql_password: str,
) -> None:
    assert mysql57_port == 3361
    assert mysql_database == "db"
    assert mysql_user == "app"
    assert mysql_password == "super-secret"


def test_mysql_56_config(
    mysql56_port: int,
    mysql_database: str,
    mysql_user: str,
    mysql_password: str,
) -> None:
    assert mysql56_port == 3362
    assert mysql_database == "db"
    assert mysql_user == "app"
    assert mysql_password == "super-secret"


def test_mysql_57_services(
    mysql_docker_ip: str,
    mysql57_service: DockerServiceRegistry,
    mysql57_port: int,
    mysql_database: str,
    mysql_user: str,
    mysql_password: str,
) -> None:
    ping = mysql_responsive(
        mysql_docker_ip,
        port=mysql57_port,
        database=mysql_database,
        user=mysql_user,
        password=mysql_password,
    )
    assert ping


def test_mysql_56_services(
    mysql_docker_ip: str,
    mysql56_service: DockerServiceRegistry,
    mysql56_port: int,
    mysql_database: str,
    mysql_user: str,
    mysql_password: str,
) -> None:
    ping = mysql_responsive(
        mysql_docker_ip,
        port=mysql56_port,
        database=mysql_database,
        user=mysql_user,
        password=mysql_password,
    )
    assert ping


def test_mysql_8_services(
    mysql_docker_ip: str,
    mysql8_service: DockerServiceRegistry,
    mysql8_port: int,
    mysql_database: str,
    mysql_user: str,
    mysql_password: str,
) -> None:
    ping = mysql_responsive(
        mysql_docker_ip,
        port=mysql8_port,
        database=mysql_database,
        user=mysql_user,
        password=mysql_password,
    )
    assert ping


def test_mysql_services_after_start(
    mysql_startup_connection: Any,
) -> None:
    with mysql_startup_connection.cursor() as cursor:
        cursor.execute("CREATE TABLE if not exists simple_table as SELECT 1 as the_value")
        cursor.execute("select * from simple_table")
        result = cursor.fetchall()
        assert bool(result is not None and result[0][0] == 1)


def test_mysql56_services_after_start(
    mysql56_startup_connection: Any,
) -> None:
    with mysql56_startup_connection.cursor() as cursor:
        cursor.execute("CREATE TABLE if not exists simple_table as SELECT 1 as the_value")
        cursor.execute("select * from simple_table")
        result = cursor.fetchall()
        assert bool(result is not None and result[0][0] == 1)


def test_mysql57_services_after_start(
    mysql57_startup_connection: Any,
) -> None:
    with mysql57_startup_connection.cursor() as cursor:
        cursor.execute("CREATE TABLE if not exists simple_table as SELECT 1 as the_value")
        cursor.execute("select * from simple_table")
        result = cursor.fetchall()
        assert bool(result is not None and result[0][0] == 1)


def test_mysql8_services_after_start(
    mysql8_startup_connection: Any,
) -> None:
    with mysql8_startup_connection.cursor() as cursor:
        cursor.execute("CREATE TABLE if not exists simple_table as SELECT 1 as the_value")
        cursor.execute("select * from simple_table")
        result = cursor.fetchall()
        assert bool(result is not None and result[0][0] == 1)
