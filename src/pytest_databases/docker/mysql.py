# SPDX-FileCopyrightText: 2023-present Jolt
#
# SPDX-License-Identifier: MIT
from __future__ import annotations

from typing import TYPE_CHECKING

import asyncmy
import pytest

if TYPE_CHECKING:
    from pytest_databases.docker import DockerServiceRegistry


async def mysql_responsive(host: str, port: int, user: str, password: str, database: str) -> bool:
    try:
        conn = await asyncmy.connect(
            host=host,
            port=port,
            user=user,
            database=database,
            password=password,
        )
    except Exception:  # noqa: BLE001
        return False

    try:
        async with conn.cursor() as cursor:
            await cursor.execute("select 1 as is_available")
            resp = await cursor.fetchone()
        return resp[0] == 1
    finally:
        await conn.close()


@pytest.fixture()
def mysql_user() -> str:
    return "app"


@pytest.fixture()
def mysql_password() -> str:
    return "super-secret"


@pytest.fixture()
def mysql_database() -> str:
    return "db"


@pytest.fixture()
def mysql56_port() -> int:
    return 3362


@pytest.fixture()
def mysql57_port() -> int:
    return 3361


@pytest.fixture()
def mysql8_port() -> int:
    return 3360


@pytest.fixture()
def mysql_default_version() -> str:
    return "mysql8"


@pytest.fixture()
def mysql_port(mysql8_port: int) -> int:
    return mysql8_port


@pytest.fixture(autouse=False)
async def mysql8_service(
    docker_services: DockerServiceRegistry, mysql8_port: int, mysql_database: str, mysql_user: str, mysql_password: str
) -> None:
    await docker_services.start(
        "mysql8",
        timeout=45,
        pause=1,
        check=mysql_responsive,
        port=mysql8_port,
        database=mysql_database,
        user=mysql_user,
        password=mysql_password,
    )


@pytest.fixture(autouse=False)
async def mysql57_service(
    docker_services: DockerServiceRegistry, mysql57_port: int, mysql_database: str, mysql_user: str, mysql_password: str
) -> None:
    await docker_services.start(
        "mysql57",
        timeout=45,
        pause=1,
        check=mysql_responsive,
        port=mysql57_port,
        database=mysql_database,
        user=mysql_user,
        password=mysql_password,
    )


@pytest.fixture(autouse=False)
async def mysql56_service(
    docker_services: DockerServiceRegistry, mysql56_port: int, mysql_database: str, mysql_user: str, mysql_password: str
) -> None:
    await docker_services.start(
        "mysql56",
        timeout=45,
        pause=1,
        check=mysql_responsive,
        port=mysql56_port,
        database=mysql_database,
        user=mysql_user,
        password=mysql_password,
    )


@pytest.fixture(autouse=False)
async def mysql_service(
    docker_services: DockerServiceRegistry,
    mysql_default_version: str,
    mysql_port: int,
    mysql_database: str,
    mysql_user: str,
    mysql_password: str,
) -> None:
    await docker_services.start(
        mysql_default_version,
        timeout=45,
        pause=1,
        check=mysql_responsive,
        port=mysql_port,
        database=mysql_database,
        user=mysql_user,
        password=mysql_password,
    )
