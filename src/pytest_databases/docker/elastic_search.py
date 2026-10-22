"""Elasticsearch container service fixtures."""

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

__all__ = (
    "ElasticsearchService",
    "elasticsearch_7_image",
    "elasticsearch_7_service",
    "elasticsearch_8_image",
    "elasticsearch_8_service",
    "elasticsearch_service",
    "elasticsearch_service_memory_limit",
    "provide_elasticsearch_service",
)


@dataclasses.dataclass
class ElasticsearchService(ServiceContainer):
    """Service handle for a running Elasticsearch container."""

    scheme: str
    user: str
    password: str
    database: str


@contextlib.contextmanager
def provide_elasticsearch_service(
    docker_service: DockerService,
    image: str,
    name: str,
    memory_limit: str,
) -> Generator[ElasticsearchService, None, None]:
    """Start and manage an Elasticsearch container service.

    Yields:
        Active ElasticsearchService instance.
    """
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
        transient=False,
        mem_limit=memory_limit,
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


@pytest.fixture(scope="session")
def elasticsearch_service_memory_limit() -> str:
    """Return the container memory limit for Elasticsearch services.

    Returns:
        Memory limit string.
    """
    return "1g"


@pytest.fixture(scope="session")
def elasticsearch_7_image() -> str:
    """Return the Elasticsearch 7 container image.

    Returns:
        Container image tag.
    """
    return "elasticsearch:7.17.19"


@pytest.fixture(scope="session")
def elasticsearch_8_image() -> str:
    """Return the Elasticsearch 8 container image.

    Returns:
        Container image tag.
    """
    return "elasticsearch:8.13.0"


@pytest.fixture(autouse=False, scope="session")
def elasticsearch_7_service(
    docker_service: DockerService,
    elasticsearch_7_image: str,
    elasticsearch_service_memory_limit: str,
) -> Generator[ElasticsearchService, None, None]:
    """Provide a running Elasticsearch 7 container service.

    Yields:
        Active ElasticsearchService instance.
    """
    with provide_elasticsearch_service(
        docker_service=docker_service,
        image=elasticsearch_7_image,
        name="elasticsearch-7",
        memory_limit=elasticsearch_service_memory_limit,
    ) as service:
        yield service


@pytest.fixture(autouse=False, scope="session")
def elasticsearch_8_service(
    docker_service: DockerService,
    elasticsearch_8_image: str,
    elasticsearch_service_memory_limit: str,
) -> Generator[ElasticsearchService, None, None]:
    """Provide a running Elasticsearch 8 container service.

    Yields:
        Active ElasticsearchService instance.
    """
    with provide_elasticsearch_service(
        docker_service=docker_service,
        image=elasticsearch_8_image,
        name="elasticsearch-8",
        memory_limit=elasticsearch_service_memory_limit,
    ) as service:
        yield service


@pytest.fixture(autouse=False, scope="session")
def elasticsearch_service(elasticsearch_8_service: ElasticsearchService) -> ElasticsearchService:
    """Provide the default Elasticsearch container service.

    Returns:
        Active ElasticsearchService instance.
    """
    return elasticsearch_8_service


def _check_cluster_health(host: str, port: int, *, timeout: float = 2.0) -> bool:
    request = urllib.request.Request(
        f"http://{host}:{port}/_cluster/health",
        headers={"Accept": "application/json"},
    )
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            if response.status != 200:
                return False
            payload = json.loads(response.read().decode("utf-8"))
    except (urllib.error.URLError, OSError, ValueError):
        return False
    return payload.get("status") in {"yellow", "green"}
