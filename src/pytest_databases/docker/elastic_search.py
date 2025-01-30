from __future__ import annotations

import contextlib
import dataclasses
import traceback
from typing import TYPE_CHECKING

import pytest
from elasticsearch7 import Elasticsearch as Elasticsearch7
from elasticsearch7 import Elasticsearch as Elasticsearch8

from pytest_databases.types import ServiceContainer

if TYPE_CHECKING:
    from collections.abc import Generator

    from pytest_databases._service import DockerService


@dataclasses.dataclass
class ElasticsearchService(ServiceContainer):
    scheme: str
    user: str
    password: str
    database: str


def elasticsearch7_responsive(scheme: str, host: str, port: int, user: str, password: str, database: str) -> bool:
    try:
        with Elasticsearch7(
            hosts=[{"host": host, "port": port, "scheme": scheme}], verify_certs=False, http_auth=(user, password)
        ) as client:
            return client.ping()
    except Exception:  # noqa: BLE001
        return False


def elasticsearch8_responsive(scheme: str, host: str, port: int, user: str, password: str, database: str) -> bool:
    try:
        with Elasticsearch8(
            hosts=[{"host": host, "port": port, "scheme": scheme}], verify_certs=False, basic_auth=(user, password)
        ) as client:
            return client.ping()
    except Exception:  # noqa: BLE001
        traceback.print_exc()
        return False


@pytest.fixture(scope="session")
def elasticsearch_service_memory_limit() -> str:
    return "500m"


@contextlib.contextmanager
def _provide_elasticsearch_service(
    docker_service: DockerService,
    image: str,
    name: str,
    client_cls: type[Elasticsearch7 | Elasticsearch8],
    memory_limit: str,
) -> Generator[ElasticsearchService, None, None]:
    user = "elastic"
    password = "changeme"
    database = "db"
    scheme = "http"

    def check(_service: ServiceContainer) -> bool:
        try:
            with client_cls(
                hosts=[{"host": _service.host, "port": _service.port, "scheme": scheme}],
                verify_certs=False,
                http_auth=(user, password),
            ) as client:
                return client.ping()
        except Exception:  # noqa: BLE001
            return False

    with docker_service.run(
        image=image,
        name=name,
        container_port=9200,
        env={
            "discovery.type": "single-node",
            "xpack.security.enabled": "false",
        },
        check=check,
        timeout=120,
        pause=1,
        transient=True,
        mem_limit="1g",
    ) as service:
        yield ElasticsearchService(
            host=service.host,
            port=service.port,
            user=user,
            password=password,
            scheme=scheme,
            database=database,
        )


@pytest.fixture(autouse=False, scope="session")
def elasticsearch_7_service(
    docker_service: DockerService,
    elasticsearch_service_memory_limit: str,
) -> Generator[ElasticsearchService, None, None]:
    with _provide_elasticsearch_service(
        docker_service=docker_service,
        image="elasticsearch:7.17.19",
        name="elasticsearch-7",
        client_cls=Elasticsearch7,
        memory_limit=elasticsearch_service_memory_limit,
    ) as service:
        yield service


@pytest.fixture(autouse=False, scope="session")
def elasticsearch_8_service(
    docker_service: DockerService,
    elasticsearch_service_memory_limit: str,
) -> Generator[ElasticsearchService, None, None]:
    with _provide_elasticsearch_service(
        docker_service=docker_service,
        image="elasticsearch:8.13.0",
        name="elasticsearch-8",
        client_cls=Elasticsearch8,
        memory_limit=elasticsearch_service_memory_limit,
    ) as service:
        yield service


@pytest.fixture(autouse=False, scope="session")
def elasticsearch_service(elasticsearch8_service: ElasticsearchService) -> ElasticsearchService:
    return elasticsearch8_service
