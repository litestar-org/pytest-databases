"""Tests for IBM Db2 Community Edition container service fixtures and CLI helpers."""

from __future__ import annotations

from contextlib import contextmanager
from typing import TYPE_CHECKING, Any, cast
from unittest.mock import MagicMock

import pytest

from pytest_databases.docker import db2
from pytest_databases.docker.db2 import (
    DEFAULT_DB2_IMAGE,
    Db2Service,
    create_worker_database,
    exec_db2_sql,
    validate_db2_database_name,
)
from pytest_databases.types import ServiceContainer

if TYPE_CHECKING:
    from pytest import MonkeyPatch


def test_plugin_imports_without_db2_clients(pytester: pytest.Pytester) -> None:
    """Ensure the Db2 module imports cleanly when ibm_db packages are absent."""
    pytester.makepyfile("""
    import builtins
    import importlib

    def test_import() -> None:
        original_import = builtins.__import__
        blocked = {"ibm_db", "ibm_db_dbi", "ibm_db_sa"}

        def blocked_import(name, globals=None, locals=None, fromlist=(), level=0):
            if name.partition(".")[0] in blocked:
                raise ModuleNotFoundError(name)
            return original_import(name, globals, locals, fromlist, level)

        builtins.__import__ = blocked_import
        try:
            module = importlib.import_module("pytest_databases.docker.db2")
            assert module.Db2Service
        finally:
            builtins.__import__ = original_import
    """)

    result = pytester.runpytest_subprocess("-p", "pytest_databases", "-vv")
    result.assert_outcomes(passed=1)


def test_validate_db2_database_name_enforces_eight_char_limit() -> None:
    """Verify validate_db2_database_name accepts valid 1-8 char names and rejects invalid ones."""
    assert validate_db2_database_name("pytestdb") == "pytestdb"
    assert validate_db2_database_name("ptdb_0") == "ptdb_0"

    with pytest.raises(ValueError, match="at most 8 characters"):
        validate_db2_database_name("pytest_databases")

    with pytest.raises(ValueError, match="must start with a letter"):
        validate_db2_database_name("1db")


def test_db2_service_metadata_and_exec_helpers() -> None:
    """Verify Db2Service dsn, connection_config, exec_sql, and create_worker_database."""
    container = MagicMock()
    container.exec_run.return_value = MagicMock(exit_code=0, output=b"1\n")

    service = Db2Service(
        container=container,
        host="127.0.0.1",
        port=50000,
        db_name="pytestdb",
        username="db2inst1",
        password="pytest_db2_pwd",
    )
    assert service.dsn == (
        "DATABASE=pytestdb;HOSTNAME=127.0.0.1;PORT=50000;PROTOCOL=TCPIP;UID=db2inst1;PWD=pytest_db2_pwd;"
    )
    assert service.connection_config == {
        "database": "pytestdb",
        "hostname": "127.0.0.1",
        "port": 50000,
        "protocol": "TCPIP",
        "user": "db2inst1",
        "password": "pytest_db2_pwd",
    }

    output = service.exec_sql("SELECT 1 FROM SYSIBM.SYSDUMMY1")
    assert output == "1"
    args, _ = container.exec_run.call_args
    assert args[0][:3] == ["su", "-", "db2inst1"]
    assert "SELECT 1 FROM SYSIBM.SYSDUMMY1" in args[0][4]

    service.create_worker_database("ptdb_1")
    create_args, _ = container.exec_run.call_args
    assert "db2 create database ptdb_1" in create_args[0][4]

    container.exec_run.return_value = MagicMock(exit_code=4, output=b"SQL1032N")
    with pytest.raises(RuntimeError, match="Db2 SQL command failed"):
        exec_db2_sql(container, "SELECT 1 FROM SYSIBM.SYSDUMMY1", db_name="pytestdb")

    with pytest.raises(RuntimeError, match="Failed to create Db2 database"):
        create_worker_database(container, "ptdb_2")


def test_db2_contract_fixtures(pytester: pytest.Pytester, monkeypatch: MonkeyPatch) -> None:
    """Verify default values of db2_image, db2_dbname, db2_username, and xdist_db2_isolation_level."""
    for var in ("PYTEST_XDIST_WORKER", "DB2_IMAGE", "DB2_DBNAME", "DB2_USER", "DB2_PASSWORD"):
        monkeypatch.delenv(var, raising=False)

    pytester.makepyfile(f"""
    pytest_plugins = ["pytest_databases.docker.db2"]

    def test_contract(
        db2_image,
        db2_dbname,
        db2_username,
        db2_password,
        db2_startup_timeout,
        xdist_db2_isolation_level,
    ) -> None:
        assert db2_image == {DEFAULT_DB2_IMAGE!r}
        assert db2_dbname == "pytestdb"
        assert db2_username == "db2inst1"
        assert db2_password == "pytest_db2_pwd"
        assert db2_startup_timeout == 600
        assert xdist_db2_isolation_level == "database"
    """)

    result = pytester.runpytest_subprocess("-p", "pytest_databases", "-vv")
    result.assert_outcomes(passed=1)


def test_db2_service_uses_privileged_and_host_ipc(monkeypatch: MonkeyPatch) -> None:
    """Verify db2_service launches the container with privileged=True and ipc_mode='host'."""
    captured_kwargs: dict[str, object] = {}
    mock_container = MagicMock()
    mock_container.exec_run.return_value = MagicMock(exit_code=0, output=b"1\n")

    class FakeContainerService:
        def run(self, image: str, **kwargs: object) -> Any:
            captured_kwargs["image"] = image
            captured_kwargs.update(kwargs)

            @contextmanager
            def _ctx() -> Any:
                svc = ServiceContainer(container=mock_container, host="127.0.0.1", port=50000)
                check_fn = kwargs.get("check")
                if callable(check_fn):
                    assert check_fn(svc) is True
                yield svc

            return _ctx()

    monkeypatch.setattr(db2, "get_xdist_worker_num", lambda: 2)
    with db2.provide_db2_service(
        container_service=cast("Any", FakeContainerService()),
        db2_image=DEFAULT_DB2_IMAGE,
        db2_dbname="ptdb_2",
        db2_username="db2inst1",
        db2_password="pytest_db2_pwd",
        db2_startup_timeout=600,
        xdist_db2_isolation_level="database",
    ) as service:
        assert service.db_name == "ptdb_2"
        assert captured_kwargs["privileged"] is True
        assert captured_kwargs["ipc_mode"] == "host"
        assert captured_kwargs["wait_for_log"] == "Setup has completed"
