from __future__ import annotations

import io
import json
import urllib.error
import urllib.request
from unittest.mock import MagicMock, patch

import pytest

from pytest_databases.docker.spanner import (
    bootstrap_spanner_emulator,
    spanner_service,
)
from pytest_databases.types import ServiceContainer

pytest_plugins = ["pytest_databases.docker.spanner"]


def test_xdist_spanner_isolation_level_default(xdist_spanner_isolation_level: str) -> None:
    """Ensure xdist_spanner_isolation_level defaults to database."""
    assert xdist_spanner_isolation_level == "database"


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
    ):
        spanner_fixture = spanner_service.__wrapped__
        generator = spanner_fixture(
            docker_service=mock_docker,
            xdist_spanner_isolation_level="database",
            spanner_image="emulator:latest",
            spanner_project="test-proj",
            spanner_instance_name="test-inst",
            spanner_database_name="test-db",
        )
        service = next(generator)
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
    ):
        spanner_fixture = spanner_service.__wrapped__
        generator = spanner_fixture(
            docker_service=mock_docker,
            xdist_spanner_isolation_level="server",
            spanner_image="emulator:latest",
            spanner_project="test-proj",
            spanner_instance_name="test-inst",
            spanner_database_name="test-db",
        )
        service = next(generator)
        assert service.database_name == "test-db"

    call_kwargs = mock_docker.run.call_args[1]
    assert call_kwargs["name"] == "spanner_1"
    assert call_kwargs["transient"] is True


def test_bootstrap_spanner_emulator_rest_calls() -> None:
    """Ensure bootstrap_spanner_emulator sends REST POST requests."""
    recorded_urls: list[str] = []
    recorded_payloads: list[dict] = []

    def fake_urlopen(req: urllib.request.Request, timeout: int = 5) -> io.BytesIO:
        recorded_urls.append(req.full_url)
        assert req.data is not None
        raw_data = req.data if isinstance(req.data, bytes) else bytes(req.data)  # type: ignore[arg-type]
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
    http_error = urllib.error.HTTPError("http://test", 409, "Conflict", hdrs=None, fp=io.BytesIO(b"already exists"))  # type: ignore[arg-type]

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
    http_error = urllib.error.HTTPError("http://test", 500, "Internal Server Error", hdrs=None, fp=io.BytesIO(b"internal error"))  # type: ignore[arg-type]

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
