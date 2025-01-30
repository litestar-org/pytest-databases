from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    import pytest


def test_service_fixture(pytester: pytest.Pytester) -> None:
    pytester.makepyfile("""
    import pytest
    import psycopg
    from pytest_databases.docker.postgres import _make_connection_string  # noqa: PLC2701

    pytest_plugins = ["pytest_databases.docker.alloydb_omni"]

    def test(alloydb_omni_service) -> None:
        with psycopg.connect(
            _make_connection_string(
                host=alloydb_omni_service.host,
                port=alloydb_omni_service.port,
                user=alloydb_omni_service.user,
                password=alloydb_omni_service.password,
                database=alloydb_omni_service.database,
            )
        ) as conn:
            db_open = conn.execute("SELECT 1").fetchone()
            assert db_open is not None and db_open[0] == 1
    """)

    result = pytester.runpytest()
    result.assert_outcomes(passed=1)


def test_startup_connection_fixture(pytester: pytest.Pytester) -> None:
    pytester.makepyfile("""
    import pytest
    import psycopg
    from pytest_databases.docker.postgres import _make_connection_string  # noqa: PLC2701

    pytest_plugins = ["pytest_databases.docker.alloydb_omni"]

    def test(alloydb_omni_connection) -> None:
        alloydb_omni_connection.execute("CREATE TABLE if not exists simple_table as SELECT 1")
        result = alloydb_omni_connection.execute("select * from simple_table").fetchone()
        assert result is not None and result[0] == 1
    """)

    result = pytester.runpytest()
    result.assert_outcomes(passed=1)


def test_xdist_isolate(pytester: pytest.Pytester) -> None:
    pytester.makepyfile("""
    import pytest
    import psycopg
    from pytest_databases.docker.postgres import _make_connection_string

    pytest_plugins = ["pytest_databases.docker.alloydb_omni"]


    def test_one(alloydb_omni_service) -> None:
        with psycopg.connect(
            _make_connection_string(
                host=alloydb_omni_service.host,
                port=alloydb_omni_service.port,
                user=alloydb_omni_service.user,
                password=alloydb_omni_service.password,
                database=alloydb_omni_service.database,
            ),
            autocommit=True,
        ) as conn:
            conn.execute("CREATE DATABASE foo")

    def test_two(alloydb_omni_service) -> None:
        with psycopg.connect(
            _make_connection_string(
                host=alloydb_omni_service.host,
                port=alloydb_omni_service.port,
                user=alloydb_omni_service.user,
                password=alloydb_omni_service.password,
                database=alloydb_omni_service.database,
            ),
            autocommit=True,
        ) as conn:
            conn.execute("CREATE DATABASE foo")
    """)

    result = pytester.runpytest_subprocess("-n", "2")
    result.assert_outcomes(passed=2)
