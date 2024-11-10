from __future__ import annotations

import contextlib
import dataclasses
import os
import sys
from pathlib import Path
from typing import TYPE_CHECKING

import pytest
from elasticsearch7 import Elasticsearch as Elasticsearch7
from elasticsearch7 import Elasticsearch as Elasticsearch8

from pytest_databases._service import DockerService
from pytest_databases.docker import DockerServiceRegistry
from pytest_databases.helpers import simple_string_hash
from pytest_databases.types import ServiceContainer

if TYPE_CHECKING:
    from collections.abc import Generator


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
        return False


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


@contextlib.contextmanager
def _provide_elasticsearch_service(
    docker_service: DockerService,
    image: str,
    name: str,
    client_cls: type[Elasticsearch7 | Elasticsearch8],
):
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
def elasticsearch7_service(docker_service: DockerService) -> Generator[ElasticsearchService, None, None]:
    with _provide_elasticsearch_service(
        docker_service=docker_service,
        image="elasticsearch:7.17.19",
        name="elasticsearch-7",
        client_cls=Elasticsearch7,
    ) as service:
        yield service


@pytest.fixture(autouse=False, scope="session")
def elasticsearch8_service(docker_service: DockerService) -> Generator[ElasticsearchService, None, None]:
    with _provide_elasticsearch_service(
        docker_service=docker_service,
        image="elasticsearch:8.13.0",
        name="elasticsearch-8",
        client_cls=Elasticsearch8,
    ) as service:
        yield service


@pytest.fixture(autouse=False, scope="session")
def elasticsearch_service(elasticsearch8_service) -> ElasticsearchService:
    return elasticsearch8_service
