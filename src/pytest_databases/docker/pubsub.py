from __future__ import annotations

import socket
from dataclasses import dataclass
from typing import TYPE_CHECKING

import pytest

from pytest_databases.helpers import get_xdist_worker_id
from pytest_databases.types import ServiceContainer, XdistIsolationLevel

if TYPE_CHECKING:
    from collections.abc import Generator

    from docker.models.containers import Container

    from pytest_databases._service import ContainerService

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


def _pubsub_start_command(project: str) -> list[str]:
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
    result = emulator_container.exec_run(
        ["bash", "-c", _PUBSUB_SMOKE_SCRIPT],
        environment={
            "CLOUDSDK_API_ENDPOINT_OVERRIDES_PUBSUB": f"http://localhost:{PUBSUB_EMULATOR_PORT}/",
            "CLOUDSDK_AUTH_DISABLE_CREDENTIALS": "true",
            "CLOUDSDK_CORE_PROJECT": project,
        },
    )
    if result.exit_code != 0:
        output = result.output.decode(errors="replace") if isinstance(result.output, bytes) else str(result.output)
        msg = f"Pub/Sub emulator smoke check failed with exit code {result.exit_code}: {output[-2000:]}"
        raise RuntimeError(msg)


@pytest.fixture(scope="session")
def pubsub_service(
    container_service: ContainerService,
    pubsub_image: str,
    pubsub_project: str,
    xdist_pubsub_isolation_level: XdistIsolationLevel,
) -> Generator[PubSubService, None, None]:
    worker_id = get_xdist_worker_id()
    container_name = "pubsub"
    if xdist_pubsub_isolation_level == "server" and worker_id not in {None, "master"}:
        container_name = f"{container_name}_{worker_id}"

    with container_service.run(
        image=pubsub_image,
        command=_pubsub_start_command(pubsub_project),
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
