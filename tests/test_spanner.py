"""Tests for Cloud Spanner emulator container service fixtures."""

from __future__ import annotations

import email.message
import io
import json
import urllib.error
import urllib.request
from typing import Any
from unittest.mock import MagicMock, patch

import pytest

from pytest_databases.docker.spanner import (
    SpannerService,
    _send_spanner_request_with_retry,
    bootstrap_spanner_emulator,
    provide_spanner_service,
    spanner_connection,
)
from pytest_databases.types import ServiceContainer
from tests.conftest import unwrap_fixture

pytest_plugins = ["pytest_databases.docker.spanner"]


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

    def fake_urlopen(req: urllib.request.Request, timeout: int = 5) -> io.BytesIO:
        recorded_urls.append(req.full_url)
        assert req.data is not None
        raw_data = req.data if isinstance(req.data, bytes) else str(req.data).encode("utf-8")
        recorded_payloads.append(json.loads(raw_data.decode("utf-8")))
        return io.BytesIO(b"{}")

    with patch("urllib.request.urlopen", side_effect=fake_urlopen):
        bootstrap_spanner_emulator(
            "127.0.0.1",
            9020,
            project="test-proj",
            instance_name="test-inst",
            database_name="test-db",
        )

    assert len(recorded_urls) == 2
    assert recorded_urls[0] == "http://127.0.0.1:9020/v1/projects/test-proj/instances"
    assert recorded_payloads[0]["instanceId"] == "test-inst"
    assert recorded_urls[1] == "http://127.0.0.1:9020/v1/projects/test-proj/instances/test-inst/databases"
    assert recorded_payloads[1]["createStatement"] == "CREATE DATABASE `test-db`"


def test_bootstrap_spanner_emulator_handles_409() -> None:
    """Ensure bootstrap_spanner_emulator treats HTTP 409 conflict as success."""
    headers = email.message.Message()
    http_error = urllib.error.HTTPError("http://test", 409, "Conflict", headers, io.BytesIO(b"already exists"))

    with patch("urllib.request.urlopen", side_effect=http_error):
        bootstrap_spanner_emulator(
            "127.0.0.1",
            9020,
            project="test-proj",
            instance_name="test-inst",
            database_name="test-db",
        )


def test_bootstrap_spanner_emulator_raises_on_500() -> None:
    """Ensure bootstrap_spanner_emulator raises HTTPError on 500 error."""
    headers = email.message.Message()
    http_error = urllib.error.HTTPError(
        "http://test",
        500,
        "Internal Server Error",
        headers,
        io.BytesIO(b"internal error"),
    )

    with (
        patch("urllib.request.urlopen", side_effect=http_error),
        pytest.raises(urllib.error.HTTPError),
    ):
        bootstrap_spanner_emulator(
            "127.0.0.1",
            9020,
            project="test-proj",
            instance_name="test-inst",
            database_name="test-db",
        )


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
    monkeypatch.setattr(
        "pytest_databases.docker.spanner.urllib.request.urlopen",
        MagicMock(side_effect=urllib.error.URLError("connection refused")),
    )
    with pytest.raises(urllib.error.URLError, match="connection refused"):
        _send_spanner_request_with_retry(
            "http://127.0.0.1:9020/v1/projects/p/instances",
            {"instanceId": "inst"},
            max_attempts=2,
        )


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
