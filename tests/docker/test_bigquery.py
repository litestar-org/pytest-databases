from __future__ import annotations

from typing import TYPE_CHECKING

from google.cloud import bigquery

from pytest_databases.docker.bigquery import BigQueryService

if TYPE_CHECKING:
    pass

pytest_plugins = [
    "pytest_databases.docker.bigquery",
]


def test_bigquery_service(bigquery_service: BigQueryService) -> None:
    client = bigquery.Client(
        project=bigquery_service.project,
        client_options=bigquery_service.client_options,
        credentials=bigquery_service.credentials,
    )

    job = client.query(query="SELECT 1 as one")

    resp = list(job.result())
    assert resp[0].one == 1


def test_bigquery_service_after_start(
    bigquery_startup_connection: bigquery.Client,
) -> None:
    assert isinstance(bigquery_startup_connection, bigquery.Client)
