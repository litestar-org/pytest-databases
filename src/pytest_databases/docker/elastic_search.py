"""Elasticsearch container service fixtures."""

from __future__ import annotations

import contextlib
import dataclasses
import importlib
import json
import urllib.error
import urllib.request
import warnings
from typing import TYPE_CHECKING, Any

import pytest

from pytest_databases.types import ServiceContainer

if TYPE_CHECKING:
    from collections.abc import Generator

    from pytest_databases._service import DockerService

__all__ = (
    "ElasticsearchService",
    "elasticsearch7_responsive",
    "elasticsearch8_responsive",
    "elasticsearch_7_image",
    "elasticsearch_7_service",
    "elasticsearch_8_image",
    "elasticsearch_8_service",
    "elasticsearch_9_image",
    "elasticsearch_9_service",
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


def elasticsearch7_responsive(scheme: str, host: str, port: int, user: str, password: str, database: str) -> bool:
    """Ping an Elasticsearch 7 node with the ``elasticsearch7`` client.

    .. deprecated:: 0.20.0
        ``elasticsearch7_responsive`` will be removed in v1.0.0. ``elasticsearch_7_service`` checks readiness itself.

    Returns:
        True when the node answers the ping, otherwise False.
    """
    warnings.warn(
        "'elasticsearch7_responsive' is deprecated in v0.20.0 and will be removed in v1.0.0. "
        "'elasticsearch_7_service' checks readiness without a client.",
        DeprecationWarning,
        stacklevel=2,
    )
    return _ping_elasticsearch("elasticsearch7", "http_auth", scheme, host, port, user, password)


def elasticsearch8_responsive(scheme: str, host: str, port: int, user: str, password: str, database: str) -> bool:
    """Ping an Elasticsearch 8 node with the ``elasticsearch8`` client.

    .. deprecated:: 0.20.0
        ``elasticsearch8_responsive`` will be removed in v1.0.0. ``elasticsearch_8_service`` checks readiness itself.

    Returns:
        True when the node answers the ping, otherwise False.
    """
    warnings.warn(
        "'elasticsearch8_responsive' is deprecated in v0.20.0 and will be removed in v1.0.0. "
        "'elasticsearch_8_service' checks readiness without a client.",
        DeprecationWarning,
        stacklevel=2,
    )
    return _ping_elasticsearch("elasticsearch8", "basic_auth", scheme, host, port, user, password)


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
        transient=True,
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
    """Return the container memory limit for Elasticsearch services."""
    return "1g"


@pytest.fixture(scope="session")
def elasticsearch_7_image() -> str:
    """Return the Elasticsearch 7 container image."""
    return "elasticsearch:7.17.19"


@pytest.fixture(scope="session")
def elasticsearch_8_image() -> str:
    """Return the Elasticsearch 8 container image."""
    return "elasticsearch:8.13.0"


@pytest.fixture(scope="session")
def elasticsearch_9_image() -> str:
    """Return the Elasticsearch 9 container image."""
    return "elasticsearch:9.5.5"


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
def elasticsearch_9_service(
    docker_service: DockerService,
    elasticsearch_9_image: str,
    elasticsearch_service_memory_limit: str,
) -> Generator[ElasticsearchService, None, None]:
    """Provide a running Elasticsearch 9 container service.

    Yields:
        Active ElasticsearchService instance.
    """
    with provide_elasticsearch_service(
        docker_service=docker_service,
        image=elasticsearch_9_image,
        name="elasticsearch-9",
        memory_limit=elasticsearch_service_memory_limit,
    ) as service:
        yield service


@pytest.fixture(autouse=False, scope="session")
def elasticsearch_service(elasticsearch_8_service: ElasticsearchService) -> ElasticsearchService:
    """Provide the default Elasticsearch container service."""
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


def _ping_elasticsearch(
    module_name: str,
    auth_kwarg: str,
    scheme: str,
    host: str,
    port: int,
    user: str,
    password: str,
) -> bool:
    """Ping a node with the lazily imported Elasticsearch client from ``module_name``.

    Returns:
        The client's ``ping()`` result, or False when the client cannot be constructed.
    """
    client_cls: Any = importlib.import_module(module_name).Elasticsearch
    try:
        with client_cls(
            hosts=[{"host": host, "port": port, "scheme": scheme}],
            verify_certs=False,
            **{auth_kwarg: (user, password)},
        ) as client:
            return bool(client.ping())
    except (OSError, ValueError):
        return False
