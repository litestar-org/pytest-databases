"""Tests for CockroachDB container service fixtures."""

from __future__ import annotations

from typing import TYPE_CHECKING
from unittest.mock import MagicMock, patch

import pytest
from docker.errors import APIError

from pytest_databases.docker import cockroachdb
from pytest_databases.docker.cockroachdb import (
    CockroachDBService,
    _prepare_database,
    cockroachdb_connection,
    cockroachdb_driver_opts,
    exec_cockroach_sql,
    provide_cockroachdb_service,
)
from pytest_databases.types import ServiceContainer
from tests.conftest import unwrap_fixture

if TYPE_CHECKING:
    from _pytest.pytester import Pytester


def test_plugin_imports_without_psycopg(pytester: Pytester) -> None:
    """Verify cockroachdb plugin imports cleanly without psycopg installed."""
    pytester.makepyfile("""
    import builtins

    def test_import() -> None:
        original_import = builtins.__import__

        def blocked_import(name, globals=None, locals=None, fromlist=(), level=0):
            if name == "psycopg" or name.startswith("psycopg."):
                raise ModuleNotFoundError(name)
            return original_import(name, globals, locals, fromlist, level)

        builtins.__import__ = blocked_import
        try:
            import pytest_databases.docker.cockroachdb
        finally:
            builtins.__import__ = original_import
    """)

    result = pytester.runpytest_subprocess("-p", "pytest_databases", "-vv")
    result.assert_outcomes(passed=1)


def test_cockroachdb_deprecated_connection_shim() -> None:
    """Verify cockroachdb_connection emits DeprecationWarning and lazily connects with driver_opts."""
    mock_psycopg = MagicMock()
    mock_conn = MagicMock()
    mock_psycopg.connect.return_value.__enter__.return_value = mock_conn
    service = CockroachDBService(
        host="127.0.0.1",
        port=26257,
        container=MagicMock(),
        database="pytest_databases",
        driver_opts={"sslmode": "disable"},
    )
    assert unwrap_fixture(cockroachdb_driver_opts)() == {"sslmode": "disable"}

    with (
        patch("importlib.import_module", return_value=mock_psycopg) as mock_import,
        pytest.warns(DeprecationWarning, match="cockroachdb_connection") as record,
    ):
        conn_gen = unwrap_fixture(cockroachdb_connection)(service, service.driver_opts)
        assert next(conn_gen) is mock_conn
        with pytest.raises(StopIteration):
            next(conn_gen)

    assert len(record) == 1
    assert record[0].filename == cockroachdb.__file__
    mock_import.assert_called_once_with("psycopg")
    mock_psycopg.connect.assert_called_once_with(
        "postgresql://root@127.0.0.1:26257/pytest_databases?sslmode=disable",
    )


def test_service_fixture(pytester: Pytester) -> None:
    """Verify cockroachdb_service executes SQL via the in-container cockroach CLI."""
    pytester.makepyfile("""
    pytest_plugins = ["pytest_databases.docker.cockroachdb"]

    def run_cockroach(service, sql, database=None):
        result = service.container.exec_run([
            "cockroach",
            "sql",
            "--insecure",
            "--host=localhost:26257",
            f"--database={database or service.database}",
            "--format=tsv",
            "-e",
            sql,
        ])
        assert result.exit_code == 0, result.output.decode(errors="replace")
        return [line.strip() for line in result.output.decode().splitlines() if line.strip()]

    def test(cockroachdb_service):
        assert cockroachdb_service.driver_opts == {"sslmode": "disable"}
        rows = run_cockroach(cockroachdb_service, "SELECT 1")
        assert rows[-1] == "1"
        run_cockroach(cockroachdb_service, "CREATE TABLE IF NOT EXISTS simple_table (the_value INT)")
        run_cockroach(cockroachdb_service, "INSERT INTO simple_table VALUES (1)")
        rows = run_cockroach(cockroachdb_service, "SELECT the_value FROM simple_table")
        assert rows[-1] == "1"
        run_cockroach(cockroachdb_service, "DROP TABLE simple_table")
    """)

    result = pytester.runpytest_subprocess("-p", "pytest_databases", "-vv")
    result.assert_outcomes(passed=1)


