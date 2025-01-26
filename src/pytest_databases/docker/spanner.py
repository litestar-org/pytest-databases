from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

import pytest
from google.api_core.client_options import ClientOptions
from google.auth.credentials import AnonymousCredentials, Credentials
from google.cloud import spanner

from pytest_databases.helpers import get_xdist_worker_num
from pytest_databases.types import ServiceContainer

if TYPE_CHECKING:
    from collections.abc import Generator

    from pytest_databases._service import DockerService


@pytest.fixture(scope="session")
def spanner_image() -> str:
    return "gcr.io/cloud-spanner-emulator/emulator:latest"


@dataclass
class SpannerService(ServiceContainer):
    credentials: Credentials
    project: str
    database_name: str
    instance_name: str

    @property
    def endpoint(self) -> str:
        return f"{self.host}:{self.port}"

    @property
    def client_options(self) -> ClientOptions:
        return ClientOptions(api_endpoint=self.endpoint)


@pytest.fixture(autouse=False, scope="session")
def spanner_service(docker_service: DockerService, spanner_image: str) -> Generator[SpannerService, None, None]:
    with docker_service.run(
        image=spanner_image,
        name=f"pytest_databases_spanner_{get_xdist_worker_num() or 0}",
        container_port=9010,
        wait_for_log="gRPC server listening at",
        transient=True,
    ) as service:
        yield SpannerService(
            host=service.host,
            port=service.port,
            credentials=AnonymousCredentials(),
            project="emulator-test-project",
            instance_name="emulator-test-instance",
            database_name="emulator-test-database",
        )


@pytest.fixture(autouse=False, scope="session")
def spanner_connection(
    spanner_service: SpannerService,
) -> Generator[spanner.Client, None, None]:
    client = spanner.Client(
        project=spanner_service.project,
        credentials=spanner_service.credentials,
        client_options=spanner_service.client_options,
    )
    try:
        yield client
    finally:
        client.close()
