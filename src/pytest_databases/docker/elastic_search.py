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

from pathlib import Path
from typing import TYPE_CHECKING

import pytest
from elasticsearch7 import AsyncElasticsearch as Elasticsearch7
from elasticsearch7 import AsyncElasticsearch as Elasticsearch8

if TYPE_CHECKING:
    from pytest_databases.docker import DockerServiceRegistry


async def elasticsearch7_responsive(scheme: str, host: str, port: int, user: str, password: str, database: str) -> bool:
    try:
        async with Elasticsearch7(
            hosts=[{"host": host, "port": port, "scheme": scheme}], verify_certs=False, http_auth=(user, password)
        ) as client:
            return await client.ping()
    except Exception:  # noqa: BLE001
        return False


async def elasticsearch8_responsive(scheme: str, host: str, port: int, user: str, password: str, database: str) -> bool:
    try:
        async with Elasticsearch8(
            hosts=[{"host": host, "port": port, "scheme": scheme}], verify_certs=False, basic_auth=(user, password)
        ) as client:
            return await client.ping()
    except Exception:  # noqa: BLE001
        return False


@pytest.fixture
def elasticsearch_user() -> str:
    return "elastic"


@pytest.fixture
def elasticsearch_password() -> str:
    return "changeme"


@pytest.fixture
def elasticsearch_database() -> str:
    return "db"


@pytest.fixture
def elasticsearch_scheme() -> str:
    return "http"


@pytest.fixture
def elasticsearch7_port() -> int:
    return 9200


@pytest.fixture
def elasticsearch8_port() -> int:
    return 9201


@pytest.fixture(scope="session")
def docker_compose_files() -> list[Path]:
    return [Path(Path(__file__).parent / "docker-compose.elasticsearch.yml")]


@pytest.fixture(scope="session")
def default_elasticsearch_service_name() -> str:
    return "elasticsearch8"


@pytest.fixture(autouse=False)
async def elasticsearch7_service(
    docker_services: DockerServiceRegistry,
    docker_compose_files: list[Path],
    elasticsearch7_port: int,
    elasticsearch_database: str,
    elasticsearch_user: str,
    elasticsearch_password: str,
    elasticsearch_scheme: str,
) -> None:
    await docker_services.start(
        "elasticsearch7",
        docker_compose_files=docker_compose_files,
        timeout=45,
        pause=1,
        check=elasticsearch7_responsive,
        port=elasticsearch7_port,
        database=elasticsearch_database,
        user=elasticsearch_user,
        password=elasticsearch_password,
        scheme=elasticsearch_scheme,
    )


@pytest.fixture(autouse=False)
async def elasticsearch8_service(
    docker_services: DockerServiceRegistry,
    docker_compose_files: list[Path],
    elasticsearch8_port: int,
    elasticsearch_database: str,
    elasticsearch_user: str,
    elasticsearch_password: str,
    elasticsearch_scheme: str,
) -> None:
    await docker_services.start(
        "elasticsearch8",
        docker_compose_files=docker_compose_files,
        timeout=45,
        pause=1,
        check=elasticsearch8_responsive,
        port=elasticsearch8_port,
        database=elasticsearch_database,
        user=elasticsearch_user,
        password=elasticsearch_password,
        scheme=elasticsearch_scheme,
    )


@pytest.fixture(autouse=False)
async def elasticsearch_service(
    docker_services: DockerServiceRegistry,
    default_elasticsearch_service_name: str,
    docker_compose_files: list[Path],
    elasticsearch8_port: int,
    elasticsearch_database: str,
    elasticsearch_user: str,
    elasticsearch_password: str,
    elasticsearch_scheme: str,
) -> None:
    await docker_services.start(
        name=default_elasticsearch_service_name,
        docker_compose_files=docker_compose_files,
        timeout=45,
        pause=1,
        check=elasticsearch8_responsive,
        port=elasticsearch8_port,
        database=elasticsearch_database,
        user=elasticsearch_user,
        password=elasticsearch_password,
        scheme=elasticsearch_scheme,
    )
