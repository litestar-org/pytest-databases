from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    import pytest


def test_plugin_imports_without_elasticsearch_clients(pytester: pytest.Pytester) -> None:
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


def test_elasticsearch_7(pytester: pytest.Pytester) -> None:
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


def test_elasticsearch_index_round_trip(pytester: pytest.Pytester) -> None:
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
