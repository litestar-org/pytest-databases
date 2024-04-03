# SPDX-FileCopyrightText: 2023-present Jolt
#
# SPDX-License-Identifier: MIT
from __future__ import annotations

import asyncio
from typing import TYPE_CHECKING

import aioodbc
import pytest

if TYPE_CHECKING:
    from pytest_databases.docker import DockerServiceRegistry


async def mssql_responsive(host: str, port: int, user: str, password: str, database: str) -> bool:
    await asyncio.sleep(1)
    try:
        conn = await aioodbc.connect(
            connstring=f"encrypt=no; TrustServerCertificate=yes; driver={{ODBC Driver 18 for SQL Server}}; server={host},{port}; database={database}; UID={user}; PWD={password}",
            timeout=2,
        )
        async with conn.cursor() as cursor:
            await cursor.execute("select 1 as is_available")
            resp = cursor.fetchone()
            return resp[0] == 1 if resp is not None else False
    except Exception:  # noqa: BLE001
        return False


@pytest.fixture()
def mssql_user() -> str:
    return "sa"


@pytest.fixture()
def mssql_password() -> str:
    return "super-secret"


@pytest.fixture()
def mssql_database() -> str:
    return "master"


@pytest.fixture()
def mssql2022_port() -> int:
    return 4133


@pytest.fixture()
def mssql_default_version() -> str:
    return "mssql2022"


@pytest.fixture()
def mssql_port(mssql113_port: int) -> int:
    return mssql113_port


@pytest.fixture(autouse=False)
async def mssql2022_service(
    docker_services: DockerServiceRegistry,
    mssql2022_port: int,
    mssql_database: str,
    mssql_user: str,
    mssql_password: str,
) -> None:
    await docker_services.start(
        "mssql2022",
        timeout=120,
        pause=1,
        check=mssql_responsive,
        port=mssql2022_port,
        database=mssql_database,
        user=mssql_user,
        password=mssql_password,
    )


@pytest.fixture(autouse=False)
async def mssql_service(
    docker_services: DockerServiceRegistry,
    mssql_default_version: str,
    mssql_port: int,
    mssql_database: str,
    mssql_user: str,
    mssql_password: str,
) -> None:
    await docker_services.start(
        mssql_default_version,
        timeout=120,
        pause=1,
        check=mssql_responsive,
        port=mssql_port,
        database=mssql_database,
        user=mssql_user,
        password=mssql_password,
    )
