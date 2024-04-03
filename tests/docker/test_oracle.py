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

import oracledb
import pytest

if TYPE_CHECKING:
    from pytest_databases.docker import DockerServiceRegistry

pytestmark = pytest.mark.anyio
pytest_plugins = [
    "pytest_databases.docker.oracle",
]


def test_oracle18c_default_config(
    oracle_user: str, oracle_password: str, oracle18c_service_name: str, oracle18c_port: int
) -> None:
    assert oracle_user == "app"
    assert oracle_password == "super-secret"
    assert oracle18c_service_name == "xepdb1"
    assert oracle18c_port == 1514


def test_oracle23c_default_config(
    oracle_user: str, oracle_password: str, oracle23c_service_name: str, oracle23c_port: int
) -> None:
    assert oracle_user == "app"
    assert oracle_password == "super-secret"
    assert oracle23c_service_name == "FREEPDB1"
    assert oracle23c_port == 1513


def test_oracle_default_config(
    oracle_user: str,
    oracle_password: str,
    oracle_service_name: str,
    oracle_port: int,
    oracle23c_port: int,
    oracle_default_version: str,
) -> None:
    assert oracle_default_version == "oracle23c"
    assert oracle_user == "app"
    assert oracle_password == "super-secret"
    assert oracle_service_name == "FREEPDB1"
    assert oracle_port == 1513
    assert oracle_port == oracle23c_port


async def test_oracle18c_service(
    docker_ip: str,
    oracle18c_service: DockerServiceRegistry,
    oracle18c_service_name: str,
    oracle18c_port: int,
    oracle_user: str,
    oracle_password: str,
) -> None:
    conn = oracledb.connect(
        user=oracle_user, password=oracle_password, dsn=f"{docker_ip}:{oracle18c_port!s}/{oracle18c_service_name}"
    )
    with conn.cursor() as cur:
        cur.execute("SELECT 'Hello World!' FROM dual")
        res = cur.fetchall()[0][0]
        assert "Hello World!" in res


async def test_oracle23c_service(
    docker_ip: str,
    oracle23c_service: DockerServiceRegistry,
    oracle23c_service_name: str,
    oracle23c_port: int,
    oracle_user: str,
    oracle_password: str,
) -> None:
    conn = oracledb.connect(
        user=oracle_user, password=oracle_password, dsn=f"{docker_ip}:{oracle23c_port!s}/{oracle23c_service_name}"
    )
    with conn.cursor() as cur:
        cur.execute("SELECT 'Hello World!' FROM dual")
        res = cur.fetchall()[0][0]
        assert "Hello World!" in res
