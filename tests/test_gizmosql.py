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

    from pytest_databases.types import XdistIsolationLevel


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


@pytest.mark.parametrize(
    ("worker_num", "isolation_level", "expected_name"),
    [
        pytest.param(None, "database", "gizmosql-sqlite", id="no-xdist"),
        pytest.param(0, "database", "gizmosql-sqlite_0", id="database-gw0"),
        pytest.param(3, "database", "gizmosql-sqlite_3", id="database-gw3"),
        pytest.param(3, "server", "gizmosql-sqlite_3", id="server-gw3"),
    ],
)
def test_provide_gizmosql_service_container_per_worker(
    worker_num: int | None,
    isolation_level: XdistIsolationLevel,
    expected_name: str,
) -> None:
    container = MagicMock()
    docker_service = MagicMock()
    docker_service.run.return_value.__enter__.return_value = MagicMock(
        host="127.0.0.1",
        port=31337,
        container=container,
    )
    with (
        patch("pytest_databases.docker.gizmosql.get_xdist_worker_num", return_value=worker_num),
        provide_gizmosql_service(
            docker_service=docker_service,
            isolation_level=isolation_level,
            image="gizmodata/gizmosql:latest",
            username="u",
            password="p",
            backend="sqlite",
        ) as svc,
    ):
        assert svc.backend == "sqlite"
    run_kwargs = docker_service.run.call_args.kwargs
    assert run_kwargs["name"] == expected_name
    assert run_kwargs["env"]["DATABASE_BACKEND"] == "sqlite"
    assert run_kwargs["transient"] is (isolation_level == "server")


@pytest.mark.parametrize(
    ("exit_code", "output", "expected"),
    [
        pytest.param(0, b"probe\n4242\n", True, id="exact-value"),
        pytest.param(0, b"| probe |\n| 4242  |\n", True, id="table-format"),
        pytest.param(0, b"connected to localhost:31337\n", False, id="banner-with-1"),
        pytest.param(0, b"42420\n", False, id="partial-value"),
        pytest.param(1, b"4242\n", False, id="non-zero-exit"),
    ],
)
def test_provide_gizmosql_service_readiness_matches_exact_value(exit_code: int, output: bytes, expected: bool) -> None:
    container = MagicMock()
    container.exec_run.return_value = MagicMock(exit_code=exit_code, output=output)
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
        backend="duckdb",
    ) as svc:
        assert docker_service.run.call_args.kwargs["check"](svc) is expected
    command = container.exec_run.call_args.args[0]
    assert command[command.index("--command") + 1] == "SELECT 4242 AS probe"


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
from pytest_databases.docker.gizmosql import exec_gizmosql

def run_gizmosql(service, sql):
    exit_code, output = exec_gizmosql(
        service.container,
        sql,
        user=service.username,
        password=service.password,
    )
    decoded = output.decode(errors="replace").strip()
    assert exit_code == 0, decoded
    return decoded
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


@pytest.fixture(
    params=[
        pytest.param("gizmosql_duckdb_service", id="duckdb"),
        pytest.param("gizmosql_sqlite_service", id="sqlite"),
    ]
)
def gizmosql_backend_service(request: pytest.FixtureRequest) -> str:
    return request.param


@pytest.mark.parametrize(
    "isolation_override",
    [
        pytest.param("", id="default-isolation"),
        pytest.param(
            """
@pytest.fixture(scope="session")
def xdist_gizmosql_isolation_level():
    return "server"
""",
            id="server-isolation",
        ),
    ],
)
def test_xdist_container_per_worker(pytester: Pytester, gizmosql_backend_service: str, isolation_override: str) -> None:
    """Each xdist worker gets its own container per backend, whatever the isolation level."""
    pytester.makepyfile(f"""
import os

import pytest
from pytest_databases.docker.gizmosql import GizmoSQLService

pytest_plugins = ["pytest_databases.docker.gizmosql"]

{isolation_override}
{GIZMOSQL_TEST_HELPERS}

def assert_worker_container(service: GizmoSQLService) -> None:
    worker_num = int(os.environ["PYTEST_XDIST_WORKER"].removeprefix("gw"))
    assert f"gizmosql-{{service.backend}}_{{worker_num}}_" in service.container.name
    assert "4242" in run_gizmosql(service, "SELECT 4242")


def test_one({gizmosql_backend_service}: GizmoSQLService) -> None:
    assert_worker_container({gizmosql_backend_service})


def test_two({gizmosql_backend_service}: GizmoSQLService) -> None:
    assert_worker_container({gizmosql_backend_service})
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


def test_exec_gizmosql_retries_on_sigabrt() -> None:
    """Verify exec_gizmosql retries when gizmosql_client exits with 134 (SIGABRT)."""
    container = MagicMock()
    container.exec_run.side_effect = [
        MagicMock(exit_code=134, output=b"terminate called"),
        MagicMock(exit_code=0, output=b"1\n"),
    ]
    with patch("pytest_databases.docker.gizmosql.time.sleep"):
        code, output = exec_gizmosql(container, "SELECT 1;", user="u", password="p")
    assert code == 0
    assert output == b"1\n"
    assert container.exec_run.call_count == 2


def test_gizmosql_all_fixtures_inprocess(pytester: Pytester) -> None:
    """Verify GizmoSQL config and service fixtures execute in-process with mocked provider."""
    pytester.makepyfile("""
    from contextlib import contextmanager
    from unittest.mock import MagicMock, patch
    import pytest

    pytest_plugins = ["pytest_databases.docker.gizmosql"]

    @pytest.fixture(scope="session")
    def docker_service() -> MagicMock:
        return MagicMock()

    def test_fixtures(request: pytest.FixtureRequest) -> None:
        mock_svc = MagicMock()

        @contextmanager
        def fake_svc(*args, **kwargs):
            yield mock_svc

        def fake_conn(*args, **kwargs):
            yield "conn"

        with (
            patch("pytest_databases.docker.gizmosql.provide_gizmosql_service", side_effect=fake_svc),
            patch("pytest_databases.docker.gizmosql.provide_deprecated_gizmosql_connection", side_effect=fake_conn),
        ):
            assert request.getfixturevalue("xdist_gizmosql_isolation_level") == "database"
            assert request.getfixturevalue("gizmosql_image") == "gizmodata/gizmosql:latest"
            assert request.getfixturevalue("gizmosql_username") == "gizmosql_username"
            assert request.getfixturevalue("gizmosql_password") == "gizmosql_password"
            assert request.getfixturevalue("gizmosql_duckdb_service") is mock_svc
            assert request.getfixturevalue("gizmosql_sqlite_service") is mock_svc
            assert request.getfixturevalue("gizmosql_service") is mock_svc
            assert request.getfixturevalue("gizmosql_connection") == "conn"
    """)
    result = pytester.runpytest("-p", "no:sugar", "-p", "pytest_databases")
    result.assert_outcomes(passed=1)
