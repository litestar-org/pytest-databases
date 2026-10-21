"""Tests for Oracle database container service fixtures and per-worker schema isolation."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

from pytest_databases.docker.oracle import (
    ensure_oracle_user,
    provide_oracle_service,
)
from pytest_databases.types import ServiceContainer

pytest_plugins = ["pytest_databases.docker.oracle"]


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


@pytest.fixture(scope="module")
def oracle_test_helpers() -> str:
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
