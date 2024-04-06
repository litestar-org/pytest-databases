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

from typing import TYPE_CHECKING

import pytest

from pytest_databases.docker.postgres import postgres_responsive

if TYPE_CHECKING:
    from pytest_databases.docker import DockerServiceRegistry

pytestmark = pytest.mark.anyio
pytest_plugins = [
    "pytest_databases.docker.postgres",
]


async def test_postgres_default_config(
    postgres_default_version: str,
    postgres_port: int,
    postgres_database: str,
    postgres_user: str,
    postgres_password: str,
) -> None:
    assert postgres_default_version == "postgres16"
    assert postgres_port == 5427
    assert postgres_database == "postgres"
    assert postgres_user == "postgres"
    assert postgres_password == "super-secret"


async def test_postgres_12_config(
    postgres12_port: int,
    postgres_database: str,
    postgres_user: str,
    postgres_password: str,
) -> None:
    assert postgres12_port == 5423
    assert postgres_database == "postgres"
    assert postgres_user == "postgres"
    assert postgres_password == "super-secret"


async def test_postgres_13_config(
    postgres13_port: int,
    postgres_database: str,
    postgres_user: str,
    postgres_password: str,
) -> None:
    assert postgres13_port == 5424
    assert postgres_database == "postgres"
    assert postgres_user == "postgres"
    assert postgres_password == "super-secret"


async def test_postgres_14_config(
    postgres14_port: int,
    postgres_database: str,
    postgres_user: str,
    postgres_password: str,
) -> None:
    assert postgres14_port == 5425
    assert postgres_database == "postgres"
    assert postgres_user == "postgres"
    assert postgres_password == "super-secret"


async def test_postgres_15_config(
    postgres15_port: int,
    postgres_database: str,
    postgres_user: str,
    postgres_password: str,
) -> None:
    assert postgres15_port == 5426
    assert postgres_database == "postgres"
    assert postgres_user == "postgres"
    assert postgres_password == "super-secret"


async def test_postgres_16_config(
    postgres16_port: int,
    postgres_database: str,
    postgres_user: str,
    postgres_password: str,
) -> None:
    assert postgres16_port == 5427
    assert postgres_database == "postgres"
    assert postgres_user == "postgres"
    assert postgres_password == "super-secret"


async def test_postgres_services(
    docker_ip: str,
    postgres_service: DockerServiceRegistry,
    postgres_port: int,
    postgres_database: str,
    postgres_user: str,
    postgres_password: str,
) -> None:
    ping = await postgres_responsive(
        docker_ip,
        port=postgres_port,
        database=postgres_database,
        user=postgres_user,
        password=postgres_password,
    )
    assert ping


async def test_postgres_12_services(
    docker_ip: str,
    postgres12_service: DockerServiceRegistry,
    postgres12_port: int,
    postgres_database: str,
    postgres_user: str,
    postgres_password: str,
) -> None:
    ping = await postgres_responsive(
        docker_ip,
        port=postgres12_port,
        database=postgres_database,
        user=postgres_user,
        password=postgres_password,
    )
    assert ping


async def test_postgres_13_services(
    docker_ip: str,
    postgres13_service: DockerServiceRegistry,
    postgres13_port: int,
    postgres_database: str,
    postgres_user: str,
    postgres_password: str,
) -> None:
    ping = await postgres_responsive(
        docker_ip,
        port=postgres13_port,
        database=postgres_database,
        user=postgres_user,
        password=postgres_password,
    )
    assert ping


async def test_postgres_14_services(
    docker_ip: str,
    postgres14_service: DockerServiceRegistry,
    postgres14_port: int,
    postgres_database: str,
    postgres_user: str,
    postgres_password: str,
) -> None:
    ping = await postgres_responsive(
        docker_ip,
        port=postgres14_port,
        database=postgres_database,
        user=postgres_user,
        password=postgres_password,
    )
    assert ping


async def test_postgres_15_services(
    docker_ip: str,
    postgres15_service: DockerServiceRegistry,
    postgres15_port: int,
    postgres_database: str,
    postgres_user: str,
    postgres_password: str,
) -> None:
    ping = await postgres_responsive(
        docker_ip,
        port=postgres15_port,
        database=postgres_database,
        user=postgres_user,
        password=postgres_password,
    )
    assert ping


async def test_postgres_16_services(
    docker_ip: str,
    postgres16_service: DockerServiceRegistry,
    postgres16_port: int,
    postgres_database: str,
    postgres_user: str,
    postgres_password: str,
) -> None:
    ping = await postgres_responsive(
        docker_ip,
        port=postgres16_port,
        database=postgres_database,
        user=postgres_user,
        password=postgres_password,
    )
    assert ping
