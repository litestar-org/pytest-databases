# SPDX-FileCopyrightText: 2023-present Jolt
#
# SPDX-License-Identifier: MIT
from __future__ import annotations

from typing import TYPE_CHECKING

import asyncmy
import pytest

if TYPE_CHECKING:
    from pytest_databases.docker import DockerServiceRegistry


async def mariadb_responsive(host: str, port: int, user: str, password: str, database: str) -> bool:
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
def mariadb_user() -> str:
    return "app"


@pytest.fixture()
def mariadb_password() -> str:
    return "super-secret"


@pytest.fixture()
def mariadb_database() -> str:
    return "db"


@pytest.fixture()
def mariadb113_port() -> int:
    return 3359


@pytest.fixture()
def mariadb_default_version() -> str:
    return "mariadb113"


@pytest.fixture()
def mariadb_port(mariadb113_port: int) -> int:
    return mariadb113_port


@pytest.fixture()
async def mariadb113_service(
    docker_services: DockerServiceRegistry,
    mariadb113_port: int,
    mariadb_database: str,
    mariadb_user: str,
    mariadb_password: str,
) -> None:
    await docker_services.start(
        "mariadb8",
        timeout=45,
        pause=1,
        check=mariadb_responsive,
        port=mariadb113_port,
        database=mariadb_database,
        user=mariadb_user,
        password=mariadb_password,
    )


@pytest.fixture()
async def mariadb_service(
    docker_services: DockerServiceRegistry,
    mariadb_default_version: str,
    mariadb_port: int,
    mariadb_database: str,
    mariadb_user: str,
    mariadb_password: str,
) -> None:
    await docker_services.start(
        mariadb_default_version,
        timeout=45,
        pause=1,
        check=mariadb_responsive,
        port=mariadb_port,
        database=mariadb_database,
        user=mariadb_user,
        password=mariadb_password,
    )
