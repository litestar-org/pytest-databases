from __future__ import annotations

import socket

import pytest


def _pick_free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.bind(("127.0.0.1", 0))
        return sock.getsockname()[1]


@pytest.mark.parametrize(
    ("service_fixture", "env_var"),
    [
        ("postgres_15_service", "POSTGRES_15_PORT"),
        ("pgvector_18_service", "PGVECTOR_18_PORT"),
        ("paradedb_18_service", "PARADEDB_18_PORT"),
        ("alloydb_omni_17_service", "ALLOYDB_OMNI_17_PORT"),
    ],
)
def test_port_pinning_via_env(
    pytester: pytest.Pytester,
    monkeypatch: pytest.MonkeyPatch,
    service_fixture: str,
    env_var: str,
) -> None:
    free_port = _pick_free_port()
    pytester.makepyfile(f"""
    import pytest

    pytest_plugins = ["pytest_databases.docker.postgres"]

    def test_pinned({service_fixture}) -> None:
        assert {service_fixture}.port == {free_port}
    """)
    monkeypatch.setenv(env_var, str(free_port))
    result = pytester.runpytest_subprocess("-p", "pytest_databases")
    result.assert_outcomes(passed=1)


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
        "alloydb_omni_15_service",
        "alloydb_omni_16_service",
        "alloydb_omni_17_service",
        "pgvector_service",
        "pgvector_13_service",
        "pgvector_14_service",
        "pgvector_15_service",
        "pgvector_16_service",
        "pgvector_17_service",
        "pgvector_18_service",
        "paradedb_service",
        "paradedb_15_service",
        "paradedb_16_service",
        "paradedb_17_service",
        "paradedb_18_service",
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
        "alloydb_omni_15_connection",
        "alloydb_omni_16_connection",
        "alloydb_omni_17_connection",
        "pgvector_connection",
        "pgvector_13_connection",
        "pgvector_14_connection",
        "pgvector_15_connection",
        "pgvector_16_connection",
        "pgvector_17_connection",
        "pgvector_18_connection",
        "paradedb_connection",
        "paradedb_15_connection",
        "paradedb_16_connection",
        "paradedb_17_connection",
        "paradedb_18_connection",
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
