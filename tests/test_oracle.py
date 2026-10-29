"""Tests for Oracle database container service fixtures and per-worker schema isolation."""

from __future__ import annotations

from typing import TYPE_CHECKING
from unittest.mock import MagicMock, patch

import pytest

from pytest_databases.docker import oracle
from pytest_databases.docker.oracle import (
    OracleService,
    ensure_oracle_user,
    open_oracle_connection,
    provide_oracle_service,
)
from pytest_databases.types import ServiceContainer

if TYPE_CHECKING:
    from pytest import MonkeyPatch

pytest_plugins = ["pytest_databases.docker.oracle"]


def test_plugin_imports_without_oracledb(pytester: pytest.Pytester) -> None:
    """Ensure the Oracle module imports cleanly when oracledb is absent."""
    pytester.makepyfile("""
    import builtins
    import importlib

    def test_import() -> None:
        original_import = builtins.__import__

        def blocked_import(name, globals=None, locals=None, fromlist=(), level=0):
            if name.partition(".")[0] in {"oracledb", "cx_Oracle"}:
                raise ModuleNotFoundError(name)
            return original_import(name, globals, locals, fromlist, level)

        builtins.__import__ = blocked_import
        try:
            module = importlib.import_module("pytest_databases.docker.oracle")
            assert module.OracleService
        finally:
            builtins.__import__ = original_import
    """)

    result = pytester.runpytest_subprocess("-p", "pytest_databases", "-vv")
    result.assert_outcomes(passed=1)


def test_xdist_oracle_isolation_level_default(xdist_oracle_isolation_level: str) -> None:
    """Ensure xdist_oracle_isolation_level defaults to database."""
    assert xdist_oracle_isolation_level == "database"


def test_oracle_database_isolation_naming_and_user() -> None:
    """Ensure database isolation preserves shared name and assigns per-worker user."""
    mock_docker = MagicMock()
    mock_container = MagicMock()
    mock_service = ServiceContainer(container=mock_container, host="127.0.0.1", port=1521)
    mock_docker.run.return_value.__enter__.return_value = mock_service

    with (
        patch("pytest_databases.docker.oracle.get_xdist_worker_num", return_value=2),
        patch("pytest_databases.docker.oracle.ensure_oracle_user", return_value=True) as mock_ensure,
        patch("pytest_databases.docker.oracle._exec_sqlplus", return_value=(0, b"1")),
        provide_oracle_service(
            docker_service=mock_docker,
            image="gvenzl/oracle-free:23-slim-faststart",
            name="oracle23ai",
            service_name="FREEPDB1",
            user="app",
            password="secret",
            system_password="sys-secret",
            isolation_level="database",
        ) as service,
    ):
        assert service.user == "app_2"
        call_kwargs = mock_docker.run.call_args[1]
        assert call_kwargs["name"] == "oracle23ai"
        assert call_kwargs["transient"] is False
        check_fn = call_kwargs["check"]
        assert check_fn(mock_service) is True
        mock_ensure.assert_called_once_with(
            mock_container,
            user="app_2",
            password="secret",
            service_name="FREEPDB1",
            system_password="sys-secret",
        )


def test_oracle_server_isolation_naming_and_user() -> None:
    """Ensure server isolation suffixes name and retains default user."""
    mock_docker = MagicMock()
    mock_container = MagicMock()
    mock_service = ServiceContainer(container=mock_container, host="127.0.0.1", port=1521)
    mock_docker.run.return_value.__enter__.return_value = mock_service

    with (
        patch("pytest_databases.docker.oracle.get_xdist_worker_num", return_value=3),
        patch("pytest_databases.docker.oracle._exec_sqlplus", return_value=(0, b"1")),
        provide_oracle_service(
            docker_service=mock_docker,
            image="gvenzl/oracle-free:23-slim-faststart",
            name="oracle23ai",
            service_name="FREEPDB1",
            user="app",
            password="secret",
            system_password="sys-secret",
            isolation_level="server",
        ) as service,
    ):
        assert service.user == "app"

    call_kwargs = mock_docker.run.call_args[1]
    assert call_kwargs["name"] == "oracle23ai_3"
    assert call_kwargs["transient"] is True


