# from __future__ import annotations
#
# from typing import TYPE_CHECKING
#
# import psycopg
#
# if TYPE_CHECKING:
#     from pytest_databases.docker.cockroachdb import CockroachDBService
#
# pytest_plugins = [
#     "pytest_databases.docker.cockroachdb",
# ]
#
#
# def test_cockroachdb_default_config(cockroachdb_driver_opts: dict[str, str]) -> None:
#     assert cockroachdb_driver_opts == {"sslmode": "disable"}
#
#
# def test_cockroachdb_service(
#     cockroachdb_service: CockroachDBService,
# ) -> None:
#     opts = "&".join(f"{k}={v}" for k, v in cockroachdb_service.driver_opts.items())
#     with psycopg.connect(
#         f"postgresql://root@{cockroachdb_service.host}:{cockroachdb_service.port}/{cockroachdb_service.database}?{opts}"
#     ) as conn:
#         conn.execute("CREATE TABLE if not exists simple_table as SELECT 1 as the_value")
#         result = conn.execute("select * from simple_table").fetchone()
#         assert result is not None and result[0] == 1
#
#
# def test_cockroachdb_services_after_start(
#     cockroachdb_startup_connection: psycopg.Connection,
# ) -> None:
#     cockroachdb_startup_connection.execute("CREATE TABLE if not exists simple_table as SELECT 1 as the_value")
#     result = cockroachdb_startup_connection.execute("select * from simple_table").fetchone()
#     assert result is not None and result[0] == 1


from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    import pytest


def test_service_fixture(pytester: pytest.Pytester) -> None:
    pytester.makepyfile("""
    import pytest
    import psycopg
    from pytest_databases.docker.postgres import _make_connection_string  # noqa: PLC2701

    pytest_plugins = ["pytest_databases.docker.cockroachdb"]

    def test(cockroachdb_service) -> None:
        opts = "&".join(f"{k}={v}" for k, v in cockroachdb_service.driver_opts.items())
        with psycopg.connect(
            f"postgresql://root@{cockroachdb_service.host}:{cockroachdb_service.port}/{cockroachdb_service.database}?{opts}"
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


    pytest_plugins = ["pytest_databases.docker.cockroachdb"]

    def test(cockroachdb_connection) -> None:
        cockroachdb_connection.execute("CREATE TABLE if not exists simple_table as SELECT 1")
        result = cockroachdb_connection.execute("select * from simple_table").fetchone()
        assert result is not None and result[0] == 1
    """)

    result = pytester.runpytest()
    result.assert_outcomes(passed=1)


def test_xdist_isolate_database(pytester: pytest.Pytester) -> None:
    pytester.makepyfile("""
    import pytest
    import psycopg
    from pytest_databases.docker.postgres import _make_connection_string

    pytest_plugins = ["pytest_databases.docker.cockroachdb"]

    def test_one(cockroachdb_service) -> None:
        opts = "&".join(f"{k}={v}" for k, v in cockroachdb_service.driver_opts.items())
        with psycopg.connect(
            f"postgresql://root@{cockroachdb_service.host}:{cockroachdb_service.port}/{cockroachdb_service.database}?{opts}"
        ) as conn:
            conn.execute("CREATE TABLE foo AS SELECT 1")

    def test_two(cockroachdb_service) -> None:
        opts = "&".join(f"{k}={v}" for k, v in cockroachdb_service.driver_opts.items())
        with psycopg.connect(
            f"postgresql://root@{cockroachdb_service.host}:{cockroachdb_service.port}/{cockroachdb_service.database}?{opts}"
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

    pytest_plugins = ["pytest_databases.docker.cockroachdb"]

    @pytest.fixture(scope="session")
    def xdist_cockroachdb_isolation_level():
        return "server"

    def test_one(cockroachdb_service) -> None:
        opts = "&".join(f"{k}={v}" for k, v in cockroachdb_service.driver_opts.items())
        with psycopg.connect(
            f"postgresql://root@{cockroachdb_service.host}:{cockroachdb_service.port}/{cockroachdb_service.database}?{opts}"
        ) as conn:
            conn.execute("CREATE DATABASE foo")

    def test_two(cockroachdb_service) -> None:
        opts = "&".join(f"{k}={v}" for k, v in cockroachdb_service.driver_opts.items())
        with psycopg.connect(
            f"postgresql://root@{cockroachdb_service.host}:{cockroachdb_service.port}/{cockroachdb_service.database}?{opts}"
        ) as conn:
            conn.execute("CREATE DATABASE foo")
    """)

    result = pytester.runpytest_subprocess("-n", "2")
    result.assert_outcomes(passed=2)
