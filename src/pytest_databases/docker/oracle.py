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


def oracle_responsive(host: str, port: int, service_name: str, user: str, password: str) -> bool:
    try:
        conn = oracledb.connect(
            host=host,
            port=port,
            user=user,
            service_name=service_name,
            password=password,
        )
        with conn.cursor() as cursor:
            cursor.execute("SELECT 1 FROM dual")
            resp = cursor.fetchone()
        return resp[0] == 1 if resp is not None else False
    except Exception:  # noqa: BLE001
        return False


@pytest.fixture()
def oracle_user() -> str:
    return "app"


@pytest.fixture()
def oracle_password() -> str:
    return "super-secret"


@pytest.fixture()
def oracle18c_service_name() -> str:
    return "xepdb1"


@pytest.fixture()
def oracle23c_service_name() -> str:
    return "FREEPDB1"


@pytest.fixture()
def oracle_service_name(oracle23c_service_name: str) -> str:
    return oracle23c_service_name


@pytest.fixture()
def oracle18c_port() -> int:
    return 1514


@pytest.fixture()
def oracle23c_port() -> int:
    return 1513


@pytest.fixture()
def oracle_default_version() -> str:
    return "oracle23c"


@pytest.fixture()
def oracle_port(oracle23c_port: int) -> int:
    return oracle23c_port


@pytest.fixture(autouse=False)
async def oracle23c_service(
    docker_services: DockerServiceRegistry,
    oracle23c_port: int,
    oracle23c_service_name: str,
    oracle_user: str,
    oracle_password: str,
) -> None:
    await docker_services.start(
        "oracle23c",
        timeout=90,
        pause=1,
        check=oracle_responsive,
        port=oracle23c_port,
        service_name=oracle23c_service_name,
        user=oracle_user,
        password=oracle_password,
    )


@pytest.fixture(autouse=False)
async def oracle18c_service(
    docker_services: DockerServiceRegistry,
    oracle18c_port: int,
    oracle18c_service_name: str,
    oracle_user: str,
    oracle_password: str,
) -> None:
    await docker_services.start(
        "oracle18c",
        timeout=90,
        pause=1,
        check=oracle_responsive,
        port=oracle18c_port,
        service_name=oracle18c_service_name,
        user=oracle_user,
        password=oracle_password,
    )


# alias to the latest
@pytest.fixture(autouse=False)
async def oracle_service(
    docker_services: DockerServiceRegistry,
    oracle_default_version: str,
    oracle_port: int,
    oracle_service_name: str,
    oracle_user: str,
    oracle_password: str,
) -> None:
    await docker_services.start(
        oracle_default_version,
        timeout=90,
        pause=1,
        check=oracle_responsive,
        port=oracle_port,
        service_name=oracle_service_name,
        user=oracle_user,
        password=oracle_password,
    )
