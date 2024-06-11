from __future__ import annotations

from typing import TYPE_CHECKING

import pytest
from google.cloud import bigquery

from pytest_databases.docker.bigquery import bigquery_responsive

if TYPE_CHECKING:
    from google.api_core.client_options import ClientOptions
    from google.auth.credentials import Credentials

    from pytest_databases.docker import DockerServiceRegistry

pytestmark = pytest.mark.anyio
pytest_plugins = [
    "pytest_databases.docker.bigquery",
]


def test_bigquery_default_config(
    bigquery_docker_ip: str,
    bigquery_port: int,
    bigquery_grpc_port: int,
    bigquery_dataset: str,
    bigquery_endpoint: str,
    bigquery_project: str,
) -> None:
    assert bigquery_port == 9051
    assert bigquery_grpc_port == 9061
    assert bigquery_dataset == "test-dataset"
    assert bigquery_endpoint == f"http://{bigquery_docker_ip}:9051"
    assert bigquery_project == "emulator-test-project"


async def test_bigquery_services(
    bigquery_docker_ip: str,
    bigquery_service: DockerServiceRegistry,
    bigquery_endpoint: str,
    bigquery_dataset: str,
    bigquery_client_options: ClientOptions,
    bigquery_project: str,
    bigquery_credentials: Credentials,
) -> None:
    ping = await bigquery_responsive(
        bigquery_docker_ip,
        bigquery_endpoint=bigquery_endpoint,
        bigquery_dataset=bigquery_dataset,
        bigquery_project=bigquery_project,
        bigquery_credentials=bigquery_credentials,
        bigquery_client_options=bigquery_client_options,
    )
    assert ping


async def test_bigquery_service_after_start(
    bigquery_startup_connection: bigquery.Client,
) -> None:
    assert isinstance(bigquery_startup_connection, bigquery.Client)
