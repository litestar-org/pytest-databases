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

from pytest_databases.docker.mysql import mysql_responsive

if TYPE_CHECKING:
    from pytest_databases.docker import DockerServiceRegistry

pytestmark = pytest.mark.anyio
pytest_plugins = [
    "pytest_databases.docker.mysql",
]


async def test_mysql_default_config(
    mysql_default_version: str,
    mysql_port: int,
    mysql_database: str,
    mysql_user: str,
    mysql_password: str,
) -> None:
    assert mysql_default_version == "mysql8"
    assert mysql_port == 3360
    assert mysql_database == "db"
    assert mysql_user == "app"
    assert mysql_password == "super-secret"


async def test_mysql_8_config(
    mysql8_port: int,
    mysql_database: str,
    mysql_user: str,
    mysql_password: str,
) -> None:
    assert mysql8_port == 3360
    assert mysql_database == "db"
    assert mysql_user == "app"
    assert mysql_password == "super-secret"


async def test_mysql_57_config(
    mysql57_port: int,
    mysql_database: str,
    mysql_user: str,
    mysql_password: str,
) -> None:
    assert mysql57_port == 3361
    assert mysql_database == "db"
    assert mysql_user == "app"
    assert mysql_password == "super-secret"


async def test_mysql_56_config(
    mysql56_port: int,
    mysql_database: str,
    mysql_user: str,
    mysql_password: str,
) -> None:
    assert mysql56_port == 3362
    assert mysql_database == "db"
    assert mysql_user == "app"
    assert mysql_password == "super-secret"


async def test_mysql_services(
    docker_ip: str,
    mysql_service: DockerServiceRegistry,
    mysql_port: int,
    mysql_database: str,
    mysql_user: str,
    mysql_password: str,
) -> None:
    ping = await mysql_responsive(
        docker_ip,
        port=mysql_port,
        database=mysql_database,
        user=mysql_user,
        password=mysql_password,
    )
    assert ping


async def test_mysql_57_services(
    docker_ip: str,
    mysql57_service: DockerServiceRegistry,
    mysql57_port: int,
    mysql_database: str,
    mysql_user: str,
    mysql_password: str,
) -> None:
    ping = await mysql_responsive(
        docker_ip,
        port=mysql57_port,
        database=mysql_database,
        user=mysql_user,
        password=mysql_password,
    )
    assert ping


async def test_mysql_56_services(
    docker_ip: str,
    mysql56_service: DockerServiceRegistry,
    mysql56_port: int,
    mysql_database: str,
    mysql_user: str,
    mysql_password: str,
) -> None:
    ping = await mysql_responsive(
        docker_ip,
        port=mysql56_port,
        database=mysql_database,
        user=mysql_user,
        password=mysql_password,
    )
    assert ping


async def test_mysql_8_services(
    docker_ip: str,
    mysql8_service: DockerServiceRegistry,
    mysql8_port: int,
    mysql_database: str,
    mysql_user: str,
    mysql_password: str,
) -> None:
    ping = await mysql_responsive(
        docker_ip,
        port=mysql8_port,
        database=mysql_database,
        user=mysql_user,
        password=mysql_password,
    )
    assert ping
