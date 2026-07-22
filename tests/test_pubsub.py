from __future__ import annotations

from unittest.mock import MagicMock

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
