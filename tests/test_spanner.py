"""Tests for Cloud Spanner emulator container service fixtures."""

from __future__ import annotations

import io
import json
import logging
import os
import socket
import sys
import threading
import types
import urllib.error
from contextlib import contextmanager
from datetime import timedelta
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import TYPE_CHECKING, Any
from unittest.mock import MagicMock, patch

import pytest

from pytest_databases.docker.spanner import (
    _SPANNER_LOGGER_NAMES,
    SpannerService,
    _send_spanner_request_with_retry,
    bootstrap_spanner_emulator,
    configure_spanner_emulator_client_guards,
    provide_spanner_service,
    spanner_connection,
)
from pytest_databases.types import ServiceContainer
from tests.conftest import unwrap_fixture

if TYPE_CHECKING:
    from collections.abc import Generator

pytest_plugins = ["pytest_databases.docker.spanner"]


@contextmanager
def _spanner_loopback_server(
    statuses: list[int],
    recorded_urls: list[str] | None = None,
    recorded_payloads: list[dict[str, Any]] | None = None,
) -> Generator[int, None, None]:
    """Run a loopback HTTP server returning a deterministic sequence of status codes under poisoned proxies.

    Yields:
        Bound TCP port on 127.0.0.1.
    """
    remaining = list(statuses)
    port_holder = [0]

    class _Handler(BaseHTTPRequestHandler):
        def do_POST(self) -> None:
            length = int(self.headers.get("Content-Length", "0"))
            raw_body = self.rfile.read(length) if length > 0 else b"{}"
            if recorded_urls is not None:
                recorded_urls.append(f"http://127.0.0.1:{port_holder[0]}{self.path}")
            if recorded_payloads is not None:
                recorded_payloads.append(json.loads(raw_body.decode("utf-8")))
            status = remaining.pop(0) if len(remaining) > 1 else remaining[0]
            body = b"{}" if status < 400 else b'{"error": "spanner error"}'
            self.send_response(status)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def log_request(self, code: int | str = "-", size: int | str = "-") -> None:
            return

    saved_proxies = {
        var: os.environ.get(var)
        for var in ("HTTP_PROXY", "HTTPS_PROXY", "ALL_PROXY", "http_proxy", "https_proxy", "all_proxy")
    }
    for var in saved_proxies:
        os.environ[var] = "http://127.0.0.1:1"
    server = ThreadingHTTPServer(("127.0.0.1", 0), _Handler)
    port_holder[0] = server.server_port
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield port_holder[0]
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=2)
        for var, prev in saved_proxies.items():
            if prev is None:
                os.environ.pop(var, None)
            else:
                os.environ[var] = prev


def test_xdist_spanner_isolation_level_default(xdist_spanner_isolation_level: str) -> None:
    """Ensure xdist_spanner_isolation_level defaults to database."""
    assert xdist_spanner_isolation_level == "database"


def test_spanner_deprecated_connection_and_properties() -> None:
    """Verify spanner_connection, SpannerService.credentials, and SpannerService.client_options emit DeprecationWarning."""
    service = SpannerService(
        host="127.0.0.1",
        port=9010,
        container=MagicMock(),
        project="emulator-test-project",
        instance_name="emulator-test-instance",
        database_name="emulator-test-database",
        rest_port=9020,
    )
    mock_creds_mod = MagicMock()
    mock_options_mod = MagicMock()
    mock_spanner_mod = MagicMock()
    mock_client = MagicMock()
    mock_spanner_mod.Client.return_value = mock_client

    def fake_import(name: str) -> MagicMock:
        if name == "google.auth.credentials":
            return mock_creds_mod
        if name == "google.api_core.client_options":
            return mock_options_mod
        return mock_spanner_mod

    with patch("importlib.import_module", side_effect=fake_import):
        with pytest.warns(DeprecationWarning, match=r"SpannerService\.credentials") as credentials_record:
            assert service.credentials is mock_creds_mod.AnonymousCredentials.return_value
        with pytest.warns(DeprecationWarning, match=r"SpannerService\.client_options") as options_record:
            assert service.client_options is mock_options_mod.ClientOptions.return_value
        with pytest.warns(DeprecationWarning, match="spanner_connection") as connection_record:
            gen = unwrap_fixture(spanner_connection)(service)
            client = next(gen)
            assert client is mock_client
            with pytest.raises(StopIteration):
                next(gen)

    for record in (credentials_record, options_record, connection_record):
        assert len(record) == 1
        assert record[0].filename == __file__
    mock_options_mod.ClientOptions.assert_called_with(api_endpoint="127.0.0.1:9010")
    mock_client.close.assert_called_once_with()


