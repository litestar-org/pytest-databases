from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

import pytest
from google.api_core.client_options import ClientOptions
from google.auth.credentials import AnonymousCredentials, Credentials
from google.cloud import bigquery

from pytest_databases._service import DockerService
from pytest_databases.helpers import get_xdist_worker_id
from pytest_databases.types import ServiceContainer

if TYPE_CHECKING:
    from collections.abc import Generator


@dataclass
class BigQueryService(ServiceContainer):
    project: str
    dataset: str
    credentials: Credentials

    @property
    def endpoint(self) -> str:
        return f"http://{self.host}:{self.port}"

    @property
    def client_options(self) -> ClientOptions:
        return ClientOptions(api_endpoint=self.endpoint)


@pytest.fixture(scope="session")
def bigquery_xdist_isolate() -> bool:
    return True


@pytest.fixture(autouse=False, scope="session")
def bigquery_service(
    docker_service: DockerService,
    bigquery_xdist_isolate: bool,
) -> Generator[BigQueryService, None, None]:
    project = "emulator-test-project"
    dataset = "test-dataset"

    def check(_service: ServiceContainer) -> bool:
        try:
            client = bigquery.Client(
                project=project,
                client_options=ClientOptions(api_endpoint=f"http://{_service.host}:{_service.port}"),
                credentials=AnonymousCredentials(),
            )

            job = client.query(query="SELECT 1 as one")

            resp = list(job.result())
            return resp[0].one == 1
        except Exception:  # noqa: BLE001
            return False

    container_name = "bigquery"
    if not bigquery_xdist_isolate:
        container_name = f"{container_name}_{get_xdist_worker_id()}"

    with docker_service.run(
        image="ghcr.io/goccy/bigquery-emulator:latest",
        command=f"--project={project} --dataset={dataset}",
        name=container_name,
        check=check,
        env={
            "PROJECT_ID": project,
            "DATASET_NAME": dataset,
        },
        container_port=9050,
        timeout=60,
    ) as service:
        yield BigQueryService(
            host=service.host,
            port=service.port,
            project=project,
            dataset=dataset,
            credentials=AnonymousCredentials(),
        )


@pytest.fixture(autouse=False, scope="session")
def bigquery_startup_connection(
    bigquery_service: BigQueryService,
) -> Generator[bigquery.Client, None, None]:
    yield bigquery.Client(
        project=bigquery_service.project,
        client_options=bigquery_service.client_options,
        credentials=bigquery_service.credentials,
    )
