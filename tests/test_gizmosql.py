"""Tests for GizmoSQL container service fixtures."""

from __future__ import annotations

from typing import TYPE_CHECKING
from unittest.mock import MagicMock, patch

import pytest

from pytest_databases.docker.gizmosql import (
    GizmoSQLService,
    exec_gizmosql,
    provide_deprecated_gizmosql_connection,
    provide_gizmosql_service,
)

if TYPE_CHECKING:
    from pytest import Pytester


def test_plugin_imports_without_adbc_driver_flightsql(pytester: Pytester) -> None:
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


def test_gizmosql_service_properties_and_exec() -> None:
    container = MagicMock()
    container.exec_run.return_value = MagicMock(exit_code=0, output=b"1\n")
    service = GizmoSQLService(
        host="127.0.0.1",
        port=31337,
        container=container,
        username="gizmosql_username",
        password="gizmosql_password",
        backend="sqlite",
    )
    assert service.uri == "grpc+tls://127.0.0.1:31337"
    assert service.backend == "sqlite"
    assert service.connection_kwargs == {
        "username": "gizmosql_username",
        "password": "gizmosql_password",
        "adbc.flight.sql.client_option.tls_skip_verify": "true",
    }
    code, out = exec_gizmosql(container, "SELECT 1", user="gizmosql_username", password="gizmosql_password")
    assert code == 0
    assert out == b"1\n"


def test_provide_gizmosql_service_sets_backend_env() -> None:
    container = MagicMock()
    container.exec_run.return_value = MagicMock(exit_code=0, output=b"1\n")
    docker_service = MagicMock()
    docker_service.run.return_value.__enter__.return_value = MagicMock(
        host="127.0.0.1",
        port=31337,
        container=container,
    )
    with provide_gizmosql_service(
        docker_service=docker_service,
        isolation_level="database",
        image="gizmodata/gizmosql:latest",
        username="u",
        password="p",
        backend="sqlite",
    ) as svc:
        assert svc.backend == "sqlite"
        run_kwargs = docker_service.run.call_args.kwargs
        assert run_kwargs["name"] == "gizmosql-sqlite"
        assert run_kwargs["env"]["DATABASE_BACKEND"] == "sqlite"
        assert run_kwargs["check"](svc) is True


def test_deprecated_gizmosql_connection_emits_warning() -> None:
    service = GizmoSQLService(
        host="127.0.0.1",
        port=31337,
        container=MagicMock(),
        username="u",
        password="p",
    )
    fake_conn = MagicMock()
    fake_flightsql = MagicMock()
    fake_flightsql.connect.return_value.__enter__.return_value = fake_conn
    with (
        patch("importlib.import_module", return_value=fake_flightsql),
        pytest.deprecated_call(match="gizmosql_connection"),
    ):
        gen = provide_deprecated_gizmosql_connection(service)
        assert next(gen) is fake_conn
        fake_flightsql.connect.assert_called_once_with(
            uri="grpc+tls://127.0.0.1:31337",
            db_kwargs=service.connection_kwargs,
            autocommit=True,
        )
        with pytest.raises(StopIteration):
            next(gen)


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


def test_service_fixture(pytester: Pytester) -> None:
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


def test_backend_specific_service_fixtures(pytester: Pytester) -> None:
    pytester.makepyfile(f"""
from pytest_databases.docker.gizmosql import GizmoSQLService

pytest_plugins = ["pytest_databases.docker.gizmosql"]

{GIZMOSQL_TEST_HELPERS}

def configured_backend(service: GizmoSQLService) -> str:
    prefix = "DATABASE_BACKEND="
    return next(value.removeprefix(prefix) for value in service.container.attrs["Config"]["Env"] if value.startswith(prefix))


def test(
    gizmosql_service: GizmoSQLService,
    gizmosql_duckdb_service: GizmoSQLService,
    gizmosql_sqlite_service: GizmoSQLService,
) -> None:
    assert gizmosql_service is gizmosql_duckdb_service
    assert gizmosql_duckdb_service.container.id != gizmosql_sqlite_service.container.id
    assert "gizmosql-duckdb" in gizmosql_duckdb_service.container.name
    assert "gizmosql-sqlite" in gizmosql_sqlite_service.container.name
    assert gizmosql_duckdb_service.backend == "duckdb"
    assert gizmosql_sqlite_service.backend == "sqlite"
    assert configured_backend(gizmosql_duckdb_service) == "duckdb"
    assert configured_backend(gizmosql_sqlite_service) == "sqlite"
    assert "1" in run_gizmosql(gizmosql_duckdb_service, "SELECT 1")
    assert "1" in run_gizmosql(gizmosql_sqlite_service, "SELECT 1")
""")

    result = pytester.runpytest_subprocess("-p", "pytest_databases", "-vv")
    result.assert_outcomes(passed=1)


def test_service_ddl_dml(pytester: Pytester) -> None:
    pytester.makepyfile(f"""
from pytest_databases.docker.gizmosql import GizmoSQLService

pytest_plugins = ["pytest_databases.docker.gizmosql"]

{GIZMOSQL_TEST_HELPERS}

def test(gizmosql_service: GizmoSQLService) -> None:
    \"\"\"Verify combined DDL and DML visibility under Flight SQL semantics.\"\"\"
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


def test_xdist_isolate_server(pytester: Pytester) -> None:
    """Test xdist server isolation with GizmoSQL.

    Since DuckDB and SQLite do not support multiple databases per instance,
    each xdist worker gets its own container.
    """
    pytester.makepyfile(f"""
import pytest
from pytest_databases.docker.gizmosql import GizmoSQLService

pytest_plugins = ["pytest_databases.docker.gizmosql"]


@pytest.fixture(scope="session")
def xdist_gizmosql_isolation_level():
    return "server"

{GIZMOSQL_TEST_HELPERS}

def test_one(
    gizmosql_duckdb_service: GizmoSQLService,
    gizmosql_sqlite_service: GizmoSQLService,
) -> None:
    for service in (gizmosql_duckdb_service, gizmosql_sqlite_service):
        run_gizmosql(
            service,
            "CREATE TABLE worker_test (id INTEGER); INSERT INTO worker_test VALUES (1);",
        )
        output = run_gizmosql(service, "SELECT id FROM worker_test")
        assert "1" in output


def test_two(
    gizmosql_duckdb_service: GizmoSQLService,
    gizmosql_sqlite_service: GizmoSQLService,
) -> None:
    for service in (gizmosql_duckdb_service, gizmosql_sqlite_service):
        run_gizmosql(
            service,
            "CREATE TABLE worker_test (id INTEGER); INSERT INTO worker_test VALUES (2);",
        )
        output = run_gizmosql(service, "SELECT id FROM worker_test")
        assert "2" in output
""")

    result = pytester.runpytest_subprocess("-p", "pytest_databases", "-n", "2")
    result.assert_outcomes(passed=2)


def test_custom_image(pytester: Pytester) -> None:
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
