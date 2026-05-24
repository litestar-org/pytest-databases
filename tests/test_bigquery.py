from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    import pytest


def test_plugin_imports_without_google_cloud_bigquery(pytester: pytest.Pytester) -> None:
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


def test_service_fixture(pytester: pytest.Pytester) -> None:
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
