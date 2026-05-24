from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

import pytest

from pytest_databases.helpers import get_xdist_worker_num
from pytest_databases.types import ServiceContainer

if TYPE_CHECKING:
    from collections.abc import Generator

    from docker.models.containers import Container

    from pytest_databases._service import DockerService


SPANNER_GCLOUD_CLI_IMAGE = "gcr.io/google.com/cloudsdktool/cloud-sdk:slim"

_SPANNER_BOOTSTRAP_SCRIPT = """\
set -euo pipefail
gcloud config configurations create emulator --quiet 2>/dev/null \
    || gcloud config configurations activate emulator --quiet
gcloud config set auth/disable_credentials true --quiet
gcloud config set project "$PROJECT" --quiet
gcloud config set api_endpoint_overrides/spanner http://localhost:9020/ --quiet
gcloud spanner instances describe "$INSTANCE" --quiet >/dev/null 2>&1 \
    || gcloud spanner instances create "$INSTANCE" --config=emulator-config --description=pytest-databases --nodes=1 --quiet
gcloud spanner databases describe "$DATABASE" --instance="$INSTANCE" --quiet >/dev/null 2>&1 \
    || gcloud spanner databases create "$DATABASE" --instance="$INSTANCE" --quiet
"""


def _bootstrap_spanner_emulator(
    docker_service: DockerService,
    emulator_container: Container,
    *,
    project: str,
    instance_name: str,
    database_name: str,
) -> None:
    docker_service._client.containers.run(
        SPANNER_GCLOUD_CLI_IMAGE,
        entrypoint=["bash", "-c", _SPANNER_BOOTSTRAP_SCRIPT],
        environment={"PROJECT": project, "INSTANCE": instance_name, "DATABASE": database_name},
        network_mode=f"container:{emulator_container.id}",
        remove=True,
    )


@pytest.fixture(scope="session")
def spanner_image() -> str:
    return "gcr.io/cloud-spanner-emulator/emulator:latest"


@dataclass
class SpannerService(ServiceContainer):
    project: str
    database_name: str
    instance_name: str

    @property
    def endpoint(self) -> str:
        return f"{self.host}:{self.port}"


@pytest.fixture(autouse=False, scope="session")
def spanner_service(docker_service: DockerService, spanner_image: str) -> Generator[SpannerService, None, None]:
    project = "emulator-test-project"
    instance_name = "emulator-test-instance"
    database_name = "emulator-test-database"
    with docker_service.run(
        image=spanner_image,
        name=f"pytest_databases_spanner_{get_xdist_worker_num() or 0}",
        container_port=9010,
        wait_for_log="gRPC server listening at",
        transient=True,
    ) as service:
        _bootstrap_spanner_emulator(
            docker_service,
            service.container,
            project=project,
            instance_name=instance_name,
            database_name=database_name,
        )
        yield SpannerService(
            host=service.host,
            port=service.port,
            container=service.container,
            project=project,
            instance_name=instance_name,
            database_name=database_name,
        )
