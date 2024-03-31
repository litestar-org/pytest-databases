# SPDX-FileCopyrightText: 2023-present Jolt
#
# SPDX-License-Identifier: MIT
from __future__ import annotations

from typing import TYPE_CHECKING

import psycopg
import pytest

if TYPE_CHECKING:
    from pytest_databases.docker import DockerServiceRegistry


async def cockroachdb_responsive(host: str, port: int, database: str, driver_opts: dict[str, str]) -> bool:
    opts = "&".join(f"{k}={v}" for k, v in driver_opts.items()) if driver_opts else ""
    try:
        with psycopg.connect(f"postgresql://root@{host}:{port}/{database}?{opts}") as conn, conn.cursor() as cursor:
            cursor.execute("select 1 as is_available")
            resp = cursor.fetchone()
            return resp[0] if resp is not None else 0 == 1  # noqa: PLR0133
    except Exception:  # noqa: BLE001
        return False


@pytest.fixture()
async def cockroachdb_service(docker_services: DockerServiceRegistry) -> None:
    await docker_services.start(
        "cockroachdb",
        timeout=60,
        pause=1,
        check=cockroachdb_responsive,
        port=26257,
        database="defaultdb",
        driver_opts={"sslmode": "disable"},
    )
