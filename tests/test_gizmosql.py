from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    import pytest


def test_plugin_imports_without_adbc_driver_flightsql(pytester: pytest.Pytester) -> None:
    pytester.makepyfile("""
    import builtins

    def test_import() -> None:
        original_import = builtins.__import__

        def blocked_import(name, globals=None, locals=None, fromlist=(), level=0):
            if name == "adbc_driver_flightsql" or name.startswith("adbc_driver_flightsql."):
                raise ModuleNotFoundError(name)
            return original_import(name, globals, locals, fromlist, level)

        builtins.__import__ = blocked_import
        try:
            import pytest_databases.docker.gizmosql
        finally:
            builtins.__import__ = original_import
    """)

    result = pytester.runpytest_subprocess("-p", "pytest_databases", "-vv")
    result.assert_outcomes(passed=1)


GIZMOSQL_TEST_HELPERS = """
def run_gizmosql(service, sql):
    result = service.container.exec_run(
        [
            "gizmosql_client",
            "--host",
            "localhost",
            "--port",
            "31337",
            "--username",
            service.username,
            "--tls",
            "--tls-skip-verify",
            "--command",
            sql,
        ],
        environment={"GIZMOSQL_PASSWORD": service.password},
    )
    assert result.exit_code == 0, (
        result.output.decode(errors="replace") if isinstance(result.output, bytes) else str(result.output)
    )
    output = result.output
    if isinstance(output, bytes):
        return output.decode().strip()
    if isinstance(output, str):
        return output.strip()
    return b"".join(output).decode().strip()
"""


def test_service_fixture(pytester: pytest.Pytester) -> None:
    pytester.makepyfile(f"""
from pytest_databases.docker.gizmosql import GizmoSQLService

pytest_plugins = ["pytest_databases.docker.gizmosql"]

{GIZMOSQL_TEST_HELPERS}

def test(gizmosql_service: GizmoSQLService) -> None:
    output = run_gizmosql(gizmosql_service, "SELECT 1")
    assert "1" in output
""")

    result = pytester.runpytest_subprocess("-p", "pytest_databases", "-vv")
    result.assert_outcomes(passed=1)


def test_service_ddl_dml(pytester: pytest.Pytester) -> None:
    pytester.makepyfile(f"""
from pytest_databases.docker.gizmosql import GizmoSQLService

pytest_plugins = ["pytest_databases.docker.gizmosql"]

{GIZMOSQL_TEST_HELPERS}

def test(gizmosql_service: GizmoSQLService) -> None:
    # Flight SQL semantics: combine DDL+DML in a single statement for immediate visibility
    run_gizmosql(
        gizmosql_service,
        "CREATE TABLE test_table (id INTEGER, name VARCHAR); INSERT INTO test_table VALUES (1, 'test');",
    )
    output = run_gizmosql(gizmosql_service, "SELECT id, name FROM test_table")
    assert "1" in output
    assert "test" in output
""")

    result = pytester.runpytest_subprocess("-p", "pytest_databases", "-vv")
    result.assert_outcomes(passed=1)


def test_xdist_isolate_server(pytester: pytest.Pytester) -> None:
    """Test xdist server isolation with GizmoSQL.

    Since DuckDB doesn't support multiple databases, each xdist worker
    gets its own container. This test verifies that workers don't
    interfere with each other.
    """
    pytester.makepyfile(f"""
import pytest
from pytest_databases.docker.gizmosql import GizmoSQLService

pytest_plugins = ["pytest_databases.docker.gizmosql"]


@pytest.fixture(scope="session")
def xdist_gizmosql_isolation_level():
    return "server"

{GIZMOSQL_TEST_HELPERS}

def test_one(gizmosql_service: GizmoSQLService) -> None:
    run_gizmosql(
        gizmosql_service,
        "CREATE TABLE worker_test (id INTEGER); INSERT INTO worker_test VALUES (1);",
    )
    output = run_gizmosql(gizmosql_service, "SELECT id FROM worker_test")
    assert "1" in output


def test_two(gizmosql_service: GizmoSQLService) -> None:
    # Would fail if sharing the same container since worker_test already exists
    run_gizmosql(
        gizmosql_service,
        "CREATE TABLE worker_test (id INTEGER); INSERT INTO worker_test VALUES (2);",
    )
    output = run_gizmosql(gizmosql_service, "SELECT id FROM worker_test")
    assert "2" in output
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
