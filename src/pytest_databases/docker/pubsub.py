"""Google Cloud Pub/Sub emulator fixtures and clientless readiness probes."""

from __future__ import annotations

import contextlib
import shlex
import socket
from dataclasses import dataclass
from typing import TYPE_CHECKING

import pytest

from pytest_databases.helpers import exec_output_to_bytes, get_xdist_worker_id
from pytest_databases.types import ServiceContainer, XdistIsolationLevel

if TYPE_CHECKING:
    from collections.abc import Generator

    from docker.models.containers import Container

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

_PUBSUB_SMOKE_SCRIPT = """\
set -eu
topic="pytest-databases-smoke"
subscription="pytest-databases-smoke"
cleanup() {
    gcloud pubsub subscriptions delete "$subscription" --quiet >/dev/null 2>&1 || true
    gcloud pubsub topics delete "$topic" --quiet >/dev/null 2>&1 || true
}
trap cleanup EXIT
cleanup
gcloud pubsub topics create "$topic" --quiet
gcloud pubsub subscriptions create "$subscription" --topic="$topic" --quiet
gcloud pubsub topics publish "$topic" --message=pytest-databases --quiet
payload="$(timeout 30 gcloud pubsub subscriptions pull "$subscription" --auto-ack --limit=1 --format='value(message.data)' --quiet)"
test "$payload" = "pytest-databases"
"""


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
        check=_is_pubsub_responsive,
        timeout=60,
        transient=xdist_pubsub_isolation_level == "server",
    ) as service:
        _smoke_pubsub_emulator(
            service.container,
            project=pubsub_project,
        )
        yield PubSubService(
            container=service.container,
            host=service.host,
            port=service.port,
            project=pubsub_project,
            emulator_host=f"{service.host}:{service.port}",
        )


@pytest.fixture(scope="session")
def pubsub_image() -> str:
    """Provide the Google Cloud CLI emulators container image.

    Returns:
        Emulator container image tag.
    """
    return PUBSUB_EMULATOR_IMAGE


@pytest.fixture(scope="session")
def pubsub_project() -> str:
    """Provide a worker-scoped Google Cloud project ID for Pub/Sub tests.

    Returns:
        Google Cloud project ID string.
    """
    worker_id = get_xdist_worker_id()
    if worker_id is None or worker_id == "master":
        return "pytest-databases"
    return f"pytest-databases-{worker_id}"


@pytest.fixture(scope="session")
def xdist_pubsub_isolation_level() -> XdistIsolationLevel:
    """Provide the pytest-xdist isolation level for the Pub/Sub emulator.

    Returns:
        Default isolation level string.
    """
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


def _is_pubsub_responsive(service: ServiceContainer) -> bool:
    """Check whether the Pub/Sub emulator TCP socket is accepting connections.

    Returns:
        True when a TCP connection to ``service.host:service.port`` succeeds.
    """
    try:
        connection = socket.create_connection((service.host, service.port), timeout=1)
    except OSError:
        return False
    connection.close()
    return True


def _smoke_pubsub_emulator(
    emulator_container: Container,
    *,
    project: str,
) -> None:
    """Execute an end-to-end topic/subscription publish/pull smoke check inside the container.

    Raises:
        RuntimeError: If the smoke script exits with a non-zero status.
    """
    result = emulator_container.exec_run(
        ["bash", "-c", _PUBSUB_SMOKE_SCRIPT],
        environment={
            "CLOUDSDK_API_ENDPOINT_OVERRIDES_PUBSUB": f"http://localhost:{PUBSUB_EMULATOR_PORT}/",
            "CLOUDSDK_AUTH_DISABLE_CREDENTIALS": "true",
            "CLOUDSDK_CORE_PROJECT": project,
        },
    )
    if result.exit_code != 0:
        output = exec_output_to_bytes(result.output).decode("utf-8", errors="replace")
        msg = f"Pub/Sub emulator smoke check failed with exit code {result.exit_code}: {output[-2000:]}"
        raise RuntimeError(msg)
