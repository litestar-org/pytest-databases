# SPDX-FileCopyrightText: 2023-present Jolt
#
# SPDX-License-Identifier: MIT
from __future__ import annotations

import contextlib
import os
from typing import TYPE_CHECKING

import pytest
from google.auth.credentials import AnonymousCredentials
from google.cloud import spanner

if TYPE_CHECKING:
    from pytest_databases.docker import DockerServiceRegistry


def spanner_responsive(host: str) -> bool:
    try:
        os.environ["SPANNER_EMULATOR_HOST"] = "localhost:9010"
        os.environ["GOOGLE_CLOUD_PROJECT"] = "emulator-test-project"
        spanner_client = spanner.Client(project="emulator-test-project", credentials=AnonymousCredentials())
        instance = spanner_client.instance("test-instance")
        with contextlib.suppress(Exception):
            instance.create()

        database = instance.database("test-database")
        with contextlib.suppress(Exception):
            database.create()

        with database.snapshot() as snapshot:
            resp = next(iter(snapshot.execute_sql("SELECT 1")))
        return resp[0] == 1
    except Exception:  # noqa: BLE001
        return False


@pytest.fixture(autouse=False)
async def spanner_service(docker_services: DockerServiceRegistry) -> None:
    os.environ["SPANNER_EMULATOR_HOST"] = "localhost:9010"
    await docker_services.start("spanner", timeout=60, check=spanner_responsive)
