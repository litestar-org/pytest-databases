from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    import pytest


def test_service_fixture(pytester: pytest.Pytester) -> None:
    pytester.makepyfile("""
    from google.cloud import bigquery

    pytest_plugins = ["pytest_databases.docker.bigquery"]

    def test(bigquery_service) -> None:
        client = bigquery.Client(
            project=bigquery_service.project,
            client_options=bigquery_service.client_options,
            credentials=bigquery_service.credentials,
        )

        job = client.query(query="SELECT 1 as one")

        resp = list(job.result())
        assert resp[0].one == 1
    """)

    result = pytester.runpytest_subprocess("-p", "pytest_databases")
    result.assert_outcomes(passed=1)


def test_client_fixture(pytester: pytest.Pytester) -> None:
    pytester.makepyfile("""
    from google.cloud import bigquery

    pytest_plugins = ["pytest_databases.docker.bigquery"]

    def test(bigquery_client) -> None:
        assert isinstance(bigquery_client, bigquery.Client)
    """)

    result = pytester.runpytest_subprocess("-p", "pytest_databases")
    result.assert_outcomes(passed=1)


def test_xdist(pytester: pytest.Pytester) -> None:
    pytester.makepyfile("""
    from google.cloud import bigquery

    pytest_plugins = ["pytest_databases.docker.bigquery"]

    def test_one(bigquery_client, bigquery_service) -> None:
        bigquery_client.query(f"CREATE TABLE `{bigquery_service.dataset}.test` AS select 1 as the_value")

    def test_two(bigquery_client, bigquery_service) -> None:
        bigquery_client.query(f"CREATE TABLE `{bigquery_service.dataset}.test` AS select 1 as the_value")
    """)

    result = pytester.runpytest_subprocess("-p", "pytest_databases", "-n", "2")
    result.assert_outcomes(passed=2)
