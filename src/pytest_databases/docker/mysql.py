# SPDX-FileCopyrightText: 2023-present Cody Fincher <codyfincher@google.com>
#
# SPDX-License-Identifier: MIT
from __future__ import annotations

from typing import TYPE_CHECKING

import asyncmy
import pytest

if TYPE_CHECKING:
    from pytest_databases.docker.compose import DockerServiceRegistry


async def mysql_responsive(host: str, port: int) -> bool:
    try:
        conn = await asyncmy.connect(
            host=host,
            port=port,
            user="app",
            database="db",
            password="super-secret",
        )
        async with conn.cursor() as cursor:
            await cursor.execute("select 1 as is_available")
            resp = await cursor.fetchone()
        return resp[0] == 1
    except asyncmy.errors.OperationalError:
        return False


@pytest.fixture()
async def mysql8_service(docker_services: DockerServiceRegistry) -> None:
    await docker_services.start("mysql8", timeout=45, pause=1, check=mysql_responsive, port=3360)


@pytest.fixture()
async def mysql57_service(docker_services: DockerServiceRegistry) -> None:
    await docker_services.start("mysql57", timeout=45, pause=1, check=mysql_responsive, port=3363)


@pytest.fixture()
async def mysql56_service(docker_services: DockerServiceRegistry) -> None:
    await docker_services.start("mysql56", timeout=45, pause=1, check=mysql_responsive, port=3362)
