"""Tests for Elasticsearch container service fixtures."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any
from unittest.mock import MagicMock

from pytest_databases.docker.elastic_search import (
    elasticsearch_7_image,
    elasticsearch_8_image,
    elasticsearch_9_image,
    provide_elasticsearch_service,
)
from pytest_databases.types import ServiceContainer

if TYPE_CHECKING:
    from collections.abc import Callable

    import pytest


def test_plugin_imports_without_elasticsearch_clients(pytester: pytest.Pytester) -> None:
    """Verify elastic_search plugin imports cleanly without client packages."""
    pytester.makepyfile("""
    import builtins

    def test_import() -> None:
        original_import = builtins.__import__

        def blocked_import(name, globals=None, locals=None, fromlist=(), level=0):
            if name in {"elasticsearch7", "elasticsearch8"}:
                raise ModuleNotFoundError(name)
            return original_import(name, globals, locals, fromlist, level)

        builtins.__import__ = blocked_import
        try:
            import pytest_databases.docker.elastic_search
        finally:
            builtins.__import__ = original_import
    """)

    result = pytester.runpytest_subprocess("-p", "pytest_databases", "-vv")
    result.assert_outcomes(passed=1)


def test_elasticsearch_memory_limit_forwarded_and_images() -> None:
    """Verify provide_elasticsearch_service forwards memory_limit to mem_limit (issue #152)."""
    assert _unwrap_fixture(elasticsearch_7_image)() == "elasticsearch:7.17.19"
    assert _unwrap_fixture(elasticsearch_8_image)() == "elasticsearch:8.13.0"
    assert _unwrap_fixture(elasticsearch_9_image)() == "elasticsearch:9.5.5"

    mock_docker = MagicMock()
    mock_container = MagicMock()
    mock_docker.run.return_value.__enter__.return_value = ServiceContainer(
        host="127.0.0.1",
        port=19200,
        container=mock_container,
    )

    with provide_elasticsearch_service(
        docker_service=mock_docker,
        image="elasticsearch:8.13.0",
        name="elasticsearch-8",
        memory_limit="2g",
    ) as service:
        assert service.port == 19200

    run_kwargs = mock_docker.run.call_args.kwargs
    assert run_kwargs["mem_limit"] == "2g"
    assert run_kwargs["image"] == "elasticsearch:8.13.0"


def test_elasticsearch_7(pytester: pytest.Pytester) -> None:
    """Verify elasticsearch_7_service launches Elasticsearch 7."""
    pytester.makepyfile("""
    import json
    import urllib.request

    pytest_plugins = ["pytest_databases.docker.elastic_search"]

    def get_es(service, path):
        url = f"{service.scheme}://{service.host}:{service.port}{path}"
        with urllib.request.urlopen(url, timeout=5) as response:
            return json.loads(response.read().decode("utf-8"))

    def test(elasticsearch_7_service) -> None:
        info = get_es(elasticsearch_7_service, "/")
        assert info["version"]["number"] == "7.17.19"
    """)

    result = pytester.runpytest_subprocess("-p", "pytest_databases")
    result.assert_outcomes(passed=1)


def test_elasticsearch_8(pytester: pytest.Pytester) -> None:
    """Verify elasticsearch_8_service launches Elasticsearch 8."""
    pytester.makepyfile("""
    import json
    import urllib.request

    pytest_plugins = ["pytest_databases.docker.elastic_search"]

    def get_es(service, path):
        url = f"{service.scheme}://{service.host}:{service.port}{path}"
        with urllib.request.urlopen(url, timeout=5) as response:
            return json.loads(response.read().decode("utf-8"))

    def test(elasticsearch_8_service) -> None:
        info = get_es(elasticsearch_8_service, "/")
        assert info["version"]["number"] == "8.13.0"
    """)

    result = pytester.runpytest_subprocess("-p", "pytest_databases")
    result.assert_outcomes(passed=1)


def test_elasticsearch_9(pytester: pytest.Pytester) -> None:
    """Verify elasticsearch_9_service launches Elasticsearch 9."""
    pytester.makepyfile("""
    import json
    import urllib.request

    pytest_plugins = ["pytest_databases.docker.elastic_search"]

    def get_es(service, path):
        url = f"{service.scheme}://{service.host}:{service.port}{path}"
        with urllib.request.urlopen(url, timeout=5) as response:
            return json.loads(response.read().decode("utf-8"))

    def test(elasticsearch_9_service) -> None:
        info = get_es(elasticsearch_9_service, "/")
        assert info["version"]["number"] == "9.5.5"
    """)

    result = pytester.runpytest_subprocess("-p", "pytest_databases")
    result.assert_outcomes(passed=1)


def test_elasticsearch_index_round_trip(pytester: pytest.Pytester) -> None:
    """Verify indexing and retrieving a document in Elasticsearch."""
    pytester.makepyfile("""
    import json
    import urllib.request

    pytest_plugins = ["pytest_databases.docker.elastic_search"]

    def es_request(service, method, path, body=None):
        url = f"{service.scheme}://{service.host}:{service.port}{path}"
        data = json.dumps(body).encode("utf-8") if body is not None else None
        headers = {"Content-Type": "application/json"} if data is not None else {}
        request = urllib.request.Request(url, data=data, method=method, headers=headers)
        with urllib.request.urlopen(request, timeout=30) as response:
            return json.loads(response.read().decode("utf-8"))

    def test(elasticsearch_service) -> None:
        document = {"title": "pytest-databases", "kind": "smoke"}
        es_request(elasticsearch_service, "PUT", "/pytest_databases", body={"settings": {"number_of_replicas": 0}})
        es_request(elasticsearch_service, "PUT", "/pytest_databases/_doc/1", body=document)
        fetched = es_request(elasticsearch_service, "GET", "/pytest_databases/_doc/1")
        assert fetched["_source"] == document
    """)

    result = pytester.runpytest_subprocess("-p", "pytest_databases")
    result.assert_outcomes(passed=1)


def _unwrap_fixture(fixture_def: Any) -> Callable[..., Any]:
    """Return the underlying callable wrapped by a pytest fixture definition."""
    return fixture_def.__wrapped__
