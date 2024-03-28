# SPDX-FileCopyrightText: 2023-present Cody Fincher <codyfincher@google.com>
#
# SPDX-License-Identifier: MIT
from __future__ import annotations

from typing import TYPE_CHECKING

import oracledb
import pytest

if TYPE_CHECKING:
    from pytest_databases.docker.compose import DockerServiceRegistry


def oracle_responsive(host: str, port: int, service_name: str) -> bool:
    try:
        conn = oracledb.connect(
            host=host,
            port=port,
            user="app",
            service_name=service_name,
            password="super-secret",
        )
        with conn.cursor() as cursor:
            cursor.execute("SELECT 1 FROM dual")
            resp = cursor.fetchone()
        return resp[0] == 1 if resp is not None else False
    except Exception:  # noqa: BLE001
        return False


@pytest.fixture()
async def oracle23c_service(docker_services: DockerServiceRegistry) -> None:
    await docker_services.start(
        "oracle23c", timeout=120, pause=1, check=oracle_responsive, port=1512, service_name="FREEPDB1"
    )


@pytest.fixture()
async def oracle18c_service(docker_services: DockerServiceRegistry) -> None:
    await docker_services.start(
        "oracle18c", timeout=120, pause=1, check=oracle_responsive, port=1512, service_name="xepdb1"
    )
