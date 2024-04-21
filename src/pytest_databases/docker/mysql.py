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
import sys
from pathlib import Path
from typing import TYPE_CHECKING, AsyncGenerator

import asyncmy
import pytest

from pytest_databases.docker import DockerServiceRegistry
from pytest_databases.helpers import simple_string_hash

if TYPE_CHECKING:
    from collections.abc import Generator


COMPOSE_PROJECT_NAME: str = f"pytest-databases-mysql-{simple_string_hash(__file__)}"


async def mysql_responsive(host: str, port: int, user: str, password: str, database: str) -> bool:
    try:
        conn = await asyncmy.connect(
            host=host,
            port=port,
            user=user,
            database=database,
            password=password,
        )
    except Exception:  # noqa: BLE001
        return False

    try:
        async with conn.cursor() as cursor:
            await cursor.execute("select 1 as is_available")
            resp = await cursor.fetchone()
        return resp[0] == 1
    finally:
        with contextlib.suppress(Exception):
            await conn.close()


@pytest.fixture(scope="session")
def mysql_compose_project_name() -> str:
    return os.environ.get("COMPOSE_PROJECT_NAME", COMPOSE_PROJECT_NAME)


@pytest.fixture(autouse=False, scope="session")
def mysql_docker_services(
    mysql_compose_project_name: str, worker_id: str = "main"
) -> Generator[DockerServiceRegistry, None, None]:
    if os.getenv("GITHUB_ACTIONS") == "true" and sys.platform != "linux":
        pytest.skip("Docker not available on this platform")

    registry = DockerServiceRegistry(worker_id, compose_project_name=mysql_compose_project_name)
    try:
        yield registry
    finally:
        registry.down()


@pytest.fixture(scope="session")
def mysql_user() -> str:
    return "app"


@pytest.fixture(scope="session")
def mysql_password() -> str:
    return "super-secret"


@pytest.fixture(scope="session")
def mysql_root_password() -> str:
    return "super-secret"


@pytest.fixture(scope="session")
def mysql_database() -> str:
    return "db"


@pytest.fixture(scope="session")
def mysql56_port() -> int:
    return 3362


@pytest.fixture(scope="session")
def mysql57_port() -> int:
    return 3361


@pytest.fixture(scope="session")
def default_mysql_service_name() -> str:
    return "mysql8"


@pytest.fixture(scope="session")
def mysql8_port() -> int:
    return 3360


@pytest.fixture(scope="session")
def mysql_port(mysql8_port: int) -> int:
    return mysql8_port


@pytest.fixture(scope="session")
def mysql_docker_compose_files() -> list[Path]:
    return [Path(Path(__file__).parent / "docker-compose.mysql.yml")]


@pytest.fixture(scope="session")
def mysql_docker_ip(mysql_docker_services: DockerServiceRegistry) -> str:
    return mysql_docker_services.docker_ip


@pytest.fixture(autouse=False, scope="session")
async def mysql8_service(
    mysql_docker_services: DockerServiceRegistry,
    mysql_docker_compose_files: list[Path],
    mysql8_port: int,
    mysql_database: str,
    mysql_user: str,
    mysql_password: str,
    mysql_root_password: str,
) -> AsyncGenerator[None, None]:
    os.environ["MYSQL_ROOT_PASSWORD"] = mysql_root_password
    os.environ["MYSQL_PASSWORD"] = mysql_password
    os.environ["MYSQL_USER"] = mysql_user
    os.environ["MYSQL_DATABASE"] = mysql_database
    os.environ["MYSQL8_PORT"] = str(mysql8_port)
    await mysql_docker_services.start(
        "mysql8",
        docker_compose_files=mysql_docker_compose_files,
        timeout=45,
        pause=1,
        check=mysql_responsive,
        port=mysql8_port,
        database=mysql_database,
        user=mysql_user,
        password=mysql_password,
    )
    yield


@pytest.fixture(autouse=False, scope="session")
async def mysql57_service(
    mysql_docker_services: DockerServiceRegistry,
    mysql_docker_compose_files: list[Path],
    mysql57_port: int,
    mysql_database: str,
    mysql_user: str,
    mysql_password: str,
    mysql_root_password: str,
) -> AsyncGenerator[None, None]:
    os.environ["MYSQL_ROOT_PASSWORD"] = mysql_root_password
    os.environ["MYSQL_PASSWORD"] = mysql_password
    os.environ["MYSQL_USER"] = mysql_user
    os.environ["MYSQL_DATABASE"] = mysql_database
    os.environ["MYSQL57_PORT"] = str(mysql57_port)
    await mysql_docker_services.start(
        "mysql57",
        docker_compose_files=mysql_docker_compose_files,
        timeout=45,
        pause=1,
        check=mysql_responsive,
        port=mysql57_port,
        database=mysql_database,
        user=mysql_user,
        password=mysql_password,
    )
    yield


@pytest.fixture(autouse=False, scope="session")
async def mysql56_service(
    mysql_docker_services: DockerServiceRegistry,
    mysql_docker_compose_files: list[Path],
    mysql56_port: int,
    mysql_database: str,
    mysql_user: str,
    mysql_password: str,
    mysql_root_password: str,
) -> AsyncGenerator[None, None]:
    os.environ["MYSQL_ROOT_PASSWORD"] = mysql_root_password
    os.environ["MYSQL_PASSWORD"] = mysql_password
    os.environ["MYSQL_USER"] = mysql_user
    os.environ["MYSQL_DATABASE"] = mysql_database
    os.environ["MYSQL56_PORT"] = str(mysql56_port)
    await mysql_docker_services.start(
        "mysql56",
        docker_compose_files=mysql_docker_compose_files,
        timeout=45,
        pause=1,
        check=mysql_responsive,
        port=mysql56_port,
        database=mysql_database,
        user=mysql_user,
        password=mysql_password,
    )
    yield


@pytest.fixture(autouse=False, scope="session")
async def mysql_service(
    mysql_docker_services: DockerServiceRegistry,
    default_mysql_service_name: str,
    mysql_docker_compose_files: list[Path],
    mysql_port: int,
    mysql_database: str,
    mysql_user: str,
    mysql_password: str,
    mysql_root_password: str,
) -> AsyncGenerator[None, None]:
    os.environ["MYSQL_ROOT_PASSWORD"] = mysql_root_password
    os.environ["MYSQL_PASSWORD"] = mysql_password
    os.environ["MYSQL_USER"] = mysql_user
    os.environ["MYSQL_DATABASE"] = mysql_database
    os.environ[f"{default_mysql_service_name.upper()}_PORT"] = str(mysql_port)
    await mysql_docker_services.start(
        name=default_mysql_service_name,
        docker_compose_files=mysql_docker_compose_files,
        timeout=45,
        pause=1,
        check=mysql_responsive,
        port=mysql_port,
        database=mysql_database,
        user=mysql_user,
        password=mysql_password,
    )
    yield
