from __future__ import annotations

from typing import TYPE_CHECKING, Any

import pytest

from pytest_databases.docker.mariadb import mariadb_responsive

if TYPE_CHECKING:
    from pytest_databases.docker import DockerServiceRegistry

pytestmark = pytest.mark.anyio
pytest_plugins = [
    "pytest_databases.docker.mariadb",
]


async def test_mariadb_default_config(
    default_mariadb_service_name: str,
    mariadb_port: int,
    mariadb_database: str,
    mariadb_user: str,
    mariadb_password: str,
) -> None:
    assert default_mariadb_service_name == "mariadb113"
    assert mariadb_port == 3359
    assert mariadb_database == "db"
    assert mariadb_user == "app"
    assert mariadb_password == "super-secret"


async def test_mariadb_113_config(
    mariadb113_port: int,
    mariadb_database: str,
    mariadb_user: str,
    mariadb_password: str,
) -> None:
    assert mariadb113_port == 3359
    assert mariadb_database == "db"
    assert mariadb_user == "app"
    assert mariadb_password == "super-secret"


async def test_mariadb_services(
    mariadb_docker_ip: str,
    mariadb_service: DockerServiceRegistry,
    mariadb_port: int,
    mariadb_database: str,
    mariadb_user: str,
    mariadb_password: str,
) -> None:
    ping = await mariadb_responsive(
        mariadb_docker_ip,
        port=mariadb_port,
        database=mariadb_database,
        user=mariadb_user,
        password=mariadb_password,
    )
    assert ping


async def test_mariadb_113_services(
    mariadb_docker_ip: str,
    mariadb113_service: DockerServiceRegistry,
    mariadb113_port: int,
    mariadb_database: str,
    mariadb_user: str,
    mariadb_password: str,
) -> None:
    ping = await mariadb_responsive(
        mariadb_docker_ip,
        port=mariadb113_port,
        database=mariadb_database,
        user=mariadb_user,
        password=mariadb_password,
    )
    assert ping


async def test_mariadb_services_after_start(
    mariadb_startup_connection: Any,
) -> None:
    async with mariadb_startup_connection.cursor() as cursor:
        await cursor.execute("CREATE TABLE if not exists simple_table as SELECT 1 as the_value")
        await cursor.execute("select * from simple_table")
        result = await cursor.fetchall()
        assert bool(result is not None and result[0][0] == 1)


async def test_mariadb113_services_after_start(
    mariadb113_startup_connection: Any,
) -> None:
    async with mariadb113_startup_connection.cursor() as cursor:
        await cursor.execute("CREATE TABLE if not exists simple_table as SELECT 1 as the_value")
        await cursor.execute("select * from simple_table")
        result = await cursor.fetchall()
        assert bool(result is not None and result[0][0] == 1)
