"""Google Cloud Pub/Sub emulator fixtures and clientless readiness probes."""

from __future__ import annotations

import contextlib
import shlex
import urllib.error
import urllib.request
from dataclasses import dataclass
from typing import TYPE_CHECKING

import pytest

from pytest_databases.helpers import get_xdist_worker_id
from pytest_databases.types import ServiceContainer, XdistIsolationLevel

if TYPE_CHECKING:
    from collections.abc import Generator

    from pytest_databases._service import ContainerService

__all__ = [
    "PUBSUB_EMULATOR_IMAGE",
    "PUBSUB_EMULATOR_PORT",
    "PubSubService",
    "provide_pubsub_service",
    "pubsub_image",
    "pubsub_project",
    "pubsub_service",
    "xdist_pubsub_isolation_level",
]

PUBSUB_EMULATOR_IMAGE = "gcr.io/google.com/cloudsdktool/google-cloud-cli:577.0.0-emulators"
PUBSUB_EMULATOR_PORT = 8085


@dataclass
class PubSubService(ServiceContainer):
    """Metadata for a running Google Cloud Pub/Sub emulator container."""

    project: str
    emulator_host: str

    @property
    def endpoint(self) -> str:
        """The HTTP base endpoint URL for the Pub/Sub emulator."""
        return f"http://{self.host}:{self.port}"


@contextlib.contextmanager
def provide_pubsub_service(
    container_service: ContainerService,
    pubsub_image: str,
    pubsub_project: str,
    xdist_pubsub_isolation_level: XdistIsolationLevel,
) -> Generator[PubSubService, None, None]:
    """Start and validate a Google Cloud Pub/Sub emulator service container.

    Yields:
        A configured PubSubService instance.
    """
    worker_id = get_xdist_worker_id()
    container_name = "pubsub"
    if xdist_pubsub_isolation_level == "server" and worker_id not in {None, "master"}:
        container_name = f"{container_name}_{worker_id}"

    with container_service.run(
        image=pubsub_image,
        command=shlex.join(_pubsub_start_command(pubsub_project)),
        name=container_name,
        container_port=PUBSUB_EMULATOR_PORT,
        wait_for_log="Server started",
        check=lambda s: _is_pubsub_responsive(s, project=pubsub_project),
        timeout=60,
        transient=xdist_pubsub_isolation_level == "server",
    ) as service:
        yield PubSubService(
            container=service.container,
            host=service.host,
            port=service.port,
            project=pubsub_project,
            emulator_host=f"{service.host}:{service.port}",
        )


@pytest.fixture(scope="session")
def pubsub_image() -> str:
    """Provide the Google Cloud CLI emulators container image."""
    return PUBSUB_EMULATOR_IMAGE


@pytest.fixture(scope="session")
def pubsub_project() -> str:
    """Provide a worker-scoped Google Cloud project ID for Pub/Sub tests."""
    worker_id = get_xdist_worker_id()
    if worker_id is None or worker_id == "master":
        return "pytest-databases"
    return f"pytest-databases-{worker_id}"


@pytest.fixture(scope="session")
def xdist_pubsub_isolation_level() -> XdistIsolationLevel:
    """Provide the pytest-xdist isolation level for the Pub/Sub emulator."""
    return "database"


@pytest.fixture(scope="session")
def pubsub_service(
    container_service: ContainerService,
    pubsub_image: str,
    pubsub_project: str,
    xdist_pubsub_isolation_level: XdistIsolationLevel,
) -> Generator[PubSubService, None, None]:
    """Start and validate a Google Cloud Pub/Sub emulator service container.

    Yields:
        A configured PubSubService instance.
    """
    with provide_pubsub_service(
        container_service=container_service,
        pubsub_image=pubsub_image,
        pubsub_project=pubsub_project,
        xdist_pubsub_isolation_level=xdist_pubsub_isolation_level,
    ) as service:
        yield service


def _pubsub_start_command(project: str) -> list[str]:
    """Build the command-line argv to launch the Pub/Sub emulator.

    Returns:
        Command argument list.
    """
    return [
        "gcloud",
        "beta",
        "emulators",
        "pubsub",
        "start",
        f"--host-port=0.0.0.0:{PUBSUB_EMULATOR_PORT}",
        f"--project={project}",
    ]


def _is_pubsub_responsive(
    service: ServiceContainer,
    *,
    project: str = "pytest-databases",
    timeout: float = 2.0,
) -> bool:
    """Check whether the Pub/Sub emulator REST API is responding on ``/v1/projects/{project}/topics``.

    Returns:
        True when the REST endpoint responds with HTTP 200.
    """
    url = f"http://{service.host}:{service.port}/v1/projects/{project}/topics"
    try:
        with urllib.request.urlopen(url, timeout=timeout) as response:
            return bool(response.status == 200)
    except (OSError, urllib.error.URLError):
        return False
