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
from typing import TYPE_CHECKING

import aioodbc
import pytest

if TYPE_CHECKING:
    from pytest_databases.docker import DockerServiceRegistry


async def mssql_responsive(host: str, port: int, user: str, password: str, database: str) -> bool:
    await asyncio.sleep(1)
    try:
        conn = await aioodbc.connect(
            connstring=f"encrypt=no; TrustServerCertificate=yes; driver={{ODBC Driver 18 for SQL Server}}; server={host},{port}; database={database}; UID={user}; PWD={password}",
            timeout=2,
        )
        async with conn.cursor() as cursor:
            await cursor.execute("select 1 as is_available")
            resp = cursor.fetchone()
            return resp[0] == 1 if resp is not None else False
    except Exception:  # noqa: BLE001
        return False


@pytest.fixture()
def mssql_user() -> str:
    return "sa"


@pytest.fixture()
def mssql_password() -> str:
    return "super-secret"


@pytest.fixture()
def mssql_database() -> str:
    return "master"


@pytest.fixture()
def mssql2022_port() -> int:
    return 4133


@pytest.fixture()
def mssql_default_version() -> str:
    return "mssql2022"


@pytest.fixture()
def mssql_port(mssql113_port: int) -> int:
    return mssql113_port


@pytest.fixture(autouse=False)
async def mssql2022_service(
    docker_services: DockerServiceRegistry,
    mssql2022_port: int,
    mssql_database: str,
    mssql_user: str,
    mssql_password: str,
) -> None:
    await docker_services.start(
        "mssql2022",
        timeout=120,
        pause=1,
        check=mssql_responsive,
        port=mssql2022_port,
        database=mssql_database,
        user=mssql_user,
        password=mssql_password,
    )


@pytest.fixture(autouse=False)
async def mssql_service(
    docker_services: DockerServiceRegistry,
    mssql_default_version: str,
    mssql_port: int,
    mssql_database: str,
    mssql_user: str,
    mssql_password: str,
) -> None:
    await docker_services.start(
        mssql_default_version,
        timeout=120,
        pause=1,
        check=mssql_responsive,
        port=mssql_port,
        database=mssql_database,
        user=mssql_user,
        password=mssql_password,
    )