def test_spanner_service_accepts_deprecated_credentials_argument() -> None:
    """Verify the v0.19.0 ``credentials=`` constructor argument warns once and is ignored."""
    with pytest.warns(DeprecationWarning, match="Passing 'credentials' to SpannerService") as record:
        service = SpannerService(
            container=MagicMock(),
            host="127.0.0.1",
            port=9010,
            project="p",
            database_name="d",
            instance_name="i",
            credentials=object(),
        )

    assert len(record) == 1
    assert record[0].filename == __file__
    assert "credentials" not in vars(service)
    assert service.endpoint == "127.0.0.1:9010"


def test_spanner_database_isolation_naming() -> None:
    """Ensure database isolation preserves shared container name and suffixes database."""
    mock_docker = MagicMock()
    mock_container = MagicMock()
    mock_service = ServiceContainer(container=mock_container, host="127.0.0.1", port=9010)
    mock_docker.run.return_value.__enter__.return_value = mock_service
    mock_docker.resolve_port.return_value = 39020

    with (
        patch("pytest_databases.docker.spanner.get_xdist_worker_num", return_value=1),
        patch("pytest_databases.docker.spanner.bootstrap_spanner_emulator") as mock_bootstrap,
        provide_spanner_service(
            docker_service=mock_docker,
            spanner_image="emulator:latest",
            spanner_project="test-proj",
            spanner_instance_name="test-inst",
            spanner_database_name="test-db",
            isolation_level="database",
        ) as service,
    ):
        assert service.database_name == "test-db_1"
        assert service.rest_port == 39020

    call_kwargs = mock_docker.run.call_args[1]
    assert call_kwargs["name"] == "spanner"
    assert call_kwargs["transient"] is False
    mock_bootstrap.assert_called_once_with(
        "127.0.0.1",
        39020,
        project="test-proj",
        instance_name="test-inst",
        database_name="test-db_1",
    )


def test_spanner_server_isolation_naming() -> None:
    """Ensure server isolation suffixes container name and retains database name."""
    mock_docker = MagicMock()
    mock_container = MagicMock()
    mock_service = ServiceContainer(container=mock_container, host="127.0.0.1", port=9010)
    mock_docker.run.return_value.__enter__.return_value = mock_service
    mock_docker.resolve_port.return_value = 39020

    with (
        patch("pytest_databases.docker.spanner.get_xdist_worker_num", return_value=1),
        patch("pytest_databases.docker.spanner.bootstrap_spanner_emulator"),
        provide_spanner_service(
            docker_service=mock_docker,
            spanner_image="emulator:latest",
            spanner_project="test-proj",
            spanner_instance_name="test-inst",
            spanner_database_name="test-db",
            isolation_level="server",
        ) as service,
    ):
        assert service.database_name == "test-db"

    call_kwargs = mock_docker.run.call_args[1]
    assert call_kwargs["name"] == "spanner_1"
    assert call_kwargs["transient"] is True


def test_bootstrap_spanner_emulator_rest_calls() -> None:
    """Ensure bootstrap_spanner_emulator sends REST POST requests."""
    recorded_urls: list[str] = []
    recorded_payloads: list[dict[str, Any]] = []

    with _spanner_loopback_server([200], recorded_urls=recorded_urls, recorded_payloads=recorded_payloads) as port:
        bootstrap_spanner_emulator(
            "127.0.0.1",
            port,
            project="test-proj",
            instance_name="test-inst",
            database_name="test-db",
        )

    assert len(recorded_urls) == 2
    assert recorded_urls[0] == f"http://127.0.0.1:{port}/v1/projects/test-proj/instances"
    assert recorded_payloads[0]["instanceId"] == "test-inst"
    assert recorded_urls[1] == f"http://127.0.0.1:{port}/v1/projects/test-proj/instances/test-inst/databases"
    assert recorded_payloads[1]["createStatement"] == "CREATE DATABASE `test-db`"


def test_bootstrap_spanner_emulator_handles_409() -> None:
    """Ensure bootstrap_spanner_emulator treats HTTP 409 conflict as success."""
    with _spanner_loopback_server([409]) as port:
        bootstrap_spanner_emulator(
            "127.0.0.1",
            port,
            project="test-proj",
            instance_name="test-inst",
            database_name="test-db",
        )