def test_xdist_isolate_database(pytester: Pytester) -> None:
    """Verify cockroachdb_service isolates databases per pytest-xdist worker."""
    pytester.makepyfile("""
    pytest_plugins = ["pytest_databases.docker.cockroachdb"]

    def run_cockroach(service, sql):
        result = service.container.exec_run([
            "cockroach",
            "sql",
            "--insecure",
            "--host=localhost:26257",
            f"--database={service.database}",
            "-e",
            sql,
        ])
        assert result.exit_code == 0, result.output.decode(errors="replace")

    def test_one(cockroachdb_service):
        run_cockroach(cockroachdb_service, "CREATE TABLE foo (the_value INT)")

    def test_two(cockroachdb_service):
        run_cockroach(cockroachdb_service, "CREATE TABLE foo (the_value INT)")
    """)

    result = pytester.runpytest_subprocess("-p", "pytest_databases", "-n", "2", "-vv")
    result.assert_outcomes(passed=2)


def test_xdist_isolate_server(pytester: Pytester) -> None:
    """Verify cockroachdb_service isolates server containers per pytest-xdist worker."""
    pytester.makepyfile("""
    import pytest

    pytest_plugins = ["pytest_databases.docker.cockroachdb"]

    @pytest.fixture(scope="session")
    def xdist_cockroachdb_isolation_level():
        return "server"

    def run_cockroach(service, sql, database=None):
        result = service.container.exec_run([
            "cockroach",
            "sql",
            "--insecure",
            "--host=localhost:26257",
            f"--database={database or service.database}",
            "-e",
            sql,
        ])
        assert result.exit_code == 0, result.output.decode(errors="replace")

    def test_one(cockroachdb_service):
        run_cockroach(cockroachdb_service, "CREATE DATABASE db_test", database="defaultdb")

    def test_two(cockroachdb_service):
        run_cockroach(cockroachdb_service, "CREATE DATABASE db_test", database="defaultdb")
    """)

    result = pytester.runpytest_subprocess("-p", "pytest_databases", "-n", "2", "-vv")
    result.assert_outcomes(passed=2)


@pytest.mark.parametrize(
    ("worker_num", "isolation_level", "expected_name", "expected_db"),
    [
        (None, "database", "cockroachdb", "pytest_databases"),
        (1, "database", "cockroachdb", "pytest_databases_1"),
        (2, "server", "cockroachdb_2", "pytest_databases"),
    ],
)
def test_provide_cockroachdb_service_and_helpers(
    monkeypatch: pytest.MonkeyPatch,
    worker_num: int | None,
    isolation_level: str,
    expected_name: str,
    expected_db: str,
) -> None:
    """Verify provide_cockroachdb_service xdist modes, readiness check, and retry exhaustion."""
    monkeypatch.setattr("pytest_databases.docker.cockroachdb.time.sleep", lambda _s: None)
    monkeypatch.setattr("pytest_databases.docker.cockroachdb.get_xdist_worker_num", lambda: worker_num)
    mock_docker = MagicMock()
    mock_container = MagicMock()
    mock_container.exec_run.return_value = MagicMock(exit_code=0, output=b"1\n")
    svc_container = ServiceContainer(host="127.0.0.1", port=26257, container=mock_container)
    mock_docker.run.return_value.__enter__.return_value = svc_container

    caller_opts = {"sslmode": "disable", "connect_timeout": "5"}
    with provide_cockroachdb_service(
        docker_service=mock_docker,
        isolation_level=isolation_level,  # type: ignore[arg-type]
        driver_opts=caller_opts,
        image="cockroachdb/cockroach:latest",
    ) as service:
        assert service.database == expected_db
        assert service.user == "root"
        assert service.driver_opts == caller_opts
        assert service.driver_opts is not caller_opts

    check = mock_docker.run.call_args.kwargs["check"]
    assert mock_docker.run.call_args.kwargs["name"] == expected_name
    assert check(svc_container) is True

    mock_container.exec_run.side_effect = APIError("boom")
    code, out = exec_cockroach_sql(mock_container, "SELECT 1", database="defaultdb")
    assert code == -1
    assert b"boom" in out

    mock_container.exec_run.side_effect = None
    mock_container.exec_run.return_value = MagicMock(exit_code=1, output=b"not ready")
    with pytest.raises(RuntimeError, match="could not be prepared"):
        _prepare_database(mock_container, "test_db")


