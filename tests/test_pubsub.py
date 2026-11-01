"""Tests for Google Cloud Pub/Sub emulator fixtures and clientless readiness probes."""

from __future__ import annotations

import json
from typing import Any
from unittest.mock import MagicMock

import pytest

from pytest_databases.docker import pubsub
from pytest_databases.docker.pubsub import PubSubService
from pytest_databases.types import ServiceContainer

PUBSUB_IMAGE = "gcr.io/google.com/cloudsdktool/google-cloud-cli:577.0.0-emulators"


def test_pubsub_service_metadata() -> None:
    """Verify PubSubService attributes and endpoint property."""
    service = PubSubService(
        container=MagicMock(),
        host="127.0.0.1",
        port=8085,
        project="pytest-databases",
        emulator_host="127.0.0.1:8085",
    )

    assert isinstance(service, ServiceContainer)
    assert service.project == "pytest-databases"
    assert service.emulator_host == f"{service.host}:{service.port}"
    assert service.endpoint == "http://127.0.0.1:8085"


def test_pubsub_contract_fixtures(pytester: pytest.Pytester, monkeypatch: pytest.MonkeyPatch) -> None:
    """Verify default values of pubsub_image, pubsub_project, and xdist_pubsub_isolation_level."""
    _clear_xdist_environment(monkeypatch)
    pytester.makepyfile(f"""
    pytest_plugins = ["pytest_databases.docker.pubsub"]

    def test_contract(pubsub_image, pubsub_project, xdist_pubsub_isolation_level) -> None:
        assert pubsub_image == {PUBSUB_IMAGE!r}
        assert pubsub_project == "pytest-databases"
        assert xdist_pubsub_isolation_level == "database"
    """)

    result = pytester.runpytest_subprocess("-p", "pytest_databases", "-vv")
    result.assert_outcomes(passed=1)


def test_pubsub_project_is_worker_scoped(pytester: pytest.Pytester, monkeypatch: pytest.MonkeyPatch) -> None:
    """Verify pubsub_project appends the pytest-xdist worker ID when active."""
    _clear_xdist_environment(monkeypatch)
    monkeypatch.setenv("PYTEST_XDIST_WORKER", "gw2")
    pytester.makepyfile("""
    pytest_plugins = ["pytest_databases.docker.pubsub"]

    def test_project(pubsub_project) -> None:
        assert pubsub_project == "pytest-databases-gw2"
    """)

    result = pytester.runpytest_subprocess("-p", "pytest_databases", "-vv")
    result.assert_outcomes(passed=1)


def test_pubsub_start_command() -> None:
    """Verify _pubsub_start_command builds the expected gcloud emulator command."""
    assert pubsub._pubsub_start_command("pytest-databases-gw2") == [
        "gcloud",
        "beta",
        "emulators",
        "pubsub",
        "start",
        "--host-port=0.0.0.0:8085",
        "--project=pytest-databases-gw2",
    ]


def test_pubsub_readiness_requires_http(mocker: Any) -> None:
    """Verify _is_pubsub_responsive probes the mapped REST /v1/projects/{project}/topics endpoint."""
    service = ServiceContainer(container=MagicMock(), host="127.0.0.1", port=8085)
    mock_response = MagicMock(status=200)
    mock_response.__enter__.return_value = mock_response
    mock_response.__exit__.return_value = False
    urlopen = mocker.patch.object(pubsub.urllib.request, "urlopen", return_value=mock_response)

    assert pubsub._is_pubsub_responsive(service, project="pytest-databases-gw2") is True
    urlopen.assert_called_once_with("http://127.0.0.1:8085/v1/projects/pytest-databases-gw2/topics", timeout=2.0)

    urlopen.side_effect = OSError
    assert pubsub._is_pubsub_responsive(service, project="pytest-databases-gw2") is False


