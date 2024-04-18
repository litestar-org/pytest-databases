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

import os
from pathlib import Path
from typing import TYPE_CHECKING

import asyncpg
import pytest

if TYPE_CHECKING:
    from pytest_databases.docker import DockerServiceRegistry


async def alloydb_omni_responsive(host: str, port: int, user: str, password: str, database: str) -> bool:
    try:
        conn = await asyncpg.connect(
            host=host,
            port=port,
            user=user,
            database=database,
            password=password,
        )
    except Exception:  # noqa: BLE001
        return False

    try:
        db_open = await conn.fetchrow("SELECT 1")
        return bool(db_open is not None and db_open[0] == 1)
    finally:
        await conn.close()


@pytest.fixture()
def postgres_user() -> str:
    return "postgres"


@pytest.fixture()
def postgres_password() -> str:
    return "super-secret"


@pytest.fixture()
def postgres_database() -> str:
    return "postgres"


@pytest.fixture()
def alloydb_omni_port() -> int:
    return 5420


@pytest.fixture()
def default_alloydb_omni_service_name() -> str:
    return "alloydb"


@pytest.fixture(scope="session")
def docker_compose_files() -> list[Path]:
    return [Path(Path(__file__).parent / "docker-compose.alloydb-omni.yml")]


# alias to the latest
@pytest.fixture(autouse=False)
async def alloydb_omni_service(
    docker_services: DockerServiceRegistry,
    default_alloydb_omni_service_name: str,
    docker_compose_files: list[Path],
    alloydb_omni_port: int,
    postgres_database: str,
    postgres_user: str,
    postgres_password: str,
) -> None:
    os.environ["POSTGRES_PASSWORD"] = postgres_password
    os.environ["POSTGRES_USER"] = postgres_user
    os.environ["POSTGRES_DATABASE"] = postgres_database
    os.environ[f"{default_alloydb_omni_service_name.upper()}_PORT"] = str(alloydb_omni_port)
    await docker_services.start(
        name=default_alloydb_omni_service_name,
        docker_compose_files=docker_compose_files,
        timeout=45,
        pause=1,
        check=alloydb_omni_responsive,
        port=alloydb_omni_port,
        database=postgres_database,
        user=postgres_user,
        password=postgres_password,
    )
