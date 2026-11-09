"""Tests for Google BigQuery emulator container service fixtures."""

from __future__ import annotations

import io
import json
import sys
import urllib.error
from contextlib import contextmanager
from types import SimpleNamespace
from typing import Any
from unittest.mock import MagicMock

import pytest

from pytest_databases.docker import bigquery as bigquery_mod
from pytest_databases.docker.bigquery import (
    BigQueryService,
    _ensure_bigquery_dataset,
    provide_bigquery_client,
    provide_bigquery_service,
    query_bigquery_emulator,
)
from pytest_databases.types import ServiceContainer
from tests.conftest import assert_legacy_platform_handling


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
        pytest.warns(DeprecationWarning, match=r"bigquery_client.*v1\.0\.0") as record,
        provide_bigquery_client(service) as client,
    ):
        assert client is fake_client
        fake_client.close.assert_not_called()

    assert len(record) == 1
    assert record[0].filename == __file__
    fake_client.close.assert_called_once_with()


def test_bigquery_service_deprecated_credentials_argument() -> None:
    """Verify the ignored ``credentials`` constructor argument warns once at the caller."""
    with pytest.warns(DeprecationWarning, match=r"credentials.*v1\.0\.0") as record:
        service = BigQueryService(
            host="127.0.0.1",
            port=9050,
            container=MagicMock(),
            project="emulator-test-project",
            dataset="test-dataset",
            credentials=object(),
        )

    assert len(record) == 1
    assert record[0].filename == __file__
    assert (service.project, service.dataset, service.endpoint) == (
        "emulator-test-project",
        "test-dataset",
        "http://127.0.0.1:9050",
    )


def test_bigquery_service_without_credentials_argument_does_not_warn(recwarn: pytest.WarningsRecorder) -> None:
    """Verify constructing ``BigQueryService`` without ``credentials`` emits no warning."""
    BigQueryService(
        host="127.0.0.1",
        port=9050,
        container=MagicMock(),
        project="emulator-test-project",
        dataset="test-dataset",
    )
    assert not [w for w in recwarn if issubclass(w.category, DeprecationWarning)]


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


@pytest.mark.parametrize("mode", ["default", "override", "legacy"])
def test_bigquery_platform_and_legacy_platform_fixture(pytester: pytest.Pytester, mode: str) -> None:
    """Verify bigquery_platform defaults to x86_64, honors a legacy platform override, and the bare shim warns once."""
    assert_legacy_platform_handling(
        pytester,
        "pytest_databases.docker.bigquery",
        "bigquery_platform",
        "linux/x86_64",
        mode,
    )


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


def test_bigquery_service_deprecated_properties_and_init_credentials(monkeypatch: pytest.MonkeyPatch) -> None:
    """Verify BigQueryService deprecated credentials arg and properties emit DeprecationWarning."""
    with pytest.deprecated_call(match="Passing 'credentials' to BigQueryService"):
        svc = BigQueryService(
            host="127.0.0.1",
            port=9050,
            container=MagicMock(),
            project="test-proj",
            dataset="test_ds",
            credentials="legacy-creds",
        )
    assert svc.endpoint == "http://127.0.0.1:9050"

    fake_creds = MagicMock()
    fake_opts = MagicMock()
    monkeypatch.setitem(sys.modules, "google.auth.credentials", SimpleNamespace(AnonymousCredentials=fake_creds))
    monkeypatch.setitem(sys.modules, "google.api_core.client_options", SimpleNamespace(ClientOptions=fake_opts))

    with pytest.deprecated_call(match=r"BigQueryService\.credentials"):
        _ = svc.credentials
    fake_creds.assert_called_once_with()

    with pytest.deprecated_call(match=r"BigQueryService\.client_options"):
        _ = svc.client_options
    fake_opts.assert_called_once_with(api_endpoint="http://127.0.0.1:9050")


@pytest.mark.parametrize(
    ("status_code", "should_raise"),
    [
        (200, False),
        (409, False),
        (500, True),
    ],
)
def test_ensure_bigquery_dataset_status_codes(
    monkeypatch: pytest.MonkeyPatch,
    status_code: int,
    should_raise: bool,
) -> None:
    """Verify _ensure_bigquery_dataset handles 200, 409 Conflict, and re-raises other HTTPError codes."""

    def fake_urlopen(req: Any, timeout: float = 5.0) -> Any:
        if status_code == 200:
            cm = MagicMock()
            cm.__enter__.return_value = MagicMock(status=200)
            return cm
        raise urllib.error.HTTPError(req.full_url, status_code, "Error", MagicMock(), io.BytesIO(b""))

    monkeypatch.setattr("pytest_databases.docker.bigquery.urllib.request.urlopen", fake_urlopen)
    if should_raise:
        with pytest.raises(urllib.error.HTTPError):
            _ensure_bigquery_dataset("127.0.0.1", 9050, "proj", "ds")
    else:
        _ensure_bigquery_dataset("127.0.0.1", 9050, "proj", "ds")