def test_plugin_imports_without_google_cloud_pubsub(pytester: pytest.Pytester) -> None:
    """Ensure the Pub/Sub module imports cleanly when google-cloud-pubsub is absent."""
    pytester.makepyfile("""
    import builtins
    import importlib

    def test_import() -> None:
        original_import = builtins.__import__

        def blocked_import(name, globals=None, locals=None, fromlist=(), level=0):
            if name.startswith("google.cloud.pubsub"):
                raise ModuleNotFoundError(name)
            return original_import(name, globals, locals, fromlist, level)

        builtins.__import__ = blocked_import
        try:
            module = importlib.import_module("pytest_databases.docker.pubsub")
            assert module.PubSubService
        finally:
            builtins.__import__ = original_import
    """)

    result = pytester.runpytest_subprocess("-p", "pytest_databases", "-vv")
    result.assert_outcomes(passed=1)


def test_pubsub_service_fixture(pytester: pytest.Pytester, monkeypatch: pytest.MonkeyPatch) -> None:
    """Verify pubsub_service starts and yields a running PubSubService."""
    _clear_google_environment(monkeypatch)
    _clear_xdist_environment(monkeypatch)
    pytester.makepyfile("""
    pytest_plugins = ["pytest_databases.docker.pubsub"]

    def test_service(pubsub_service) -> None:
        assert pubsub_service.project == "pytest-databases"
        assert pubsub_service.emulator_host == f"{pubsub_service.host}:{pubsub_service.port}"
        assert pubsub_service.container.status == "running"
    """)

    result = pytester.runpytest_subprocess("-p", "pytest_databases", "-vv")
    result.assert_outcomes(passed=1)


@pytest.mark.parametrize(
    ("isolation_level", "expect_shared_container"),
    [("database", True), ("server", False)],
)
@pytest.mark.xdist_group(name="pubsub_nested_xdist")
def test_pubsub_xdist_isolation(
    pytester: pytest.Pytester,
    monkeypatch: pytest.MonkeyPatch,
    isolation_level: str,
    expect_shared_container: bool,
) -> None:
    """Verify database and server xdist isolation modes for pubsub_service."""
    _clear_google_environment(monkeypatch)
    _clear_xdist_environment(monkeypatch)
    monkeypatch.setenv("PUBSUB_RECORD_DIR", str(pytester.path))
    pytester.makepyfile(f"""
    import json
    import os
    from pathlib import Path

    import pytest

    pytest_plugins = ["pytest_databases.docker.pubsub"]

    @pytest.fixture(scope="session")
    def xdist_pubsub_isolation_level():
        return {isolation_level!r}

    @pytest.mark.parametrize("case", [0, 1])
    def test_isolation(pubsub_service, case) -> None:
        worker_id = os.environ["PYTEST_XDIST_WORKER"]
        assert pubsub_service.project == f"pytest-databases-{{worker_id}}"
        record = {{
            "container_id": pubsub_service.container.id,
            "project": pubsub_service.project,
        }}
        path = Path(os.environ["PUBSUB_RECORD_DIR"]) / f"pubsub-{{worker_id}}.json"
        path.write_text(json.dumps(record), encoding="utf-8")
    """)

    result = pytester.runpytest_subprocess("-p", "pytest_databases", "-n", "2", "--dist=load", "-vv")
    result.assert_outcomes(passed=2)
    records = [json.loads(path.read_text(encoding="utf-8")) for path in pytester.path.glob("pubsub-gw*.json")]
    assert len(records) == 2
    assert len({record["project"] for record in records}) == 2
    container_count = len({record["container_id"] for record in records})
    assert container_count == (1 if expect_shared_container else 2)


def _clear_google_environment(monkeypatch: pytest.MonkeyPatch) -> None:
    """Remove Google Cloud environment variables from the test environment."""
    for variable in (
        "CLOUDSDK_AUTH_CREDENTIAL_FILE_OVERRIDE",
        "GOOGLE_APPLICATION_CREDENTIALS",
        "GOOGLE_CLOUD_PROJECT",
        "PUBSUB_EMULATOR_HOST",
    ):
        monkeypatch.delenv(variable, raising=False)


def _clear_xdist_environment(monkeypatch: pytest.MonkeyPatch) -> None:
    """Remove pytest-xdist worker environment variables from the test environment."""
    for variable in ("PYTEST_XDIST_TESTRUNUID", "PYTEST_XDIST_WORKER", "PYTEST_XDIST_WORKER_COUNT"):
        monkeypatch.delenv(variable, raising=False)