def test_ensure_oracle_user_invokes_sysdba() -> None:
    """Ensure ensure_oracle_user connects as sysdba to create user."""
    mock_container = MagicMock()
    with patch("pytest_databases.docker.oracle._exec_sqlplus", return_value=(0, b"")) as mock_exec:
        assert (
            ensure_oracle_user(
                container=mock_container,
                user="app_1",
                password="secret",
                service_name="FREEPDB1",
                system_password="sys-secret",
            )
            is True
        )

    mock_exec.assert_called_once()
    _, kwargs = mock_exec.call_args
    assert kwargs["user"] == "sys"
    assert kwargs["password"] == "sys-secret"
    assert kwargs["as_sysdba"] is True
    assert kwargs["whenever_sqlerror"] == "CONTINUE"
    assert "CREATE USER app_1" in kwargs["sql"]


def test_deprecated_oracle_connection_helpers_emit_warnings(monkeypatch: MonkeyPatch) -> None:
    """Verify deprecated oracle_responsive and open_oracle_connection emit DeprecationWarning."""
    fake_conn = MagicMock()
    fake_cursor = MagicMock()
    fake_cursor.fetchone.return_value = (1,)
    fake_conn.cursor.return_value.__enter__.return_value = fake_cursor
    fake_conn.__enter__.return_value = fake_conn

    fake_oracledb = MagicMock()
    fake_oracledb.connect.return_value = fake_conn
    monkeypatch.setattr(oracle, "_load_oracledb", lambda: fake_oracledb)

    with pytest.deprecated_call(match="oracle_responsive"):
        assert oracle.oracle_responsive("127.0.0.1", 1521, "FREEPDB1", "app", "secret") is True

    service = OracleService(
        container=MagicMock(),
        host="127.0.0.1",
        port=1521,
        user="app",
        password="secret",
        system_password="sys-secret",
        service_name="FREEPDB1",
    )
    with (
        pytest.deprecated_call(match="oracle_23ai_connection"),
        open_oracle_connection(service, "oracle_23ai_connection") as conn,
    ):
        assert conn is fake_conn


@pytest.fixture(scope="module")
def oracle_test_helpers() -> str:
    """Provide SQL*Plus execution helper code for pytester integration tests."""
    return """
    import shlex

    def run_sqlplus(service, sql):
        statement = sql.strip()
        if not statement.endswith(";"):
            statement = f"{statement};"
        script = "\\n".join([
            "SET HEADING OFF FEEDBACK OFF PAGESIZE 0 VERIFY OFF ECHO OFF",
            "WHENEVER OSERROR EXIT 9",
            "WHENEVER SQLERROR EXIT SQL.SQLCODE",
            statement,
            "EXIT",
            "",
        ])
        connect_string = f"{service.user}/{service.password}@//localhost:1521/{service.service_name}"
        command = f"printf '%s' {shlex.quote(script)} | sqlplus -L -S {shlex.quote(connect_string)}"
        result = service.container.exec_run(["bash", "-lc", command])
        assert result.exit_code == 0, result.output.decode(errors="replace")
        return [line.strip() for line in result.output.decode().splitlines() if line.strip()]
    """


@pytest.mark.parametrize(
    "service_fixture",
    [
        "oracle_18c_service",
        "oracle_23ai_service",
    ],
)
def test_service_fixture(pytester: pytest.Pytester, service_fixture: str, oracle_test_helpers: str) -> None:
    """Run integration smoke tests against Oracle 18c and 23ai service fixtures."""
    pytester.makepyfile(f"""
    pytest_plugins = ["pytest_databases.docker.oracle"]

    {oracle_test_helpers}

    def test({service_fixture}):
        assert run_sqlplus({service_fixture}, "SELECT 1 FROM dual") == ["1"]
        run_sqlplus({service_fixture}, "CREATE or replace view simple_table as SELECT 1 as the_value from dual")
        assert run_sqlplus({service_fixture}, "select * from simple_table") == ["1"]
    """)

    result = pytester.runpytest_subprocess("-p", "pytest_databases")
    result.assert_outcomes(passed=1)
