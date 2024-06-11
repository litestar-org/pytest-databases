from __future__ import annotations

from typing import TYPE_CHECKING

import oracledb
import pytest

if TYPE_CHECKING:
    from pytest_databases.docker import DockerServiceRegistry

pytestmark = pytest.mark.anyio
pytest_plugins = [
    "pytest_databases.docker.oracle",
]


def test_oracle18c_default_config(
    oracle_user: str, oracle_password: str, oracle18c_service_name: str, oracle18c_port: int
) -> None:
    assert oracle_user == "app"
    assert oracle_password == "super-secret"
    assert oracle18c_service_name == "xepdb1"
    assert oracle18c_port == 1514


def test_oracle23c_default_config(
    oracle_user: str, oracle_password: str, oracle23c_service_name: str, oracle23c_port: int
) -> None:
    assert oracle_user == "app"
    assert oracle_password == "super-secret"
    assert oracle23c_service_name == "FREEPDB1"
    assert oracle23c_port == 1513


def test_oracle_default_config(
    oracle_user: str,
    oracle_password: str,
    oracle_service_name: str,
    oracle_port: int,
    oracle23c_port: int,
    default_oracle_service_name: str,
) -> None:
    assert default_oracle_service_name == "oracle23c"
    assert oracle_user == "app"
    assert oracle_password == "super-secret"
    assert oracle_service_name == "FREEPDB1"
    assert oracle_port == 1513
    assert oracle_port == oracle23c_port


async def test_oracle18c_service(
    oracle_docker_ip: str,
    oracle18c_service: DockerServiceRegistry,
    oracle18c_service_name: str,
    oracle18c_port: int,
    oracle_user: str,
    oracle_password: str,
) -> None:
    conn = oracledb.connect(
        user=oracle_user,
        password=oracle_password,
        dsn=f"{oracle_docker_ip}:{oracle18c_port!s}/{oracle18c_service_name}",
    )
    with conn.cursor() as cur:
        cur.execute("SELECT 'Hello World!' FROM dual")
        res = cur.fetchall()[0][0]
        assert "Hello World!" in res


async def test_oracle23c_service(
    oracle_docker_ip: str,
    oracle23c_service: DockerServiceRegistry,
    oracle23c_service_name: str,
    oracle23c_port: int,
    oracle_user: str,
    oracle_password: str,
) -> None:
    conn = oracledb.connect(
        user=oracle_user,
        password=oracle_password,
        dsn=f"{oracle_docker_ip}:{oracle23c_port!s}/{oracle23c_service_name}",
    )
    with conn.cursor() as cur:
        cur.execute("SELECT 'Hello World!' FROM dual")
        res = cur.fetchall()[0][0]
        assert "Hello World!" in res


async def test_oracle_services_after_start(
    oracle_startup_connection: oracledb.AsyncConnection,
) -> None:
    async with oracle_startup_connection.cursor() as cursor:
        await cursor.execute("CREATE or replace view simple_table as SELECT 1 as the_value from dual")
        await cursor.execute("select * from simple_table")
        result = await cursor.fetchall()
        assert bool(result is not None and result[0][0] == 1)


async def test_oracle18c_services_after_start(
    oracle18c_startup_connection: oracledb.AsyncConnection,
) -> None:
    async with oracle18c_startup_connection.cursor() as cursor:
        await cursor.execute("CREATE or replace view simple_table as SELECT 1 as the_value from dual")
        await cursor.execute("select * from simple_table")
        result = await cursor.fetchall()
        assert bool(result is not None and result[0][0] == 1)


async def test_oracle23c_services_after_start(
    oracle23c_startup_connection: oracledb.AsyncConnection,
) -> None:
    async with oracle23c_startup_connection.cursor() as cursor:
        await cursor.execute("CREATE or replace view simple_table as SELECT 1 as the_value from dual")
        await cursor.execute("select * from simple_table")
        result = await cursor.fetchall()
        assert bool(result is not None and result[0][0] == 1)
