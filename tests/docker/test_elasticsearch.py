from __future__ import annotations

from typing import TYPE_CHECKING, Any, AsyncGenerator, Callable
from unittest import mock

import pytest
from elasticsearch7 import AsyncElasticsearch as Elasticsearch7
from elasticsearch8 import AsyncElasticsearch as Elasticsearch8

from pytest_databases.docker.elastic_search import elasticsearch7_responsive, elasticsearch8_responsive

if TYPE_CHECKING:
    from pathlib import Path

    from pytest_databases.docker import DockerServiceRegistry

pytestmark = pytest.mark.anyio
pytest_plugins = [
    "pytest_databases.docker.elastic_search",
]


@pytest.fixture
async def elasticsearch7_service(
    elasticsearch_docker_services: DockerServiceRegistry,
    elasticsearch_docker_compose_files: list[Path],
    elasticsearch7_port: int,
    elasticsearch_database: str,
    elasticsearch_user: str,
    elasticsearch_password: str,
    elasticsearch_scheme: str,
) -> AsyncGenerator[Any, Any]:
    """Overwrites fixture to stop container after the test."""
    try:
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
    finally:
        elasticsearch_docker_services.stop("elasticsearch7")


@pytest.fixture
async def elasticsearch8_service(
    elasticsearch_docker_services: DockerServiceRegistry,
    elasticsearch_docker_compose_files: list[Path],
    elasticsearch8_port: int,
    elasticsearch_database: str,
    elasticsearch_user: str,
    elasticsearch_password: str,
    elasticsearch_scheme: str,
) -> AsyncGenerator[Any, Any]:
    """Overwrites fixture to stop container after the test."""
    try:
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
    finally:
        elasticsearch_docker_services.stop("elasticsearch8")


def test_elasticsearch7_default_config(
    elasticsearch7_port: str, elasticsearch_user: str, elasticsearch_password: str, elasticsearch_scheme: str
) -> None:
    assert elasticsearch7_port == 9200
    assert elasticsearch_user == "elastic"
    assert elasticsearch_password == "changeme"
    assert elasticsearch_scheme == "http"


def test_elasticsearch8_default_config(
    elasticsearch8_port: str, elasticsearch_user: str, elasticsearch_password: str, elasticsearch_scheme: str
) -> None:
    assert elasticsearch8_port == 9201
    assert elasticsearch_user == "elastic"
    assert elasticsearch_password == "changeme"
    assert elasticsearch_scheme == "http"


async def test_elasticsearch7_service(
    elasticsearch_docker_ip: str,
    elasticsearch7_service: DockerServiceRegistry,
    elasticsearch7_port: str,
    elasticsearch_user: str,
    elasticsearch_password: str,
    elasticsearch_scheme: str,
) -> None:
    async with Elasticsearch7(
        hosts=[{"host": elasticsearch_docker_ip, "port": elasticsearch7_port, "scheme": elasticsearch_scheme}],
        verify_certs=False,
        http_auth=(elasticsearch_user, elasticsearch_password),
    ) as client:
        info = await client.info()

    assert info["version"]["number"] == "7.17.19"


async def test_elasticsearch8_service(
    elasticsearch_docker_ip: str,
    elasticsearch8_service: DockerServiceRegistry,
    elasticsearch8_port: str,
    elasticsearch_user: str,
    elasticsearch_password: str,
    elasticsearch_scheme: str,
) -> None:
    async with Elasticsearch8(
        hosts=[{"host": elasticsearch_docker_ip, "port": elasticsearch8_port, "scheme": elasticsearch_scheme}],
        verify_certs=False,
        basic_auth=(elasticsearch_user, elasticsearch_password),
    ) as client:
        info = await client.info()

    assert info["version"]["number"] == "8.13.0"


@pytest.mark.parametrize(
    "responsive, path_to_mock",
    (
        (elasticsearch7_responsive, "pytest_databases.docker.elastic_search.Elasticsearch7.ping"),
        (elasticsearch8_responsive, "pytest_databases.docker.elastic_search.Elasticsearch8.ping"),
    ),
)
async def test_elasticsearch_responsive(responsive: Callable, path_to_mock: str) -> None:
    with mock.patch(path_to_mock, mock.Mock(side_effect=Exception)):
        assert not await responsive(scheme="", host="", port="", user="", password="", database="")