def test_bootstrap_spanner_emulator_raises_on_500() -> None:
    """Ensure bootstrap_spanner_emulator raises HTTPError on 500 error."""
    with _spanner_loopback_server([500]) as port, pytest.raises(urllib.error.HTTPError) as exc_info:
        bootstrap_spanner_emulator(
            "127.0.0.1",
            port,
            project="test-proj",
            instance_name="test-inst",
            database_name="test-db",
        )
    assert exc_info.value.code == 500


def test_send_spanner_request_with_retry_retries_503_then_succeeds(monkeypatch: pytest.MonkeyPatch) -> None:
    """Verify _send_spanner_request_with_retry retries transient 503 responses and succeeds on 200."""
    monkeypatch.setattr("pytest_databases.docker.spanner.time.sleep", lambda _: None)
    recorded_urls: list[str] = []
    with _spanner_loopback_server([503, 200], recorded_urls=recorded_urls) as port:
        _send_spanner_request_with_retry(
            f"http://127.0.0.1:{port}/v1/projects/p/instances",
            {"instanceId": "inst"},
            max_attempts=3,
        )
    assert len(recorded_urls) == 2


def test_plugin_imports_without_google_cloud_spanner(pytester: pytest.Pytester) -> None:
    """Verify spanner plugin imports cleanly without google-cloud-spanner installed."""
    pytester.makepyfile("""
    import builtins

    def test_import() -> None:
        original_import = builtins.__import__
        blocked = {"google.cloud.spanner", "google.api_core.client_options", "google.auth.credentials"}

        def blocked_import(name, globals=None, locals=None, fromlist=(), level=0):
            if name in blocked:
                raise ModuleNotFoundError(name)
            return original_import(name, globals, locals, fromlist, level)

        builtins.__import__ = blocked_import
        try:
            import pytest_databases.docker.spanner
        finally:
            builtins.__import__ = original_import
    """)

    result = pytester.runpytest_subprocess("-p", "pytest_databases", "-vv")
    result.assert_outcomes(passed=1)


def test_service_fixture(pytester: pytest.Pytester) -> None:
    """Verify spanner_service starts and provisions a database."""
    pytester.makepyfile("""
    from google.api_core.client_options import ClientOptions
    from google.auth.credentials import AnonymousCredentials
    from google.cloud import spanner

    pytest_plugins = ["pytest_databases.docker.spanner"]

    def test_spanner_service(spanner_service) -> None:
        assert spanner_service.endpoint == f"{spanner_service.host}:{spanner_service.port}"

        spanner_client = spanner.Client(
            project=spanner_service.project,
            credentials=AnonymousCredentials(),
            client_options=ClientOptions(api_endpoint=spanner_service.endpoint),
        )
        instance = spanner_client.instance(spanner_service.instance_name)
        database = instance.database(spanner_service.database_name)

        with database.snapshot() as snapshot:
            resp = next(iter(snapshot.execute_sql("SELECT 1")))
        assert resp[0] == 1
    """)

    result = pytester.runpytest_subprocess("-p", "pytest_databases", "-vv")
    result.assert_outcomes(passed=1)


def test_send_spanner_request_with_retry_urlerror_exhaustion(monkeypatch: pytest.MonkeyPatch) -> None:
    """Verify _send_spanner_request_with_retry retries URLError and raises after max attempts."""
    monkeypatch.setattr("pytest_databases.docker.spanner.time.sleep", lambda _: None)
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as probe:
        probe.bind(("127.0.0.1", 0))
        closed_port = probe.getsockname()[1]

    with pytest.raises(urllib.error.URLError):
        _send_spanner_request_with_retry(
            f"http://127.0.0.1:{closed_port}/v1/projects/p/instances",
            {"instanceId": "inst"},
            max_attempts=2,
        )


def test_spanner_service_emulator_host_property() -> None:
    """Verify SpannerService.emulator_host exposes host:port for SPANNER_EMULATOR_HOST."""
    service = SpannerService(
        host="127.0.0.1",
        port=9010,
        container=MagicMock(),
        project="test-proj",
        instance_name="test-inst",
        database_name="test-db",
    )
    assert service.emulator_host == "127.0.0.1:9010"


