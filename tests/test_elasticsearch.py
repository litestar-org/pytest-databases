"""Tests for Elasticsearch container service fixtures."""

from __future__ import annotations

import sys
import urllib.error
from typing import TYPE_CHECKING
from unittest.mock import MagicMock

import pytest

from pytest_databases.docker.elastic_search import (
    _check_cluster_health,
    _ping_elasticsearch,
    elasticsearch7_responsive,
    elasticsearch8_responsive,
    elasticsearch_7_image,
    elasticsearch_8_image,
    elasticsearch_9_image,
    provide_elasticsearch_service,
)
from pytest_databases.types import ServiceContainer
from tests.conftest import unwrap_fixture

if TYPE_CHECKING:
    from collections.abc import Callable


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
    """Verify provide_elasticsearch_service forwards memory_limit and removes the container after the session."""
    assert unwrap_fixture(elasticsearch_7_image)() == "elasticsearch:7.17.19"
    assert unwrap_fixture(elasticsearch_8_image)() == "elasticsearch:8.13.0"
    assert unwrap_fixture(elasticsearch_9_image)() == "elasticsearch:9.5.5"

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
    assert run_kwargs["transient"] is True


@pytest.mark.parametrize(
    ("helper", "module_name", "auth_kwarg"),
    [
        (elasticsearch7_responsive, "elasticsearch7", "http_auth"),
        (elasticsearch8_responsive, "elasticsearch8", "basic_auth"),
    ],
)
def test_deprecated_responsive_helpers_warn_once_and_ping(
    monkeypatch: pytest.MonkeyPatch,
    helper: Callable[..., bool],
    module_name: str,
    auth_kwarg: str,
) -> None:
    """Verify the v0.19.0 responsive helpers warn once at the caller and ping through the lazily imported client."""
    fake_module = MagicMock()
    fake_client = fake_module.Elasticsearch.return_value.__enter__.return_value
    fake_client.ping.return_value = True
    imported: list[str] = []

    def fake_import(name: str) -> MagicMock:
        imported.append(name)
        return fake_module

    monkeypatch.setattr("pytest_databases.docker.elastic_search.importlib.import_module", fake_import)

    with pytest.warns(DeprecationWarning, match=helper.__name__) as record:
        assert helper("http", "127.0.0.1", 9200, "elastic", "changeme", "db") is True

    assert len(record) == 1
    assert record[0].filename == __file__
    assert imported == [module_name]
    fake_module.Elasticsearch.assert_called_once_with(
        hosts=[{"host": "127.0.0.1", "port": 9200, "scheme": "http"}],
        verify_certs=False,
        **{auth_kwarg: ("elastic", "changeme")},
    )


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


def test_elasticsearch_health_and_ping_error_branches(monkeypatch: pytest.MonkeyPatch) -> None:
    """Verify _check_cluster_health and _ping_elasticsearch error branches."""

    def fake_urlopen_non_200(req: object, timeout: float = 2.0) -> object:
        cm = MagicMock()
        cm.__enter__.return_value = MagicMock(status=503)
        return cm

    monkeypatch.setattr("pytest_databases.docker.elastic_search.urllib.request.urlopen", fake_urlopen_non_200)
    assert _check_cluster_health("127.0.0.1", 9200) is False

    monkeypatch.setattr(
        "pytest_databases.docker.elastic_search.urllib.request.urlopen",
        MagicMock(side_effect=urllib.error.URLError("down")),
    )
    assert _check_cluster_health("127.0.0.1", 9200) is False

    fake_mod = MagicMock()
    fake_mod.Elasticsearch.side_effect = OSError("failed")
    monkeypatch.setitem(sys.modules, "fake_es_mod", fake_mod)
    assert _ping_elasticsearch("fake_es_mod", "http_auth", "http", "127.0.0.1", 9200, "elastic", "pwd") is False


def test_elasticsearch_all_fixtures_inprocess(pytester: pytest.Pytester) -> None:
    """Verify all Elasticsearch fixtures execute in-process with mocked docker_service."""
    pytester.makepyfile("""
    from contextlib import contextmanager
    from unittest.mock import MagicMock
    import pytest
    from pytest_databases.types import ServiceContainer

    pytest_plugins = ["pytest_databases.docker.elastic_search"]

    @pytest.fixture(scope="session")
    def docker_service():
        mock_ds = MagicMock()
        @contextmanager
        def _run(image, **kwargs):
            yield ServiceContainer(host="127.0.0.1", port=9200, container=MagicMock())
        mock_ds.run.side_effect = _run
        return mock_ds

    def test_fixtures(
        elasticsearch_service_memory_limit,
        elasticsearch_7_image,
        elasticsearch_8_image,
        elasticsearch_9_image,
        elasticsearch_7_service,
        elasticsearch_8_service,
        elasticsearch_9_service,
        elasticsearch_service,
    ):
        assert elasticsearch_service_memory_limit == "1g"
        assert "7." in elasticsearch_7_image
        assert "8." in elasticsearch_8_image
        assert "9." in elasticsearch_9_image
        assert elasticsearch_7_service.port == 9200
        assert elasticsearch_8_service.port == 9200
        assert elasticsearch_9_service.port == 9200
        assert elasticsearch_service.port == 9200
    """)
    result = pytester.runpytest("-p", "no:sugar", "-p", "pytest_databases", "-W", "ignore::DeprecationWarning")
    result.assert_outcomes(passed=1)
