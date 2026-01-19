from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    import pytest


def test_service_fixture(pytester: pytest.Pytester) -> None:
    pytester.makepyfile("""
    from google.cloud import spanner
    import contextlib

    pytest_plugins = ["pytest_databases.docker.spanner"]

    def test_spanner_service(spanner_service) -> None:
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
    """)

    result = pytester.runpytest_subprocess("-p", "pytest_databases", "-vv")
    result.assert_outcomes(passed=1)


def test_spanner_connection(pytester: pytest.Pytester) -> None:
    pytester.makepyfile("""
    from google.cloud import spanner
    pytest_plugins = ["pytest_databases.docker.spanner"]

    def test(spanner_connection) -> None:
        assert isinstance(spanner_connection, spanner.Client)
    """)

    result = pytester.runpytest_subprocess("-p", "pytest_databases")
    result.assert_outcomes(passed=1)
