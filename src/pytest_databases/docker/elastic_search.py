from __future__ import annotations

import contextlib
import dataclasses
import json
import urllib.error
import urllib.request
from typing import TYPE_CHECKING

import pytest

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


def _check_cluster_health(host: str, port: int, *, timeout: float = 2.0) -> bool:
    request = urllib.request.Request(
        f"http://{host}:{port}/_cluster/health",
        headers={"Accept": "application/json"},
    )
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:  # noqa: S310
            if response.status != 200:
                return False
            payload = json.loads(response.read().decode("utf-8"))
    except (urllib.error.URLError, OSError, ValueError):
        return False
    return payload.get("status") in {"yellow", "green"}


@pytest.fixture(scope="session")
def elasticsearch_service_memory_limit() -> str:
    return "500m"


@contextlib.contextmanager
def _provide_elasticsearch_service(
    docker_service: DockerService,
    image: str,
    name: str,
    memory_limit: str,
) -> Generator[ElasticsearchService, None, None]:
    user = "elastic"
    password = "changeme"
    database = "db"
    scheme = "http"

    def check(_service: ServiceContainer) -> bool:
        return _check_cluster_health(_service.host, _service.port)

    with docker_service.run(
        image=image,
        name=name,
        container_port=9200,
        env={
            "discovery.type": "single-node",
            "xpack.security.enabled": "false",
            "ingest.geoip.downloader.enabled": "false",
            "cluster.routing.allocation.disk.threshold_enabled": "false",
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
            container=service.container,
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
        memory_limit=elasticsearch_service_memory_limit,
    ) as service:
        yield service


@pytest.fixture(autouse=False, scope="session")
def elasticsearch_service(elasticsearch_8_service: ElasticsearchService) -> ElasticsearchService:
    return elasticsearch_8_service
