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

import asyncio
import os
import sys
from pathlib import Path
from typing import TYPE_CHECKING, AsyncGenerator

import aioodbc
import pytest

from pytest_databases.docker import DockerServiceRegistry
from pytest_databases.helpers import simple_string_hash

if TYPE_CHECKING:
    from collections.abc import Generator


COMPOSE_PROJECT_NAME: str = f"pytest-databases-mssql-{simple_string_hash(__file__)}"


async def mssql_responsive(host: str, connstring: str) -> bool:
    await asyncio.sleep(1)
    try:
        conn = await aioodbc.connect(
            dsn=connstring,
            timeout=2,
        )
        async with conn.cursor() as cursor:
            await cursor.execute("select 1 as is_available")
            resp = await cursor.fetchone()
            return resp[0] == 1 if resp is not None else False
    except Exception:  # noqa: BLE001
        return False


@pytest.fixture(scope="session")
def mssql_compose_project_name() -> str:
    return os.environ.get("COMPOSE_PROJECT_NAME", COMPOSE_PROJECT_NAME)


@pytest.fixture(autouse=False, scope="session")
def mssql_docker_services(
    mssql_compose_project_name: str, worker_id: str = "main"
) -> Generator[DockerServiceRegistry, None, None]:
    if os.getenv("GITHUB_ACTIONS") == "true" and sys.platform != "linux":
        pytest.skip("Docker not available on this platform")

    registry = DockerServiceRegistry(worker_id, compose_project_name=mssql_compose_project_name)
    try:
        yield registry
    finally:
        registry.down()


@pytest.fixture(scope="session")
def mssql_user() -> str:
    return "sa"


@pytest.fixture(scope="session")
def mssql_password() -> str:
    return "Super-secret1"


@pytest.fixture(scope="session")
def mssql_database() -> str:
    return "master"


@pytest.fixture(scope="session")
def mssql2022_port() -> int:
    return 4133


@pytest.fixture(scope="session")
def mssql_port(mssql2022_port: int) -> int:
    return mssql2022_port


@pytest.fixture(scope="session")
def mssql_docker_compose_files() -> list[Path]:
    return [Path(Path(__file__).parent / "docker-compose.mssql.yml")]


@pytest.fixture(scope="session")
def default_mssql_service_name() -> str:
    return "mssql2022"


@pytest.fixture(scope="session")
def mssql_docker_ip(mssql_docker_services: DockerServiceRegistry) -> str:
    return mssql_docker_services.docker_ip


@pytest.fixture(autouse=False, scope="session")
async def mssql2022_service(
    mssql_docker_services: DockerServiceRegistry,
    mssql_docker_compose_files: list[Path],
    mssql_docker_ip: str,
    mssql2022_port: int,
    mssql_database: str,
    mssql_user: str,
    mssql_password: str,
) -> AsyncGenerator[None, None]:
    os.environ["MSSQL_PASSWORD"] = mssql_password
    os.environ["MSSQL_USER"] = mssql_user
    os.environ["MSSQL_DATABASE"] = mssql_database
    os.environ["MSSQL2022_PORT"] = str(mssql2022_port)
    connstring = f"encrypt=no; TrustServerCertificate=yes; driver={{ODBC Driver 18 for SQL Server}}; server={mssql_docker_ip},{mssql2022_port}; database={mssql_database}; UID={mssql_user}; PWD={mssql_password}"
    await mssql_docker_services.start(
        "mssql2022",
        docker_compose_files=mssql_docker_compose_files,
        timeout=120,
        pause=1,
        check=mssql_responsive,
        connstring=connstring,
    )
    yield


@pytest.fixture(autouse=False, scope="session")
async def mssql_service(
    mssql_docker_services: DockerServiceRegistry,
    default_mssql_service_name: str,
    mssql_docker_compose_files: list[Path],
    mssql_docker_ip: str,
    mssql_port: int,
    mssql_database: str,
    mssql_user: str,
    mssql_password: str,
) -> AsyncGenerator[None, None]:
    connstring = f"encrypt=no; TrustServerCertificate=yes; driver={{ODBC Driver 18 for SQL Server}}; server={mssql_docker_ip},{mssql_port}; database={mssql_database}; UID={mssql_user}; PWD={mssql_password}"
    os.environ["MSSQL_PASSWORD"] = mssql_password
    os.environ["MSSQL_USER"] = mssql_user
    os.environ["MSSQL_DATABASE"] = mssql_database
    os.environ[f"{default_mssql_service_name.upper()}_PORT"] = str(mssql_port)
    await mssql_docker_services.start(
        name=default_mssql_service_name,
        docker_compose_files=mssql_docker_compose_files,
        timeout=120,
        pause=1,
        check=mssql_responsive,
        connstring=connstring,
    )
    yield
