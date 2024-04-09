# MIT License

# Copyright (c) 2024 Litestar

# Permission is hereby granted, free of charge, to any person obtaining a copy
# of this software and associated documentation files (the "Software"), to deal
# in the Software without restriction, including without limitation the rights
# to use, copy, modify, merge, publish, distribute, sublicense, and/or sell
# copies of the Software, and to permit persons to whom the Software is
# furnished to do so, subject to the following conditions:

# The above copyright notice and this permission notice shall be included in all
# copies or substantial portions of the Software.

# THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
# IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,
# FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE
# AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER
# LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM,
# OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN THE
# SOFTWARE.


from __future__ import annotations

import contextlib
import os
from typing import TYPE_CHECKING

import pytest
from google.auth.credentials import AnonymousCredentials, Credentials
from google.cloud import spanner

if TYPE_CHECKING:
    from pytest_databases.docker import DockerServiceRegistry


def spanner_responsive(
    host: str,
    spanner_port: int,
    spanner_instance: str,
    spanner_database: str,
    spanner_project: str,
    spanner_credentials: Credentials,
) -> bool:
    try:
        spanner_client = spanner.Client(project=spanner_project, credentials=spanner_credentials)
        instance = spanner_client.instance(spanner_instance)
        with contextlib.suppress(Exception):
            instance.create()

        database = instance.database(spanner_database)
        with contextlib.suppress(Exception):
            database.create()

        with database.snapshot() as snapshot:
            resp = next(iter(snapshot.execute_sql("SELECT 1")))
        return resp[0] == 1
    except Exception:  # noqa: BLE001
        return False


@pytest.fixture
def spanner_port() -> int:
    return 9010


@pytest.fixture
def spanner_instance() -> str:
    return "test-instance"


@pytest.fixture
def spanner_database() -> str:
    return "test-database"


@pytest.fixture
def spanner_project() -> str:
    return "emulator-test-project"


@pytest.fixture
def spanner_credentials() -> Credentials:
    return AnonymousCredentials()


@pytest.fixture(autouse=False)
async def spanner_service(
    docker_services: DockerServiceRegistry,
    docker_ip: str,
    spanner_port: int,
    spanner_instance: str,
    spanner_database: str,
    spanner_project: str,
    spanner_credentials: Credentials,
) -> None:
    os.environ["SPANNER_EMULATOR_HOST"] = f"{docker_ip}:{spanner_port}"
    os.environ["SPANNER_DATABASE"] = spanner_database
    os.environ["SPANNER_INSTANCE"] = spanner_instance
    os.environ["SPANNER_PORT"] = str(spanner_port)
    os.environ["GOOGLE_CLOUD_PROJECT"] = spanner_project
    await docker_services.start(
        "spanner",
        timeout=60,
        check=spanner_responsive,
        spanner_port=spanner_port,
        spanner_instance=spanner_instance,
        spanner_database=spanner_database,
        spanner_project=spanner_project,
        spanner_credentials=spanner_credentials,
    )
