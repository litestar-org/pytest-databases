"""Tests for Google Cloud Spanner emulator container fixtures and HTTP REST provisioning."""

from __future__ import annotations

import email.message
import io
import json
import urllib.error
import urllib.request
from unittest.mock import MagicMock, patch

import pytest

from pytest_databases.docker.spanner import (
    bootstrap_spanner_emulator,
    provide_spanner_service,
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
    recorded_payloads: list[dict] = []

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
        "http://test", 500, "Internal Server Error", headers, io.BytesIO(b"internal error")
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
    import json
    import urllib.request

    pytest_plugins = ["pytest_databases.docker.spanner"]

    def test_spanner_service(spanner_service) -> None:
        assert spanner_service.endpoint == f"{spanner_service.host}:{spanner_service.port}"
        assert spanner_service.rest_endpoint == f"{spanner_service.host}:{spanner_service.rest_port}"

        db_url = (
            f"http://{spanner_service.rest_endpoint}/v1/projects/{spanner_service.project}"
            f"/instances/{spanner_service.instance_name}/databases/{spanner_service.database_name}"
        )
        with urllib.request.urlopen(db_url, timeout=5) as response:
            payload = json.loads(response.read().decode("utf-8"))
        assert payload["name"].endswith(f"/databases/{spanner_service.database_name}")
    """)

    result = pytester.runpytest_subprocess("-p", "pytest_databases", "-vv")
    result.assert_outcomes(passed=1)
