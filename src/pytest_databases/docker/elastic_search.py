from __future__ import annotations

import os
import sys
from pathlib import Path
from typing import TYPE_CHECKING, AsyncGenerator

import pytest
from elasticsearch7 import AsyncElasticsearch as Elasticsearch7
from elasticsearch7 import AsyncElasticsearch as Elasticsearch8

from pytest_databases.docker import DockerServiceRegistry
from pytest_databases.helpers import simple_string_hash

if TYPE_CHECKING:
    from collections.abc import Generator


COMPOSE_PROJECT_NAME: str = f"pytest-databases-elasticsearch-{simple_string_hash(__file__)}"


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


@pytest.fixture(scope="session")
def elasticsearch_compose_project_name() -> str:
    return os.environ.get("COMPOSE_PROJECT_NAME", COMPOSE_PROJECT_NAME)


@pytest.fixture(autouse=False, scope="session")
def elasticsearch_docker_services(
    elasticsearch_compose_project_name: str, worker_id: str = "main"
) -> Generator[DockerServiceRegistry, None, None]:
    if os.getenv("GITHUB_ACTIONS") == "true" and sys.platform != "linux":
        pytest.skip("Docker not available on this platform")

    registry = DockerServiceRegistry(worker_id, compose_project_name=elasticsearch_compose_project_name)
    try:
        yield registry
    finally:
        registry.down()


@pytest.fixture(scope="session")
def elasticsearch_user() -> str:
    return "elastic"


@pytest.fixture(scope="session")
def elasticsearch_password() -> str:
    return "changeme"


@pytest.fixture(scope="session")
def elasticsearch_database() -> str:
    return "db"


@pytest.fixture(scope="session")
def elasticsearch_scheme() -> str:
    return "http"


@pytest.fixture(scope="session")
def elasticsearch7_port() -> int:
    return 9200


@pytest.fixture(scope="session")
def elasticsearch8_port() -> int:
    return 9201


@pytest.fixture(scope="session")
def elasticsearch_docker_compose_files() -> list[Path]:
    return [Path(Path(__file__).parent / "docker-compose.elasticsearch.yml")]


@pytest.fixture(scope="session")
def default_elasticsearch_service_name() -> str:
    return "elasticsearch8"


@pytest.fixture(scope="session")
def elasticsearch_docker_ip(elasticsearch_docker_services: DockerServiceRegistry) -> str:
    return elasticsearch_docker_services.docker_ip


@pytest.fixture(autouse=False, scope="session")
async def elasticsearch7_service(
    elasticsearch_docker_services: DockerServiceRegistry,
    elasticsearch_docker_compose_files: list[Path],
    elasticsearch7_port: int,
    elasticsearch_database: str,
    elasticsearch_user: str,
    elasticsearch_password: str,
    elasticsearch_scheme: str,
) -> AsyncGenerator[None, None]:
    await elasticsearch_docker_services.start(
        "elasticsearch7",
        docker_compose_files=elasticsearch_docker_compose_files,
        timeout=45,
        pause=1,
        check=elasticsearch7_responsive,
        port=elasticsearch7_port,
        database=elasticsearch_database,
        user=elasticsearch_user,
        password=elasticsearch_password,
        scheme=elasticsearch_scheme,
    )
    yield


@pytest.fixture(autouse=False, scope="session")
async def elasticsearch8_service(
    elasticsearch_docker_services: DockerServiceRegistry,
    elasticsearch_docker_compose_files: list[Path],
    elasticsearch8_port: int,
    elasticsearch_database: str,
    elasticsearch_user: str,
    elasticsearch_password: str,
    elasticsearch_scheme: str,
) -> AsyncGenerator[None, None]:
    await elasticsearch_docker_services.start(
        "elasticsearch8",
        docker_compose_files=elasticsearch_docker_compose_files,
        timeout=45,
        pause=1,
        check=elasticsearch8_responsive,
        port=elasticsearch8_port,
        database=elasticsearch_database,
        user=elasticsearch_user,
        password=elasticsearch_password,
        scheme=elasticsearch_scheme,
    )
    yield


@pytest.fixture(autouse=False, scope="session")
async def elasticsearch_service(
    elasticsearch_docker_services: DockerServiceRegistry,
    default_elasticsearch_service_name: str,
    elasticsearch_docker_compose_files: list[Path],
    elasticsearch8_port: int,
    elasticsearch_database: str,
    elasticsearch_user: str,
    elasticsearch_password: str,
    elasticsearch_scheme: str,
) -> AsyncGenerator[None, None]:
    await elasticsearch_docker_services.start(
        name=default_elasticsearch_service_name,
        docker_compose_files=elasticsearch_docker_compose_files,
        timeout=45,
        pause=1,
        check=elasticsearch8_responsive,
        port=elasticsearch8_port,
        database=elasticsearch_database,
        user=elasticsearch_user,
        password=elasticsearch_password,
        scheme=elasticsearch_scheme,
    )
    yield
