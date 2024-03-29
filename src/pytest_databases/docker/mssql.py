# SPDX-FileCopyrightText: 2023-present Cody Fincher <codyfincher@google.com>
#
# SPDX-License-Identifier: MIT
from __future__ import annotations

import asyncio
from typing import TYPE_CHECKING

import aioodbc
import pytest

if TYPE_CHECKING:
    from pytest_databases.docker import DockerServiceRegistry


async def mssql_responsive(host: str, port: int) -> bool:
    await asyncio.sleep(1)
    try:
        port = 1344
        user = "sa"
        database = "master"
        conn = await aioodbc.connect(
            connstring=f"encrypt=no; TrustServerCertificate=yes; driver={{ODBC Driver 18 for SQL Server}}; server={host},{port}; database={database}; UID={user}; PWD=Super-secret1",
            timeout=2,
        )
        async with conn.cursor() as cursor:
            await cursor.execute("select 1 as is_available")
            resp = cursor.fetchone()
            return resp[0] == 1 if resp is not None else False
    except Exception:  # noqa: BLE001
        return False


@pytest.fixture()
async def mssql_service(docker_services: DockerServiceRegistry) -> None:
    await docker_services.start("mssql", timeout=60, pause=1, check=mssql_responsive, port=1344)
