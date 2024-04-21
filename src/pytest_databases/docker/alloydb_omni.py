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
import sys
from pathlib import Path
from typing import TYPE_CHECKING, AsyncGenerator

import asyncpg
import pytest

from pytest_databases.docker import DockerServiceRegistry
from pytest_databases.helpers import simple_string_hash

if TYPE_CHECKING:
    from collections.abc import Generator


COMPOSE_PROJECT_NAME: str = f"pytest-databases-alloydb-{simple_string_hash(__file__)}"


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


@pytest.fixture(scope="session")
def alloydb_compose_project_name() -> str:
    return os.environ.get("COMPOSE_PROJECT_NAME", COMPOSE_PROJECT_NAME)


@pytest.fixture(autouse=False, scope="session")
def alloydb_docker_services(
    alloydb_compose_project_name: str, worker_id: str = "main"
) -> Generator[DockerServiceRegistry, None, None]:
    if os.getenv("GITHUB_ACTIONS") == "true" and sys.platform != "linux":
        pytest.skip("Docker not available on this platform")

    registry = DockerServiceRegistry(worker_id, compose_project_name=alloydb_compose_project_name)
    try:
        yield registry
    finally:
        registry.down()


@pytest.fixture(scope="session")
def postgres_user() -> str:
    return "postgres"


@pytest.fixture(scope="session")
def postgres_password() -> str:
    return "super-secret"


@pytest.fixture(scope="session")
def postgres_database() -> str:
    return "postgres"


@pytest.fixture(scope="session")
def alloydb_omni_port() -> int:
    return 5420


@pytest.fixture(scope="session")
def default_alloydb_omni_service_name() -> str:
    return "alloydb"


@pytest.fixture(scope="session")
def alloydb_docker_compose_files() -> list[Path]:
    return [Path(Path(__file__).parent / "docker-compose.alloydb-omni.yml")]


@pytest.fixture(scope="session")
def alloydb_docker_ip(alloydb_docker_services: DockerServiceRegistry) -> str:
    return alloydb_docker_services.docker_ip


# alias to the latest
@pytest.fixture(autouse=False, scope="session")
async def alloydb_omni_service(
    alloydb_docker_services: DockerServiceRegistry,
    default_alloydb_omni_service_name: str,
    alloydb_docker_compose_files: list[Path],
    alloydb_omni_port: int,
    postgres_database: str,
    postgres_user: str,
    postgres_password: str,
) -> AsyncGenerator[None, None]:
    os.environ["POSTGRES_PASSWORD"] = postgres_password
    os.environ["POSTGRES_USER"] = postgres_user
    os.environ["POSTGRES_DATABASE"] = postgres_database
    os.environ[f"{default_alloydb_omni_service_name.upper()}_PORT"] = str(alloydb_omni_port)
    await alloydb_docker_services.start(
        name=default_alloydb_omni_service_name,
        docker_compose_files=alloydb_docker_compose_files,
        timeout=45,
        pause=1,
        check=alloydb_omni_responsive,
        port=alloydb_omni_port,
        database=postgres_database,
        user=postgres_user,
        password=postgres_password,
    )
    yield