@pytest.mark.parametrize(
    ("preset_metrics", "expected_inside", "expected_after"),
    [
        (None, "true", None),
        ("false", "false", "false"),
    ],
)
def test_configure_spanner_emulator_client_guards_metrics_env(
    monkeypatch: pytest.MonkeyPatch,
    preset_metrics: str | None,
    expected_inside: str,
    expected_after: str | None,
) -> None:
    """Verify SPANNER_DISABLE_BUILTIN_METRICS defaults to true and restores prior environment state."""
    if preset_metrics is None:
        monkeypatch.delenv("SPANNER_DISABLE_BUILTIN_METRICS", raising=False)
    else:
        monkeypatch.setenv("SPANNER_DISABLE_BUILTIN_METRICS", preset_metrics)

    with configure_spanner_emulator_client_guards():
        assert os.environ.get("SPANNER_DISABLE_BUILTIN_METRICS") == expected_inside

    assert os.environ.get("SPANNER_DISABLE_BUILTIN_METRICS") == expected_after


def test_configure_spanner_emulator_client_guards_sessions_and_loggers(monkeypatch: pytest.MonkeyPatch) -> None:
    """Verify maintenance polling intervals, logger levels, and closed-stream ValueError handling restore on exit."""
    google_pkg = types.ModuleType("google")
    cloud_pkg = types.ModuleType("google.cloud")
    spanner_pkg = types.ModuleType("google.cloud.spanner_v1")
    async_pkg = types.ModuleType("google.cloud.spanner_v1._async")
    sync_mod = types.ModuleType("google.cloud.spanner_v1.database_sessions_manager")
    async_mod = types.ModuleType("google.cloud.spanner_v1._async.database_sessions_manager")
    original_sync_interval = timedelta(seconds=300)
    original_async_interval = timedelta(seconds=600)

    class _SyncManager:
        _MAINTENANCE_THREAD_POLLING_INTERVAL = original_sync_interval

    class _AsyncManager:
        _MAINTENANCE_THREAD_POLLING_INTERVAL = original_async_interval

    sync_mod.DatabaseSessionsManager = _SyncManager  # type: ignore[attr-defined]
    async_mod.DatabaseSessionsManager = _AsyncManager  # type: ignore[attr-defined]
    spanner_pkg.database_sessions_manager = sync_mod  # type: ignore[attr-defined]
    async_pkg.database_sessions_manager = async_mod  # type: ignore[attr-defined]
    spanner_pkg._async = async_pkg  # type: ignore[attr-defined]
    cloud_pkg.spanner_v1 = spanner_pkg  # type: ignore[attr-defined]
    google_pkg.cloud = cloud_pkg  # type: ignore[attr-defined]
    monkeypatch.setitem(sys.modules, google_pkg.__name__, google_pkg)
    monkeypatch.setitem(sys.modules, cloud_pkg.__name__, cloud_pkg)
    monkeypatch.setitem(sys.modules, spanner_pkg.__name__, spanner_pkg)
    monkeypatch.setitem(sys.modules, async_pkg.__name__, async_pkg)
    monkeypatch.setitem(sys.modules, sync_mod.__name__, sync_mod)
    monkeypatch.setitem(sys.modules, async_mod.__name__, async_mod)

    target_logger = logging.getLogger(_SPANNER_LOGGER_NAMES[0])
    error_logger = logging.getLogger(_SPANNER_LOGGER_NAMES[1])
    original_target_level = target_logger.level
    original_error_level = error_logger.level
    target_logger.setLevel(logging.INFO)
    error_logger.setLevel(logging.ERROR)

    closed_stream = io.StringIO()
    closed_stream.close()
    closed_handler = logging.StreamHandler(closed_stream)
    target_logger.addHandler(closed_handler)

    def _raise_closed(_record: logging.LogRecord) -> None:
        msg = "I/O operation on closed file."
        raise ValueError(msg)

    def _raise_other(_record: logging.LogRecord) -> None:
        msg = "unrelated value error"
        raise ValueError(msg)

    monkeypatch.setattr(error_logger, "callHandlers", _raise_closed)
    dummy_record = logging.LogRecord("x", logging.INFO, __file__, 1, "msg", (), None)

    try:
        with configure_spanner_emulator_client_guards():
            assert timedelta(milliseconds=100) == _SyncManager._MAINTENANCE_THREAD_POLLING_INTERVAL
            assert timedelta(milliseconds=100) == _AsyncManager._MAINTENANCE_THREAD_POLLING_INTERVAL
            assert target_logger.level == logging.WARNING
            assert error_logger.level == logging.ERROR

            target_logger.callHandlers(dummy_record)
            error_logger.callHandlers(dummy_record)

            target_logger.removeHandler(closed_handler)
            monkeypatch.setattr(target_logger, "callHandlers", _raise_other)
            with pytest.raises(ValueError, match="unrelated value error"):
                target_logger.callHandlers(dummy_record)

        assert original_sync_interval == _SyncManager._MAINTENANCE_THREAD_POLLING_INTERVAL
        assert original_async_interval == _AsyncManager._MAINTENANCE_THREAD_POLLING_INTERVAL
        assert target_logger.level == logging.INFO
        assert error_logger.level == logging.ERROR
    finally:
        target_logger.removeHandler(closed_handler)
        target_logger.setLevel(original_target_level)
        error_logger.setLevel(original_error_level)


