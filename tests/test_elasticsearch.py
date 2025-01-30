from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    import pytest


def test_elasticsearch_7(pytester: pytest.Pytester) -> None:
    pytester.makepyfile("""
    from elasticsearch7 import Elasticsearch

    pytest_plugins = ["pytest_databases.docker.elastic_search"]

    def test(elasticsearch_7_service) -> None:
        with Elasticsearch(
            hosts=[
                {
                    "host": elasticsearch_7_service.host,
                    "port": elasticsearch_7_service.port,
                    "scheme": elasticsearch_7_service.scheme,
                }
            ],
            verify_certs=False,
            http_auth=(elasticsearch_7_service.user, elasticsearch_7_service.password),
        ) as client:
            info = client.info()

        assert info["version"]["number"] == "7.17.19"
    """)

    result = pytester.runpytest()
    result.assert_outcomes(passed=1)


def test_elasticsearch_8(pytester: pytest.Pytester) -> None:
    pytester.makepyfile("""
    from elasticsearch7 import Elasticsearch

    pytest_plugins = ["pytest_databases.docker.elastic_search"]

    def test(elasticsearch_8_service) -> None:
        with Elasticsearch(
            hosts=[
                {
                    "host": elasticsearch_8_service.host,
                    "port": elasticsearch_8_service.port,
                    "scheme": elasticsearch_8_service.scheme,
                }
            ],
            verify_certs=False,
            basic_auth=(elasticsearch_8_service.user, elasticsearch_8_service.password),
        ) as client:
            info = client.info()

        assert info["version"]["number"] == "8.13.0"
    """)

    result = pytester.runpytest()
    result.assert_outcomes(passed=1)
