from __future__ import annotations

from unittest.mock import MagicMock

from pytest_databases.docker import pubsub
from pytest_databases.docker.pubsub import PubSubService
from pytest_databases.types import ServiceContainer

PUBSUB_IMAGE = "gcr.io/google.com/cloudsdktool/google-cloud-cli:577.0.0-emulators"


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
