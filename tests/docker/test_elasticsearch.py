from __future__ import annotations

from typing import TYPE_CHECKING

from elasticsearch7 import Elasticsearch as Elasticsearch7
from elasticsearch8 import Elasticsearch as Elasticsearch8

from pytest_databases.docker.elastic_search import ElasticsearchService

if TYPE_CHECKING:
    pass

pytest_plugins = [
    "pytest_databases.docker.elastic_search",
]


def test_elasticsearch7_service(elasticsearch7_service: ElasticsearchService) -> None:
    with Elasticsearch7(
        hosts=[
            {
                "host": elasticsearch7_service.host,
                "port": elasticsearch7_service.port,
                "scheme": elasticsearch7_service.scheme,
            }
        ],
        verify_certs=False,
        http_auth=(elasticsearch7_service.user, elasticsearch7_service.password),
    ) as client:
        info = client.info()

    assert info["version"]["number"] == "7.17.19"


def test_elasticsearch8_service(elasticsearch8_service: ElasticsearchService) -> None:
    with Elasticsearch8(
        hosts=[
            {
                "host": elasticsearch8_service.host,
                "port": elasticsearch8_service.port,
                "scheme": elasticsearch8_service.scheme,
            }
        ],
        verify_certs=False,
        basic_auth=(elasticsearch8_service.user, elasticsearch8_service.password),
    ) as client:
        info = client.info()

    assert info["version"]["number"] == "8.13.0"