@pytest.mark.parametrize(
    ("host", "user", "database", "driver_opts", "expected_dsn", "expected_config"),
    [
        pytest.param(
            "127.0.0.1",
            "root",
            "pytest",
            {"sslmode": "disable"},
            "postgresql://root@127.0.0.1:26257/pytest?sslmode=disable",
            {"host": "127.0.0.1", "port": 26257, "user": "root", "database": "pytest", "sslmode": "disable"},
            id="default",
        ),
        pytest.param(
            "127.0.0.1",
            "root",
            "pytest",
            {},
            "postgresql://root@127.0.0.1:26257/pytest",
            {"host": "127.0.0.1", "port": 26257, "user": "root", "database": "pytest"},
            id="empty-driver-opts",
        ),
        pytest.param(
            "127.0.0.1",
            "root",
            "pytest",
            {"sslmode": "disable", "application_name": "pt test"},
            "postgresql://root@127.0.0.1:26257/pytest?sslmode=disable&application_name=pt+test",
            {
                "host": "127.0.0.1",
                "port": 26257,
                "user": "root",
                "database": "pytest",
                "sslmode": "disable",
                "application_name": "pt test",
            },
            id="multi-driver-opts",
        ),
        pytest.param(
            "::1",
            "root",
            "pytest",
            {"sslmode": "disable"},
            "postgresql://root@[::1]:26257/pytest?sslmode=disable",
            {"host": "::1", "port": 26257, "user": "root", "database": "pytest", "sslmode": "disable"},
            id="ipv6",
        ),
        pytest.param(
            "127.0.0.1",
            "ro ot",
            "db/1",
            {"sslmode": "disable"},
            "postgresql://ro%20ot@127.0.0.1:26257/db%2F1?sslmode=disable",
            {"host": "127.0.0.1", "port": 26257, "user": "ro ot", "database": "db/1", "sslmode": "disable"},
            id="url-encoded-user-db",
        ),
    ],
)
def test_cockroachdb_service_dsn_and_connection_config(
    host: str,
    user: str,
    database: str,
    driver_opts: dict[str, str],
    expected_dsn: str,
    expected_config: dict[str, object],
) -> None:
    """Verify CockroachDBService exposes PostgreSQL-wire dsn and connection_config safely."""
    service = CockroachDBService(
        host=host,
        port=26257,
        container=MagicMock(),
        database=database,
        driver_opts=driver_opts,
        user=user,
    )
    assert service.dsn == expected_dsn
    assert service.connection_config == expected_config


@pytest.mark.parametrize(
    ("sql", "database_override", "expected_db_flag"),
    [
        pytest.param("SELECT 42", None, "--database=pytest_gw1", id="default-database"),
        pytest.param("SHOW DATABASES", "defaultdb", "--database=defaultdb", id="explicit-database"),
    ],
)
def test_cockroachdb_service_exec_sql_and_public_helper(
    sql: str,
    database_override: str | None,
    expected_db_flag: str,
) -> None:
    """Verify CockroachDBService.exec_sql delegates to public exec_cockroach_sql without private aliases."""
    assert "exec_cockroach_sql" in cockroachdb.__all__
    assert not hasattr(cockroachdb, "_exec_cockroach_sql")

    container = MagicMock()
    container.exec_run.return_value = MagicMock(exit_code=0, output=b"42\n")
    service = CockroachDBService(
        host="127.0.0.1",
        port=26257,
        container=container,
        database="pytest_gw1",
    )

    code, output = service.exec_sql(sql, database=database_override)
    assert (code, output) == (0, b"42\n")
    cmd = container.exec_run.call_args.args[0]
    assert expected_db_flag in cmd
    assert cmd[-1] == sql

    container.exec_run.side_effect = APIError("boom")
    err_code, err_out = service.exec_sql("SELECT 1")
    assert err_code == -1
    assert b"boom" in err_out


def test_cockroachdb_all_fixtures_inprocess(pytester: Pytester) -> None:
    """Exercise all CockroachDB session fixtures in-process with a mocked provide_cockroachdb_service."""
    pytester.makepyfile("""
    from contextlib import contextmanager
    from unittest.mock import MagicMock, patch
    import pytest
    from pytest_databases.docker import cockroachdb as crdb_mod
    from pytest_databases.docker.cockroachdb import CockroachDBService

    pytest_plugins = ["pytest_databases.docker.cockroachdb"]

    @pytest.fixture(scope="session")
    def docker_service():
        return MagicMock()

    @contextmanager
    def _fake_provide(**kwargs):
        yield CockroachDBService(
            host="127.0.0.1",
            port=26257,
            container=MagicMock(),
            database="pytest_databases",
            driver_opts=kwargs["driver_opts"],
        )

    def test_all(request):
        with patch.object(crdb_mod, "provide_cockroachdb_service", _fake_provide):
            for name in ("xdist_cockroachdb_isolation_level", "cockroachdb_image", "cockroachdb_driver_opts", "cockroachdb_service"):
                assert request.getfixturevalue(name) is not None
    """)
    result = pytester.runpytest("-p", "no:sugar", "-p", "pytest_databases")
    result.assert_outcomes(passed=1)
