from __future__ import annotations

import contextlib
from typing import TYPE_CHECKING

from google.cloud import spanner

if TYPE_CHECKING:
    from pytest_databases.docker.spanner import SpannerService

pytest_plugins = [
    "pytest_databases.docker.spanner",
]


def test_spanner_services(
    spanner_service: SpannerService,
) -> None:
    spanner_client = spanner.Client(
        project=spanner_service.project,
        credentials=spanner_service.credentials,
        client_options=spanner_service.client_options,
    )
    instance = spanner_client.instance(spanner_service.instance_name)
    with contextlib.suppress(Exception):
        instance.create()

    database = instance.database(spanner_service.database_name)
    with contextlib.suppress(Exception):
        database.create()

    with database.snapshot() as snapshot:
        resp = next(iter(snapshot.execute_sql("SELECT 1")))
    assert resp[0] == 1


def test_spanner_service_after_start(
    spanner_startup_connection: spanner.Client,
) -> None:
    assert isinstance(spanner_startup_connection, spanner.Client)
