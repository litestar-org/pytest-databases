from __future__ import annotations

import pytest


@pytest.mark.parametrize(
    "service_fixture",
    [
        "gizmosql_service",
    ],
)
def test_service_fixture(pytester: pytest.Pytester, service_fixture: str) -> None:
    pytester.makepyfile(f"""
    from adbc_driver_flightsql import dbapi as flightsql
    from pytest_databases.docker.gizmosql import GizmoSQLService, _make_connection_kwargs

    pytest_plugins = ["pytest_databases.docker.gizmosql"]

    def test({service_fixture}: GizmoSQLService) -> None:
        db_kwargs = _make_connection_kwargs(
            {service_fixture}.username,
            {service_fixture}.password,
        )
        with flightsql.connect(
            uri={service_fixture}.uri,
            db_kwargs=db_kwargs,
            autocommit=True,
        ) as conn:
            with conn.cursor() as cur:
                cur.execute("SELECT 1")
                result = cur.fetchone()
                assert result is not None and result[0] == 1
    """)

    result = pytester.runpytest_subprocess("-p", "pytest_databases", "-vv")
    result.assert_outcomes(passed=1)


@pytest.mark.parametrize(
    "connection_fixture",
    [
        "gizmosql_connection",
    ],
)
def test_connection_fixture(pytester: pytest.Pytester, connection_fixture: str) -> None:
    pytester.makepyfile(f"""
    pytest_plugins = ["pytest_databases.docker.gizmosql"]

    def test({connection_fixture}) -> None:
        # Note: Flight SQL requires DDL and DML to be combined in a single statement
        # for immediate visibility across cursor operations
        with {connection_fixture}.cursor() as cur:
            cur.execute(\"\"\"
                CREATE TABLE test_table (id INTEGER, name VARCHAR);
                INSERT INTO test_table VALUES (1, 'test');
            \"\"\")

        with {connection_fixture}.cursor() as cur:
            cur.execute("SELECT * FROM test_table")
            result = cur.fetchone()
            assert result is not None
            assert result[0] == 1
            assert result[1] == 'test'
    """)

    result = pytester.runpytest_subprocess("-p", "pytest_databases", "-vv")
    result.assert_outcomes(passed=1)


def test_xdist_isolate_server(pytester: pytest.Pytester) -> None:
    """Test xdist server isolation with GizmoSQL.

    Since DuckDB doesn't support multiple databases, each xdist worker
    gets its own container. This test verifies that workers don't
    interfere with each other.
    """
    pytester.makepyfile("""
    import pytest
    from adbc_driver_flightsql import dbapi as flightsql
    from pytest_databases.docker.gizmosql import GizmoSQLService, _make_connection_kwargs

    pytest_plugins = ["pytest_databases.docker.gizmosql"]

    @pytest.fixture(scope="session")
    def xdist_gizmosql_isolation_level():
        return "server"

    def test_one(gizmosql_service: GizmoSQLService) -> None:
        db_kwargs = _make_connection_kwargs(
            gizmosql_service.username,
            gizmosql_service.password,
        )
        with flightsql.connect(
            uri=gizmosql_service.uri,
            db_kwargs=db_kwargs,
            autocommit=True,
        ) as conn:
            with conn.cursor() as cur:
                # Note: DDL and DML must be combined for Flight SQL
                cur.execute(\"\"\"
                    CREATE TABLE worker_test (id INTEGER);
                    INSERT INTO worker_test VALUES (1);
                \"\"\")

            with conn.cursor() as cur:
                cur.execute("SELECT * FROM worker_test")
                result = cur.fetchone()
                assert result is not None

    def test_two(gizmosql_service: GizmoSQLService) -> None:
        db_kwargs = _make_connection_kwargs(
            gizmosql_service.username,
            gizmosql_service.password,
        )
        with flightsql.connect(
            uri=gizmosql_service.uri,
            db_kwargs=db_kwargs,
            autocommit=True,
        ) as conn:
            with conn.cursor() as cur:
                # This would fail if sharing same container since table already exists
                cur.execute(\"\"\"
                    CREATE TABLE worker_test (id INTEGER);
                    INSERT INTO worker_test VALUES (2);
                \"\"\")

            with conn.cursor() as cur:
                cur.execute("SELECT * FROM worker_test")
                result = cur.fetchone()
                assert result is not None
    """)

    result = pytester.runpytest_subprocess("-p", "pytest_databases", "-n", "2")
    result.assert_outcomes(passed=2)


def test_custom_image(pytester: pytest.Pytester) -> None:
    """Test using a custom GizmoSQL image."""
    pytester.makepyfile("""
    import pytest
    from pytest_databases.docker.gizmosql import GizmoSQLService

    pytest_plugins = ["pytest_databases.docker.gizmosql"]

    @pytest.fixture(scope="session")
    def gizmosql_image():
        return "gizmodata/gizmosql:latest"

    def test(gizmosql_service: GizmoSQLService) -> None:
        assert gizmosql_service.host is not None
        assert gizmosql_service.port > 0
        assert gizmosql_service.username == "gizmosql_username"
        assert gizmosql_service.password == "gizmosql_password"
    """)

    result = pytester.runpytest_subprocess("-p", "pytest_databases", "-vv")
    result.assert_outcomes(passed=1)
