# SPDX-FileCopyrightText: 2023-present Cody Fincher <codyfincher@google.com>
#
# SPDX-License-Identifier: MIT
from __future__ import annotations

from typing import TYPE_CHECKING

import asyncpg
import pytest

if TYPE_CHECKING:
    from pytest_databases.docker import DockerServiceRegistry


async def postgres_responsive(host: str, port: int) -> bool:
    try:
        conn = await asyncpg.connect(
            host=host,
            port=port,
            user="postgres",
            database="postgres",
            password="super-secret",
        )
    except Exception:  # noqa: BLE001
        return False

    try:
        db_open = await conn.fetchrow("SELECT 1")
        return bool(db_open is not None and db_open[0] == 1)
    finally:
        await conn.close()


@pytest.fixture()
async def postgres12_service(docker_services: DockerServiceRegistry) -> None:
    await docker_services.start("postgres12", timeout=45, pause=1, check=postgres_responsive, port=5423)


@pytest.fixture()
async def postgres13_service(docker_services: DockerServiceRegistry) -> None:
    await docker_services.start("postgres13", timeout=45, pause=1, check=postgres_responsive, port=5424)


@pytest.fixture()
async def postgres14_service(docker_services: DockerServiceRegistry) -> None:
    await docker_services.start("postgres14", timeout=45, pause=1, check=postgres_responsive, port=5425)


@pytest.fixture()
async def postgres15_service(docker_services: DockerServiceRegistry) -> None:
    await docker_services.start("postgres15", timeout=45, pause=1, check=postgres_responsive, port=5426)


@pytest.fixture()
async def postgres16_service(docker_services: DockerServiceRegistry) -> None:
    await docker_services.start("postgres16", timeout=45, pause=1, check=postgres_responsive, port=5427)
