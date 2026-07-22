from __future__ import annotations

import json
from unittest.mock import MagicMock

import pytest

from pytest_databases.docker import pubsub
from pytest_databases.docker.pubsub import PubSubService
from pytest_databases.types import ServiceContainer

PUBSUB_IMAGE = "gcr.io/google.com/cloudsdktool/google-cloud-cli:577.0.0-emulators"


def _clear_google_environment(monkeypatch: pytest.MonkeyPatch) -> None:
    for variable in (
        "CLOUDSDK_AUTH_CREDENTIAL_FILE_OVERRIDE",
        "GOOGLE_APPLICATION_CREDENTIALS",
        "GOOGLE_CLOUD_PROJECT",
        "PUBSUB_EMULATOR_HOST",
    ):
        monkeypatch.delenv(variable, raising=False)


def test_pubsub_service_metadata() -> None:
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


def test_pubsub_contract_fixtures(pytester) -> None:
    pytester.makepyfile(f"""
    pytest_plugins = ["pytest_databases.docker.pubsub"]

    def test_contract(pubsub_image, pubsub_project, xdist_pubsub_isolation_level) -> None:
        assert pubsub_image == {PUBSUB_IMAGE!r}
        assert pubsub_project == "pytest-databases"
        assert xdist_pubsub_isolation_level == "database"
    """)

    result = pytester.runpytest_subprocess("-p", "pytest_databases", "-vv")
    result.assert_outcomes(passed=1)


def test_pubsub_project_is_worker_scoped(pytester, monkeypatch) -> None:
    monkeypatch.setenv("PYTEST_XDIST_WORKER", "gw2")
    pytester.makepyfile("""
    pytest_plugins = ["pytest_databases.docker.pubsub"]

    def test_project(pubsub_project) -> None:
        assert pubsub_project == "pytest-databases-gw2"
    """)

    result = pytester.runpytest_subprocess("-p", "pytest_databases", "-vv")
    result.assert_outcomes(passed=1)


def test_pubsub_start_command() -> None:
    assert pubsub._pubsub_start_command("pytest-databases-gw2") == [
        "gcloud",
        "beta",
        "emulators",
        "pubsub",
        "start",
        "--host-port=0.0.0.0:8085",
        "--project=pytest-databases-gw2",
    ]


def test_pubsub_readiness_requires_tcp(mocker) -> None:
    service = ServiceContainer(container=MagicMock(), host="127.0.0.1", port=8085)
    connection = MagicMock()
    create_connection = mocker.patch.object(pubsub.socket, "create_connection", return_value=connection)

    assert pubsub._is_pubsub_responsive(service) is True
    create_connection.assert_called_once_with(("127.0.0.1", 8085), timeout=1)
    connection.close.assert_called_once_with()

    create_connection.side_effect = OSError("not listening")
    assert pubsub._is_pubsub_responsive(service) is False


def test_pubsub_smoke_uses_ephemeral_gcloud_sidecar() -> None:
    container_service = MagicMock()
    emulator_container = MagicMock(id="pubsub-container")

    pubsub._smoke_pubsub_emulator(
        container_service,
        emulator_container,
        image=PUBSUB_IMAGE,
        project="pytest-databases-gw2",
    )

    args, kwargs = container_service.run_container.call_args
    assert args[0] == PUBSUB_IMAGE
    assert args[1][:2] == ["bash", "-c"]
    assert "gcloud pubsub topics create" in args[1][2]
    assert "gcloud pubsub subscriptions create" in args[1][2]
    assert "gcloud pubsub topics publish" in args[1][2]
    assert "gcloud pubsub subscriptions pull" in args[1][2]
    assert kwargs == {
        "service_name": "pubsub-smoke",
        "environment": {
            "CLOUDSDK_API_ENDPOINT_OVERRIDES_PUBSUB": "http://localhost:8085/",
            "CLOUDSDK_AUTH_DISABLE_CREDENTIALS": "true",
            "CLOUDSDK_CORE_PROJECT": "pytest-databases-gw2",
        },
        "network_mode": "container:pubsub-container",
        "remove": True,
    }


def test_plugin_imports_without_google_cloud_pubsub(pytester: pytest.Pytester) -> None:
    pytester.makepyfile("""
    import builtins

    def test_import() -> None:
        original_import = builtins.__import__

        def blocked_import(name, globals=None, locals=None, fromlist=(), level=0):
            if name.startswith("google.cloud.pubsub"):
                raise ModuleNotFoundError(name)
            return original_import(name, globals, locals, fromlist, level)

        builtins.__import__ = blocked_import
        try:
            import pytest_databases.docker.pubsub
        finally:
            builtins.__import__ = original_import
    """)

    result = pytester.runpytest_subprocess("-p", "pytest_databases", "-vv")
    result.assert_outcomes(passed=1)


def test_pubsub_service_fixture(pytester: pytest.Pytester, monkeypatch: pytest.MonkeyPatch) -> None:
    _clear_google_environment(monkeypatch)
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
def test_pubsub_xdist_isolation(
    pytester: pytest.Pytester,
    monkeypatch: pytest.MonkeyPatch,
    isolation_level: str,
    expect_shared_container: bool,
) -> None:
    _clear_google_environment(monkeypatch)
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
