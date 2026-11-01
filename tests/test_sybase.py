"""Unit tests for SAP Sybase ASE container fixtures and CLI helpers."""

from __future__ import annotations

from types import SimpleNamespace
from typing import Any
from unittest.mock import MagicMock

import pytest

import pytest_databases.docker.sybase as sybase_mod
from pytest_databases.docker.sybase import (
    DEFAULT_SYBASE_IMAGE,
    SYBASE_DATABASE,
    SYBASE_PASSWORD,
    SYBASE_USER,
    SybaseService,
    check_sybase_socket_ready,
    create_worker_database,
    exec_isql,
    provide_sybase_service,
    validate_sybase_database_name,
)


def test_plugin_imports_without_sybase_clients(pytester: pytest.Pytester) -> None:
    """Verify sybase module loads without requiring pymssql or other drivers."""
    pytester.makepyfile("""
    import builtins
    import importlib

    def test_import() -> None:
        original_import = builtins.__import__
        blocked = {"pymssql", "_mssql"}

        def blocked_import(name, globals=None, locals=None, fromlist=(), level=0):
            if name.partition(".")[0] in blocked:
                raise ModuleNotFoundError(name)
            return original_import(name, globals, locals, fromlist, level)

        builtins.__import__ = blocked_import
        try:
            module = importlib.import_module("pytest_databases.docker.sybase")
            assert module.SybaseService
        finally:
            builtins.__import__ = original_import
    """)
    result = pytester.runpytest_subprocess("-p", "pytest_databases", "-vv")
    result.assert_outcomes(passed=1)


def test_sybase_service_dataclass_properties() -> None:
    """Verify SybaseService properties generate expected connection dicts and DSN."""
    fake_container = MagicMock()
    service = SybaseService(
        container=fake_container,
        host="127.0.0.1",
        port=5000,
        user="sa",
        password="myPassword",
        database="testdb",
    )
    assert service.connection_config == {
        "server": "127.0.0.1",
        "port": 5000,
        "user": "sa",
        "password": "myPassword",
        "database": "testdb",
        "autocommit": True,
    }
    assert "DRIVER={FreeTDS}" in service.dsn
    assert "TDS_Version=5.0" in service.dsn
    assert "SERVER=127.0.0.1" in service.dsn
    assert "PORT=5000" in service.dsn


def test_sybase_validate_database_name() -> None:
    """Verify Sybase database name validation rules."""
    assert validate_sybase_database_name("valid_db") == "valid_db"
    assert validate_sybase_database_name("test_db_123") == "test_db_123"

    with pytest.raises(ValueError, match="Invalid Sybase database name"):
        validate_sybase_database_name("1_starts_with_number")

    with pytest.raises(ValueError, match="Invalid Sybase database name"):
        validate_sybase_database_name("a" * 31)

    with pytest.raises(ValueError, match="Invalid Sybase database name"):
        validate_sybase_database_name("invalid-hyphen")


def test_sybase_exec_isql_command_construction() -> None:
    """Verify exec_isql builds proper sh command with isql candidates."""
    fake_container = MagicMock()
    fake_container.exec_run.return_value = SimpleNamespace(exit_code=0, output=b"1\n")

    exit_code, output = exec_isql(
        fake_container,
        "SELECT 1",
        database="master",
        user="sa",
        password="myPassword",
    )
    assert exit_code == 0
    assert output == b"1\n"
    fake_container.exec_run.assert_called_once()
    args, _kwargs = fake_container.exec_run.call_args
    assert args[0][0] == "sh"
    assert "-U sa" in args[0][2]
    assert "-P myPassword" in args[0][2]
    assert "-D master" in args[0][2]
    assert "SELECT 1" in args[0][2]


def test_sybase_create_worker_database(monkeypatch: pytest.MonkeyPatch) -> None:
    """Verify create_worker_database invokes exec_isql with valid DDL."""
    fake_container = MagicMock()
    executed_statements: list[str] = []

    def fake_exec_isql(_container: Any, sql: str, **_kwargs: Any) -> tuple[int, bytes]:
        executed_statements.append(sql)
        return 0, b""

    monkeypatch.setattr(sybase_mod, "exec_isql", fake_exec_isql)
    create_worker_database(fake_container, "worker_db")
    assert len(executed_statements) == 1
    assert "CREATE DATABASE worker_db" in executed_statements[0]


def test_sybase_create_worker_database_failure(monkeypatch: pytest.MonkeyPatch) -> None:
    """Verify create_worker_database raises RuntimeError on non-zero exit code."""
    fake_container = MagicMock()
    monkeypatch.setattr(sybase_mod, "exec_isql", lambda *_args, **_kwargs: (1, b"Msg 1801, CREATE DATABASE failed"))

    with pytest.raises(RuntimeError, match="Failed to create Sybase database"):
        create_worker_database(fake_container, "failed_db")


def test_sybase_check_socket_ready(monkeypatch: pytest.MonkeyPatch) -> None:
    """Verify check_sybase_socket_ready handles connection success and failure."""
    fake_socket = MagicMock()
    monkeypatch.setattr("socket.socket", lambda *_args, **_kwargs: fake_socket)

    assert check_sybase_socket_ready("127.0.0.1", 5000) is True

    fake_socket.connect.side_effect = OSError("Connection refused")
    assert check_sybase_socket_ready("127.0.0.1", 5000) is False


def test_provide_sybase_service_lifecycle(monkeypatch: pytest.MonkeyPatch) -> None:
    """Verify provide_sybase_service lifecycle and container arguments."""
    fake_container = MagicMock()
    fake_container.logs.return_value = b"=============== SYBASE INITIALIZED =========================="
    fake_service = SimpleNamespace(host="127.0.0.1", port=5000, container=fake_container)
    run_ctx = MagicMock()
    run_ctx.__enter__.return_value = fake_service
    run_ctx.__exit__.return_value = False
    container_service = MagicMock()
    container_service.run.return_value = run_ctx

    monkeypatch.setattr(sybase_mod, "check_sybase_socket_ready", lambda *_args: True)
    monkeypatch.setattr(sybase_mod, "exec_isql", lambda *_args, **_kwargs: (0, b"1"))
    monkeypatch.setattr(sybase_mod, "create_worker_database", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(sybase_mod, "get_xdist_worker_num", lambda: None)

    with provide_sybase_service(
        container_service=container_service,
        sybase_image=DEFAULT_SYBASE_IMAGE,
        sybase_user=SYBASE_USER,
        sybase_password=SYBASE_PASSWORD,
        sybase_database=SYBASE_DATABASE,
        sybase_startup_timeout=60,
        xdist_sybase_isolation_level="database",
    ) as service:
        assert service.host == "127.0.0.1"
        assert service.port == 5000
        assert service.user == "sa"

    container_service.run.assert_called_once()
    kwargs = container_service.run.call_args.kwargs
    assert kwargs["container_port"] == 5000
    assert kwargs["name"] == "sybase"

    check_fn = kwargs["check"]
    assert check_fn(fake_service) is True

    fake_container.logs.return_value = b"Starting Sybase ASE..."
    assert check_fn(fake_service) is False