def test_provide_spanner_service_activates_emulator_guards(monkeypatch: pytest.MonkeyPatch) -> None:
    """Verify provide_spanner_service enables emulator client guards around yield and restores on teardown."""
    monkeypatch.delenv("PYTEST_XDIST_WORKER", raising=False)
    monkeypatch.delenv("SPANNER_DISABLE_BUILTIN_METRICS", raising=False)
    monkeypatch.setattr("pytest_databases.docker.spanner.bootstrap_spanner_emulator", lambda *_a, **_kw: None)

    mock_docker = MagicMock()
    mock_docker.run.return_value.__enter__.return_value = ServiceContainer(
        host="127.0.0.1",
        port=9010,
        container=MagicMock(),
    )
    mock_docker.run.return_value.__exit__.return_value = False
    mock_docker.resolve_port.return_value = 9020

    with provide_spanner_service(
        mock_docker,
        spanner_image="gcr.io/cloud-spanner-emulator/emulator:latest",
        spanner_project="p",
        spanner_instance_name="i",
        spanner_database_name="d",
        isolation_level="database",
    ) as service:
        assert service.emulator_host == "127.0.0.1:9010"
        assert os.environ.get("SPANNER_DISABLE_BUILTIN_METRICS") == "true"

    assert "SPANNER_DISABLE_BUILTIN_METRICS" not in os.environ


def test_spanner_all_fixtures_inprocess(pytester: pytest.Pytester) -> None:
    """Verify all Spanner fixtures execute in-process with mocked docker_service."""
    pytester.makepyfile("""
    from contextlib import contextmanager
    import sys
    from unittest.mock import MagicMock
    import pytest
    from pytest_databases._service import DockerService
    from pytest_databases.types import ServiceContainer

    pytest_plugins = ["pytest_databases.docker.spanner"]

    @pytest.fixture(autouse=True, scope="session")
    def mock_spanner():
        import pytest_databases.docker.spanner as sp_mod
        orig = sp_mod.bootstrap_spanner_emulator
        sp_mod.bootstrap_spanner_emulator = lambda *a, **kw: None
        sys.modules["google"] = MagicMock()
        sys.modules["google.cloud"] = MagicMock()
        sys.modules["google.cloud.spanner"] = MagicMock()
        sys.modules["google.auth"] = MagicMock()
        sys.modules["google.auth.credentials"] = MagicMock()
        sys.modules["google.api_core"] = MagicMock()
        sys.modules["google.api_core.client_options"] = MagicMock()
        yield
        sp_mod.bootstrap_spanner_emulator = orig

    @pytest.fixture(scope="session")
    def docker_service():
        mock_ds = MagicMock(spec=DockerService)
        mock_ds.resolve_port.return_value = 9020
        @contextmanager
        def _run(image, **kwargs):
            yield ServiceContainer(host="127.0.0.1", port=9010, container=MagicMock())
        mock_ds.run.side_effect = _run
        return mock_ds

    def test_fixtures(
        docker_service,
        xdist_spanner_isolation_level,
        spanner_project,
        spanner_instance_name,
        spanner_database_name,
        spanner_image,
        spanner_service,
        spanner_connection,
    ):
        assert xdist_spanner_isolation_level == "database"
        assert spanner_project == "emulator-test-project"
        assert spanner_instance_name == "emulator-test-instance"
        assert spanner_database_name == "emulator-test-database"
        assert "cloud-spanner-emulator" in spanner_image
        assert spanner_service.port == 9010
        assert spanner_service.rest_port == 9020
        assert spanner_service.rest_endpoint == "127.0.0.1:9020"
        assert spanner_connection is not None
        docker_service.resolve_port.assert_called_once_with(spanner_service.container, 9020)
    """)
    result = pytester.runpytest("-p", "no:sugar", "-p", "pytest_databases", "-W", "ignore::DeprecationWarning")
    result.assert_outcomes(passed=1)
