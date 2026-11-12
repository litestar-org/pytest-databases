"""Tests for Google BigQuery emulator container service fixtures."""

from __future__ import annotations

import json
import os
import socket
import sys
import threading
import urllib.error
from contextlib import contextmanager
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from types import SimpleNamespace
from typing import TYPE_CHECKING, Any
from unittest.mock import MagicMock

import pytest

from pytest_databases.docker import bigquery as bigquery_mod
from pytest_databases.docker.bigquery import (
    DEFAULT_BIGQUERY_IMAGE,
    BigQueryService,
    _ensure_bigquery_dataset,
    provide_bigquery_client,
    provide_bigquery_service,
    query_bigquery_emulator,
)
from pytest_databases.types import ServiceContainer
from tests.conftest import assert_legacy_platform_handling

if TYPE_CHECKING:
    from collections.abc import Generator


@contextmanager
def _bigquery_loopback_server(
    handler_fn: Any,
) -> Generator[int, None, None]:
    """Run a loopback HTTP server dispatching POST requests to handler_fn under poisoned proxy env vars.

    Yields:
        Bound TCP port on 127.0.0.1.
    """

    class _Handler(BaseHTTPRequestHandler):
        def do_POST(self) -> None:
            length = int(self.headers.get("Content-Length", "0"))
            raw_body = self.rfile.read(length) if length > 0 else b"{}"
            status, payload = handler_fn(self.path, json.loads(raw_body.decode("utf-8")))
            encoded = json.dumps(payload).encode("utf-8")
            self.send_response(status)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(encoded)))
            self.end_headers()
            self.wfile.write(encoded)

        def log_request(self, code: int | str = "-", size: int | str = "-") -> None:
            return

    saved_proxies = {
        var: os.environ.get(var)
        for var in ("HTTP_PROXY", "HTTPS_PROXY", "ALL_PROXY", "http_proxy", "https_proxy", "all_proxy")
    }
    for var in saved_proxies:
        os.environ[var] = "http://127.0.0.1:1"
    server = ThreadingHTTPServer(("127.0.0.1", 0), _Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield server.server_address[1]
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=2)
        for var, prev in saved_proxies.items():
            if prev is None:
                os.environ.pop(var, None)
            else:
                os.environ[var] = prev


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


def test_query_bigquery_emulator_unit() -> None:
    """Verify ``query_bigquery_emulator`` posts JSON payload and parses emulator response."""
    expected_payload = {"jobComplete": True, "rows": [{"f": [{"v": "1"}]}]}
    captured: list[tuple[str, dict[str, Any]]] = []

    def handle_post(path: str, body: dict[str, Any]) -> tuple[int, dict[str, Any]]:
        captured.append((path, body))
        return 200, expected_payload

    with _bigquery_loopback_server(handle_post) as port:
        result = query_bigquery_emulator("127.0.0.1", port, "emulator-test-project", "SELECT 1 as one")

    assert result == expected_payload
    assert captured == [
        (
            "/bigquery/v2/projects/emulator-test-project/queries",
            {"query": "SELECT 1 as one", "useLegacySql": False},
        )
    ]


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

    monkeypatch.setattr(
        bigquery_mod,
        "_ensure_bigquery_dataset",
        lambda _host, _port, _project, dataset: ensured_datasets.append(dataset),
    )

    fake_docker: Any = FakeDockerService()
    monkeypatch.setattr(bigquery_mod, "get_xdist_worker_num", lambda: None)
    with provide_bigquery_service(fake_docker, "server", DEFAULT_BIGQUERY_IMAGE, "linux/x86_64") as svc_master:
        assert svc_master.dataset == "test-dataset"

    monkeypatch.setattr(bigquery_mod, "get_xdist_worker_num", lambda: 1)
    with provide_bigquery_service(fake_docker, "database", DEFAULT_BIGQUERY_IMAGE, "linux/x86_64") as svc_db:
        assert svc_db.dataset == "test-dataset_1"
    with provide_bigquery_service(fake_docker, "server", DEFAULT_BIGQUERY_IMAGE, "linux/x86_64") as svc_srv:
        assert svc_srv.dataset == "test-dataset"

    assert captured == [("bigquery", False), ("bigquery", False), ("bigquery_1", True)]
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
    from pytest_databases.docker.bigquery import query_bigquery_emulator

    pytest_plugins = ["pytest_databases.docker.bigquery"]

    def test(bigquery_service) -> None:
        assert bigquery_service.is_healthy() is True
        payload = query_bigquery_emulator(
            bigquery_service.host, bigquery_service.port, bigquery_service.project, "SELECT 1 as one"
        )
        assert payload.get("jobComplete") is True
        assert payload["rows"][0]["f"][0]["v"] == "1"
    """)

    result = pytester.runpytest_subprocess("-p", "pytest_databases")
    result.assert_outcomes(passed=1)


def test_xdist(pytester: pytest.Pytester) -> None:
    """Verify ``bigquery_service`` supports parallel ``pytest-xdist`` workers."""
    pytester.makepyfile("""
    from pytest_databases.docker.bigquery import query_bigquery_emulator

    pytest_plugins = ["pytest_databases.docker.bigquery"]

    def test_one(bigquery_service) -> None:
        query_bigquery_emulator(
            bigquery_service.host,
            bigquery_service.port,
            bigquery_service.project,
            f"CREATE TABLE `{bigquery_service.dataset}.test_one` AS SELECT 1 AS the_value",
        )

    def test_two(bigquery_service) -> None:
        query_bigquery_emulator(
            bigquery_service.host,
            bigquery_service.port,
            bigquery_service.project,
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
    status_code: int,
    should_raise: bool,
) -> None:
    """Verify _ensure_bigquery_dataset handles 200, 409 Conflict, and re-raises other HTTPError codes."""

    def handle_post(_path: str, _body: dict[str, Any]) -> tuple[int, dict[str, Any]]:
        return status_code, {}

    with _bigquery_loopback_server(handle_post) as port:
        if should_raise:
            with pytest.raises(urllib.error.HTTPError) as exc_info:
                _ensure_bigquery_dataset("127.0.0.1", port, "proj", "ds")
            assert exc_info.value.code == 500
        else:
            _ensure_bigquery_dataset("127.0.0.1", port, "proj", "ds")


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
    responses: list[dict[str, Any]] = [
        {"jobComplete": False},
        {"jobComplete": True, "rows": []},
        {"jobComplete": True, "rows": [{"f": [{"v": "1"}]}]},
    ]

    def handle_post(_path: str, _body: dict[str, Any]) -> tuple[int, dict[str, Any]]:
        return 200, responses.pop(0)

    monkeypatch.setattr("pytest_databases.docker.bigquery._ensure_bigquery_dataset", lambda *_a, **_kw: None)
    monkeypatch.setattr("pytest_databases.docker.bigquery.get_xdist_worker_num", lambda: worker_num)

    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as probe:
        probe.bind(("127.0.0.1", 0))
        closed_port = probe.getsockname()[1]

    docker_service = MagicMock()
    captured_name: list[str] = []

    with _bigquery_loopback_server(handle_post) as port:

        def fake_run(image: str, **kwargs: Any) -> Any:
            @contextmanager
            def _ctx() -> Any:
                captured_name.append(kwargs["name"])
                svc = ServiceContainer(host="127.0.0.1", port=port, container=MagicMock())
                down_svc = ServiceContainer(host="127.0.0.1", port=closed_port, container=MagicMock())
                check = kwargs["check"]
                assert check(down_svc) is False
                assert check(svc) is False
                assert check(svc) is False
                assert check(svc) is True
                yield svc

            return _ctx()

        docker_service.run.side_effect = fake_run

        with provide_bigquery_service(
            docker_service=docker_service,
            image=DEFAULT_BIGQUERY_IMAGE,
            platform_arch="linux/x86_64",
            isolation_level=isolation_level,  # type: ignore[arg-type]
        ) as service:
            assert service.dataset == expected_dataset
            assert captured_name == [expected_name]


