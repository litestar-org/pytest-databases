from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    import pytest


def test_service_fixture(pytester: pytest.Pytester) -> None:
    pytester.makepyfile("""
    import pytest
    import psycopg
    from pytest_databases.docker.postgres import _make_connection_string  # noqa: PLC2701

    pytest_plugins = ["pytest_databases.docker.yugabyte"]

    def test(yugabyte_service) -> None:
        opts = "&".join(f"{k}={v}" for k, v in yugabyte_service.driver_opts.items())
        with psycopg.connect(
            f"postgresql://root@{yugabyte_service.host}:{yugabyte_service.port}/{yugabyte_service.database}?{opts}"
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


    pytest_plugins = ["pytest_databases.docker.yugabyte"]

    def test(yugabyte_connection) -> None:
        yugabyte_connection.execute("CREATE TABLE if not exists simple_table as SELECT 1")
        result = yugabyte_connection.execute("select * from simple_table").fetchone()
        assert result is not None and result[0] == 1
    """)

    result = pytester.runpytest()
    result.assert_outcomes(passed=1)


def test_xdist_isolate_database(pytester: pytest.Pytester) -> None:
    pytester.makepyfile("""
    import pytest
    import psycopg
    from pytest_databases.docker.postgres import _make_connection_string

    pytest_plugins = ["pytest_databases.docker.yugabyte"]

    def test_one(yugabyte_service) -> None:
        opts = "&".join(f"{k}={v}" for k, v in yugabyte_service.driver_opts.items())
        with psycopg.connect(
            f"postgresql://root@{yugabyte_service.host}:{yugabyte_service.port}/{yugabyte_service.database}?{opts}"
        ) as conn:
            conn.execute("CREATE TABLE foo AS SELECT 1")

    def test_two(yugabyte_service) -> None:
        opts = "&".join(f"{k}={v}" for k, v in yugabyte_service.driver_opts.items())
        with psycopg.connect(
            f"postgresql://root@{yugabyte_service.host}:{yugabyte_service.port}/{yugabyte_service.database}?{opts}"
        ) as conn:
            conn.execute("CREATE TABLE foo AS SELECT 1")
    """)

    result = pytester.runpytest_subprocess("-n", "2")
    result.assert_outcomes(passed=2)


def test_xdist_isolate_server(pytester: pytest.Pytester) -> None:
    pytester.makepyfile("""
    import pytest
    import psycopg
    from pytest_databases.docker.postgres import _make_connection_string

    pytest_plugins = ["pytest_databases.docker.yugabyte"]

    @pytest.fixture(scope="session")
    def xdist_yugabyte_isolation_level():
        return "server"

    def test_one(yugabyte_service) -> None:
        opts = "&".join(f"{k}={v}" for k, v in yugabyte_service.driver_opts.items())
        with psycopg.connect(
            f"postgresql://root@{yugabyte_service.host}:{yugabyte_service.port}/{yugabyte_service.database}?{opts}"
        ) as conn:
            conn.execute("CREATE DATABASE foo")

    def test_two(yugabyte_service) -> None:
        opts = "&".join(f"{k}={v}" for k, v in yugabyte_service.driver_opts.items())
        with psycopg.connect(
            f"postgresql://root@{yugabyte_service.host}:{yugabyte_service.port}/{yugabyte_service.database}?{opts}"
        ) as conn:
            conn.execute("CREATE DATABASE foo")
    """)

    result = pytester.runpytest_subprocess("-n", "2")
    result.assert_outcomes(passed=2)