@pytest.mark.parametrize(
    ("isolation_level", "worker_num", "expected_dataset", "expected_name"),
    [
        ("database", None, "test-dataset", "bigquery"),
        ("database", 2, "test-dataset_2", "bigquery"),
        ("server", 2, "test-dataset", "bigquery_2"),
    ],
)
def test_query_bigquery_emulator_and_provide_bigquery_service_check_branches(
    monkeypatch: pytest.MonkeyPatch,
    isolation_level: str,
    worker_num: int | None,
    expected_dataset: str,
    expected_name: str,
) -> None:
    """Verify query_bigquery_emulator and provide_bigquery_service readiness check branches."""
    responses: list[Any] = [
        urllib.error.URLError("down"),
        {"jobComplete": False},
        {"jobComplete": True, "rows": []},
        {"jobComplete": True, "rows": [{"f": [{"v": "1"}]}]},
    ]

    def fake_urlopen(req: Any, timeout: float = 5.0) -> Any:
        item = responses.pop(0)
        if isinstance(item, Exception):
            raise item
        cm = MagicMock()
        cm.__enter__.return_value.read.return_value = json.dumps(item).encode("utf-8")
        return cm

    monkeypatch.setattr("pytest_databases.docker.bigquery.urllib.request.urlopen", fake_urlopen)
    monkeypatch.setattr("pytest_databases.docker.bigquery._ensure_bigquery_dataset", lambda *_a, **_kw: None)
    monkeypatch.setattr("pytest_databases.docker.bigquery.get_xdist_worker_num", lambda: worker_num)

    docker_service = MagicMock()
    captured_name: list[str] = []

    def fake_run(image: str, **kwargs: Any) -> Any:
        @contextmanager
        def _ctx() -> Any:
            captured_name.append(kwargs["name"])
            svc = ServiceContainer(host="127.0.0.1", port=9050, container=MagicMock())
            check = kwargs["check"]
            assert check(svc) is False
            assert check(svc) is False
            assert check(svc) is False
            assert check(svc) is True
            yield svc

        return _ctx()

    docker_service.run.side_effect = fake_run

    with provide_bigquery_service(
        docker_service=docker_service,
        image="ghcr.io/goccy/bigquery-emulator:0.6.6",
        platform_arch="linux/x86_64",
        isolation_level=isolation_level,  # type: ignore[arg-type]
    ) as service:
        assert service.dataset == expected_dataset
        assert captured_name == [expected_name]


def test_bigquery_all_fixtures_inprocess(pytester: pytest.Pytester) -> None:
    """Verify all BigQuery fixtures execute in-process with mocked docker_service."""
    pytester.makepyfile("""
    from contextlib import contextmanager
    import sys
    from unittest.mock import MagicMock
    import pytest
    from pytest_databases.types import ServiceContainer

    pytest_plugins = ["pytest_databases.docker.bigquery"]

    @pytest.fixture(autouse=True, scope="session")
    def mock_bq():
        import pytest_databases.docker.bigquery as bq_mod
        orig = bq_mod._ensure_bigquery_dataset
        bq_mod._ensure_bigquery_dataset = lambda *a, **kw: None
        sys.modules["google"] = MagicMock()
        sys.modules["google.cloud"] = MagicMock()
        sys.modules["google.cloud.bigquery"] = MagicMock()
        sys.modules["google.auth"] = MagicMock()
        sys.modules["google.auth.credentials"] = MagicMock()
        sys.modules["google.api_core"] = MagicMock()
        sys.modules["google.api_core.client_options"] = MagicMock()
        yield
        bq_mod._ensure_bigquery_dataset = orig

    @pytest.fixture(scope="session")
    def docker_service():
        mock_ds = MagicMock()
        @contextmanager
        def _run(image, **kwargs):
            yield ServiceContainer(host="127.0.0.1", port=9050, container=MagicMock())
        mock_ds.run.side_effect = _run
        return mock_ds

    def test_fixtures(
        xdist_bigquery_isolation_level,
        bigquery_image,
        bigquery_platform,
        bigquery_service,
        bigquery_client,
    ):
        assert xdist_bigquery_isolation_level == "database"
        assert "bigquery-emulator" in bigquery_image
        assert bigquery_platform == "linux/x86_64"
        assert bigquery_service.port == 9050
        assert bigquery_client is not None
    """)
    result = pytester.runpytest("-p", "no:sugar", "-p", "pytest_databases", "-W", "ignore::DeprecationWarning")
    result.assert_outcomes(passed=1)