@pytest.mark.parametrize(
    ("status_code", "payload", "expected"),
    [
        (200, {"jobComplete": True, "rows": [{"f": [{"v": "1"}]}]}, True),
        (200, {"jobComplete": True, "rows": []}, False),
        (200, {"jobComplete": False}, False),
        (500, {"error": "boom"}, False),
    ],
)
def test_bigquery_service_is_healthy_http_responses(
    status_code: int,
    payload: dict[str, Any],
    expected: bool,
) -> None:
    """Verify BigQueryService.is_healthy evaluates emulator SELECT 1 readiness responses."""

    def handle_post(_path: str, _body: dict[str, Any]) -> tuple[int, dict[str, Any]]:
        return status_code, payload

    with _bigquery_loopback_server(handle_post) as port:
        service = BigQueryService(
            host="127.0.0.1",
            port=port,
            container=MagicMock(),
            project="test-proj",
            dataset="test-dataset",
        )
        assert service.is_healthy(timeout=1.0) is expected


def test_bigquery_service_is_healthy_unreachable() -> None:
    """Verify BigQueryService.is_healthy returns False when emulator TCP port is closed."""
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as probe:
        probe.bind(("127.0.0.1", 0))
        closed_port = probe.getsockname()[1]

    service = BigQueryService(
        host="127.0.0.1",
        port=closed_port,
        container=MagicMock(),
        project="test-proj",
        dataset="test-dataset",
    )
    assert service.is_healthy(timeout=1.0) is False


def test_bigquery_image_and_isolation_defaults(pytester: pytest.Pytester, monkeypatch: pytest.MonkeyPatch) -> None:
    """Verify bigquery_image pins 0.8.1 by default, honors BIGQUERY_IMAGE, and defaults xdist to server."""
    monkeypatch.delenv("BIGQUERY_IMAGE", raising=False)
    pytester.makepyfile(f"""
    pytest_plugins = ["pytest_databases.docker.bigquery"]

    def test_defaults(bigquery_image, xdist_bigquery_isolation_level) -> None:
        assert bigquery_image == {DEFAULT_BIGQUERY_IMAGE!r}
        assert xdist_bigquery_isolation_level == "server"
    """)
    pytester.runpytest("-p", "no:sugar", "-p", "pytest_databases").assert_outcomes(passed=1)

    monkeypatch.setenv("BIGQUERY_IMAGE", "ghcr.io/goccy/bigquery-emulator:0.9.0")
    pytester.makepyfile("""
    pytest_plugins = ["pytest_databases.docker.bigquery"]

    def test_override(bigquery_image) -> None:
        assert bigquery_image == "ghcr.io/goccy/bigquery-emulator:0.9.0"
    """)
    pytester.runpytest("-p", "no:sugar", "-p", "pytest_databases").assert_outcomes(passed=1)


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
        assert xdist_bigquery_isolation_level == "server"
        assert ":0.8.1" in bigquery_image
        assert bigquery_platform == "linux/x86_64"
        assert bigquery_service.port == 9050
        assert bigquery_client is not None
    """)
    result = pytester.runpytest("-p", "no:sugar", "-p", "pytest_databases", "-W", "ignore::DeprecationWarning")
    result.assert_outcomes(passed=1)
