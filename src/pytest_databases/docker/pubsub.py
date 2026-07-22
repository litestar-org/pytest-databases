from __future__ import annotations

from dataclasses import dataclass

import pytest

from pytest_databases.helpers import get_xdist_worker_id
from pytest_databases.types import ServiceContainer, XdistIsolationLevel

PUBSUB_EMULATOR_IMAGE = "gcr.io/google.com/cloudsdktool/google-cloud-cli:577.0.0-emulators"


@dataclass
class PubSubService(ServiceContainer):
    project: str
    emulator_host: str


@pytest.fixture(scope="session")
def pubsub_image() -> str:
    return PUBSUB_EMULATOR_IMAGE


@pytest.fixture(scope="session")
def pubsub_project() -> str:
    worker_id = get_xdist_worker_id()
    if worker_id is None or worker_id == "master":
        return "pytest-databases"
    return f"pytest-databases-{worker_id}"


@pytest.fixture(scope="session")
def xdist_pubsub_isolation_level() -> XdistIsolationLevel:
    return "database"
