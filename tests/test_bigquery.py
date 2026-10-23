"""Tests for Google BigQuery emulator container service fixtures."""

from __future__ import annotations

import json
from types import SimpleNamespace
from typing import Any
from unittest.mock import MagicMock

import pytest

from pytest_databases.docker import bigquery as bigquery_mod
from pytest_databases.docker.bigquery import (
    BigQueryService,
    provide_bigquery_client,
    provide_bigquery_service,
    query_bigquery_emulator,
)
from pytest_databases.types import ServiceContainer


def test_plugin_imports_without_google_cloud_bigquery(pytester: pytest.Pytester) -> None:
    """Verify ``pytest_databases.docker.bigquery`` imports cleanly when Google Cloud libraries are absent."""
    pytester.makepyfile("""
    import builtins

    def test_import() -> None:
        original_import = builtins.__import__
        blocked = {
            "google.cloud.bigquery",
            "google.api_core.client_options",
            "google.auth.credentials",
        }

        def blocked_import(name, globals=None, locals=None, fromlist=(), level=0):
            if name in blocked:
                raise ModuleNotFoundError(name)
            return original_import(name, globals, locals, fromlist, level)

        builtins.__import__ = blocked_import
        try:
            import pytest_databases.docker.bigquery
        finally:
            builtins.__import__ = original_import
    """)

    result = pytester.runpytest_subprocess("-p", "pytest_databases", "-vv")
    result.assert_outcomes(passed=1)


def test_query_bigquery_emulator_unit(monkeypatch: pytest.MonkeyPatch) -> None:
    """Verify ``query_bigquery_emulator`` posts JSON payload and parses emulator response."""
    expected_payload = {"jobComplete": True, "rows": [{"f": [{"v": "1"}]}]}
    resp = MagicMock()
    resp.__enter__.return_value = SimpleNamespace(
        read=lambda: json.dumps(expected_payload).encode("utf-8"),
    )
    resp.__exit__.return_value = False

    monkeypatch.setattr(bigquery_mod.urllib.request, "urlopen", lambda _req, **_kwargs: resp)

    result = query_bigquery_emulator("127.0.0.1", 9050, "emulator-test-project", "SELECT 1 as one")
    assert result == expected_payload


def test_deprecated_bigquery_client_and_properties(monkeypatch: pytest.MonkeyPatch) -> None:
    """Verify deprecated ``BigQueryService`` properties and ``provide_bigquery_client`` emit warnings."""
    fake_creds = MagicMock()
    fake_options = MagicMock()
    fake_client = MagicMock()

    modules: dict[str, Any] = {
        "google.auth.credentials": SimpleNamespace(AnonymousCredentials=MagicMock(return_value=fake_creds)),
        "google.api_core.client_options": SimpleNamespace(ClientOptions=MagicMock(return_value=fake_options)),
        "google.cloud.bigquery": SimpleNamespace(Client=MagicMock(return_value=fake_client)),
    }
    monkeypatch.setattr(bigquery_mod.importlib, "import_module", lambda name: modules[name])

    service = BigQueryService(
        host="127.0.0.1",
        port=9050,
        container=MagicMock(),
        project="emulator-test-project",
        dataset="test-dataset",
    )
    assert service.endpoint == "http://127.0.0.1:9050"

    with pytest.deprecated_call(match="BigQueryService.credentials"):
        assert service.credentials is fake_creds

    with pytest.deprecated_call(match="BigQueryService.client_options"):
        assert service.client_options is fake_options

    with (
        pytest.deprecated_call(match="bigquery_client"),
        provide_bigquery_client(service) as client,
    ):
        assert client is fake_client


def test_provide_bigquery_service_isolation_modes(monkeypatch: pytest.MonkeyPatch) -> None:
    """Verify ``provide_bigquery_service`` isolates dataset per worker in database mode and container in server mode."""
    captured: list[tuple[str, bool]] = []
    ensured_datasets: list[str] = []

    class FakeDockerService:
        def run(self, **kwargs: Any) -> Any:
            captured.append((str(kwargs["name"]), bool(kwargs["transient"])))
            ctx = MagicMock()
            ctx.__enter__.return_value = ServiceContainer(host="127.0.0.1", port=9050, container=MagicMock())
            ctx.__exit__.return_value = False
            return ctx

    monkeypatch.setattr(bigquery_mod, "get_xdist_worker_num", lambda: 1)
    monkeypatch.setattr(
        bigquery_mod,
        "_ensure_bigquery_dataset",
        lambda _host, _port, _project, dataset: ensured_datasets.append(dataset),
    )

    fake_docker: Any = FakeDockerService()
    with provide_bigquery_service(
        fake_docker, "database", "ghcr.io/goccy/bigquery-emulator:latest", "linux/x86_64"
    ) as svc_db:
        assert svc_db.dataset == "test-dataset_1"
    with provide_bigquery_service(
        fake_docker, "server", "ghcr.io/goccy/bigquery-emulator:latest", "linux/x86_64"
    ) as svc_srv:
        assert svc_srv.dataset == "test-dataset"

    assert captured == [("bigquery", False), ("bigquery_1", True)]
    assert ensured_datasets == ["test-dataset_1"]


def test_service_fixture(pytester: pytest.Pytester) -> None:
    """Verify ``bigquery_service`` starts and answers REST queries."""
    pytester.makepyfile("""
    import json
    import urllib.request

    pytest_plugins = ["pytest_databases.docker.bigquery"]

    def run_bigquery(service, sql):
        body = json.dumps({"query": sql, "useLegacySql": False}).encode("utf-8")
        request = urllib.request.Request(
            f"{service.endpoint}/bigquery/v2/projects/{service.project}/queries",
            data=body,
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        with urllib.request.urlopen(request, timeout=10) as response:
            return json.loads(response.read().decode("utf-8"))

    def test(bigquery_service) -> None:
        payload = run_bigquery(bigquery_service, "SELECT 1 as one")
        assert payload.get("jobComplete") is True
        assert payload["rows"][0]["f"][0]["v"] == "1"
    """)

    result = pytester.runpytest_subprocess("-p", "pytest_databases")
    result.assert_outcomes(passed=1)


def test_xdist(pytester: pytest.Pytester) -> None:
    """Verify ``bigquery_service`` supports parallel ``pytest-xdist`` workers."""
    pytester.makepyfile("""
    import json
    import urllib.request

    pytest_plugins = ["pytest_databases.docker.bigquery"]

    def run_bigquery(service, sql):
        body = json.dumps({"query": sql, "useLegacySql": False}).encode("utf-8")
        request = urllib.request.Request(
            f"{service.endpoint}/bigquery/v2/projects/{service.project}/queries",
            data=body,
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        with urllib.request.urlopen(request, timeout=30) as response:
            return json.loads(response.read().decode("utf-8"))

    def test_one(bigquery_service) -> None:
        run_bigquery(
            bigquery_service,
            f"CREATE TABLE `{bigquery_service.dataset}.test_one` AS SELECT 1 AS the_value",
        )

    def test_two(bigquery_service) -> None:
        run_bigquery(
            bigquery_service,
            f"CREATE TABLE `{bigquery_service.dataset}.test_two` AS SELECT 1 AS the_value",
        )
    """)

    result = pytester.runpytest_subprocess("-p", "pytest_databases", "-n", "2")
    result.assert_outcomes(passed=2)
