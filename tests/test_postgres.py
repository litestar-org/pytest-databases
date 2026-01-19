from __future__ import annotations

import pytest


@pytest.mark.parametrize(
    "service_fixture",
    [
        "postgres_service",
        "postgres_12_service",
        "postgres_13_service",
        "postgres_14_service",
        "postgres_15_service",
        "postgres_16_service",
        "postgres_17_service",
        "postgres_18_service",
        "alloydb_omni_service",
        "pgvector_service",
    ],
)
def test_service_fixture(pytester: pytest.Pytester, service_fixture: str) -> None:
    pytester.makepyfile(f"""
    import pytest
    import psycopg
    from pytest_databases.docker.postgres import _make_connection_string  # noqa: PLC2701


    pytest_plugins = [
        "pytest_databases.docker.postgres",
    ]

    def test({service_fixture}) -> None:
        with psycopg.connect(
            _make_connection_string(
                host={service_fixture}.host,
                port={service_fixture}.port,
                user={service_fixture}.user,
                password={service_fixture}.password,
                database={service_fixture}.database,
            )
        ) as conn:
            db_open = conn.execute("SELECT 1").fetchone()
            assert db_open is not None and db_open[0] == 1
    """)

    result = pytester.runpytest_subprocess("-p", "pytest_databases")
    result.assert_outcomes(passed=1)


@pytest.mark.parametrize(
    "connection_fixture",
    [
        "postgres_connection",
        "postgres_11_connection",
        "postgres_12_connection",
        "postgres_13_connection",
        "postgres_14_connection",
        "postgres_15_connection",
        "postgres_16_connection",
        "postgres_17_connection",
        "postgres_18_connection",
        "alloydb_omni_connection",
        "pgvector_connection",
    ],
)
def test_startup_connection_fixture(pytester: pytest.Pytester, connection_fixture: str) -> None:
    pytester.makepyfile(f"""
    import pytest
    import psycopg
    from pytest_databases.docker.postgres import _make_connection_string  # noqa: PLC2701


    pytest_plugins = [
        "pytest_databases.docker.postgres",
    ]

    def test({connection_fixture}) -> None:
        {connection_fixture}.execute("CREATE TABLE if not exists simple_table as SELECT 1")
        result = {connection_fixture}.execute("select * from simple_table").fetchone()
        assert result is not None and result[0] == 1
    """)

    result = pytester.runpytest_subprocess("-p", "pytest_databases")
    result.assert_outcomes(passed=1)


def test_xdist_isolate_db(pytester: pytest.Pytester) -> None:
    pytester.makepyfile("""
    import pytest
    import psycopg
    from pytest_databases.docker.postgres import _make_connection_string  # noqa: PLC2701


    pytest_plugins = ["pytest_databases.docker.postgres"]

    def test_two(postgres_connection) -> None:
        postgres_connection.execute("CREATE TABLE foo AS SELECT 1")

    def test_two(postgres_connection) -> None:
        postgres_connection.execute("CREATE TABLE foo AS SELECT 1")
    """)

    result = pytester.runpytest_subprocess("-p", "pytest_databases", "-n", "2")
    result.assert_outcomes(passed=1)


def test_xdist_isolate_server(pytester: pytest.Pytester) -> None:
    pytester.makepyfile("""
    import pytest
    import psycopg
    from pytest_databases.docker.postgres import _make_connection_string

    pytest_plugins = [
        "pytest_databases.docker.postgres",
    ]

    @pytest.fixture(scope="session")
    def xdist_postgres_isolation_level():
        return "server"

    def test_one(postgres_service) -> None:
        with psycopg.connect(
            _make_connection_string(
                host=postgres_service.host,
                port=postgres_service.port,
                user=postgres_service.user,
                password=postgres_service.password,
                database=postgres_service.database,
            ),
            autocommit=True,
        ) as conn:
            conn.execute("CREATE DATABASE foo")

    def test_two(postgres_service) -> None:
        with psycopg.connect(
            _make_connection_string(
                host=postgres_service.host,
                port=postgres_service.port,
                user=postgres_service.user,
                password=postgres_service.password,
                database=postgres_service.database,
            ),
            autocommit=True,
        ) as conn:
            conn.execute("CREATE DATABASE foo")
    """)

    result = pytester.runpytest_subprocess("-p", "pytest_databases", "-n", "2")
    result.assert_outcomes(passed=2)
