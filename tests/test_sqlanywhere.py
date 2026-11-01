"""Unit tests for SAP SQL Anywhere container fixtures and CLI helpers."""

from __future__ import annotations

import io
import os
import tarfile
from types import SimpleNamespace
from typing import TYPE_CHECKING, Any
from unittest.mock import MagicMock

import pytest

import pytest_databases.docker.sqlanywhere as sqlanywhere_mod
from pytest_databases.docker.sqlanywhere import (
    DEFAULT_SQLANYWHERE_IMAGE,
    SQLANYWHERE_DATABASE,
    SQLANYWHERE_PASSWORD,
    SQLANYWHERE_SERVER,
    SQLANYWHERE_USER,
    SQLAnywhereService,
    check_sqlanywhere_socket_ready,
    exec_dbisql,
    extract_sqlanywhere_client_libs,
    provide_sqlanywhere_service,
    validate_sqlanywhere_database_name,
)

if TYPE_CHECKING:
    from pathlib import Path

pytest_plugins = ["pytest_databases.docker.sqlanywhere"]


def test_plugin_imports_without_sqlanydb(pytester: pytest.Pytester) -> None:
    """Verify sqlanywhere module loads without requiring sqlanydb."""
    pytester.makepyfile("""
    import builtins
    import importlib

    def test_import() -> None:
        original_import = builtins.__import__
        blocked = {"sqlanydb"}

        def blocked_import(name, globals=None, locals=None, fromlist=(), level=0):
            if name.partition(".")[0] in blocked:
                raise ModuleNotFoundError(name)
            return original_import(name, globals, locals, fromlist, level)

        builtins.__import__ = blocked_import
        try:
            module = importlib.import_module("pytest_databases.docker.sqlanywhere")
            assert module.SQLAnywhereService
        finally:
            builtins.__import__ = original_import
    """)
    result = pytester.runpytest_subprocess("-p", "pytest_databases", "-vv")
    result.assert_outcomes(passed=1)


def test_sqlanywhere_service_dataclass_properties() -> None:
    """Verify SQLAnywhereService properties generate expected connection dicts and DSN."""
    fake_container = MagicMock()
    service = SQLAnywhereService(
        container=fake_container,
        host="127.0.0.1",
        port=2638,
        user="dba",
        password="sql",
        database="demo",
        server_name="demo17",
    )
    assert service.connection_config == {
        "uid": "dba",
        "pwd": "sql",
        "dbn": "demo",
        "eng": "demo17",
        "host": "127.0.0.1:2638",
    }
    assert "UID=dba" in service.dsn
    assert "PWD=sql" in service.dsn
    assert "DBN=demo" in service.dsn
    assert "ENG=demo17" in service.dsn
    assert "host=127.0.0.1;port=2638" in service.dsn


def test_sqlanywhere_validate_database_name() -> None:
    """Verify SQL Anywhere database name validation rules."""
    assert validate_sqlanywhere_database_name("valid_db") == "valid_db"
    assert validate_sqlanywhere_database_name("demo123") == "demo123"

    with pytest.raises(ValueError, match="Invalid SQL Anywhere database name"):
        validate_sqlanywhere_database_name("1_starts_with_digit")

    with pytest.raises(ValueError, match="Invalid SQL Anywhere database name"):
        validate_sqlanywhere_database_name("a" * 129)

    with pytest.raises(ValueError, match="Invalid SQL Anywhere database name"):
        validate_sqlanywhere_database_name("invalid-hyphen")


def test_sqlanywhere_exec_dbisql_command_construction() -> None:
    """Verify exec_dbisql builds proper command string with dbisql candidates."""
    fake_container = MagicMock()
    fake_container.exec_run.return_value = SimpleNamespace(exit_code=0, output=b"1\n")

    exit_code, output = exec_dbisql(
        fake_container,
        "SELECT 1",
        database="demo",
        server_name="demo17",
        user="dba",
        password="sql",
    )
    assert exit_code == 0
    assert output == b"1\n"
    fake_container.exec_run.assert_called_once()
    args, _kwargs = fake_container.exec_run.call_args
    assert args[0][0] == "sh"
    assert "UID=dba;PWD=sql;DBN=demo;ENG=demo17;LINKS=tcpip(host=127.0.0.1;port=2638)" in args[0][2]
    assert "chmod +x /opt/sqlanywhere16/bin64/*" in args[0][2]
    assert "dbisqlc" in args[0][2]
    assert "SELECT 1;" in args[0][2]


def test_sqlanywhere_check_socket_ready(monkeypatch: pytest.MonkeyPatch) -> None:
    """Verify check_sqlanywhere_socket_ready handles connection success and failure."""
    fake_socket = MagicMock()
    monkeypatch.setattr("socket.socket", lambda *_args, **_kwargs: fake_socket)

    assert check_sqlanywhere_socket_ready("127.0.0.1", 2638) is True

    fake_socket.connect.side_effect = OSError("Connection refused")
    assert check_sqlanywhere_socket_ready("127.0.0.1", 2638) is False


def test_provide_sqlanywhere_service_lifecycle(monkeypatch: pytest.MonkeyPatch) -> None:
    """Verify provide_sqlanywhere_service lifecycle and container arguments."""
    fake_container = MagicMock()
    fake_service = SimpleNamespace(host="127.0.0.1", port=2638, container=fake_container)
    run_ctx = MagicMock()
    run_ctx.__enter__.return_value = fake_service
    run_ctx.__exit__.return_value = False
    container_service = MagicMock()
    container_service.run.return_value = run_ctx

    monkeypatch.setattr(sqlanywhere_mod, "check_sqlanywhere_socket_ready", lambda *_args: True)
    monkeypatch.setattr(sqlanywhere_mod, "exec_dbisql", lambda *_args, **_kwargs: (0, b"1"))
    monkeypatch.setattr(sqlanywhere_mod, "get_xdist_worker_num", lambda: None)

    with provide_sqlanywhere_service(
        container_service=container_service,
        sqlanywhere_image=DEFAULT_SQLANYWHERE_IMAGE,
        sqlanywhere_user=SQLANYWHERE_USER,
        sqlanywhere_password=SQLANYWHERE_PASSWORD,
        sqlanywhere_database=SQLANYWHERE_DATABASE,
        sqlanywhere_server=SQLANYWHERE_SERVER,
        sqlanywhere_startup_timeout=30,
        xdist_sqlanywhere_isolation_level="server",
    ) as service:
        assert service.host == "127.0.0.1"
        assert service.port == 2638
        assert service.user == "dba"
        assert service.server_name == "demo"

    container_service.run.assert_called_once()
    kwargs = container_service.run.call_args.kwargs
    assert kwargs["container_port"] == 2638
    assert kwargs["name"] == "sqlanywhere"

    check_fn = kwargs["check"]
    assert check_fn(fake_service) is True

    monkeypatch.setattr(sqlanywhere_mod, "check_sqlanywhere_socket_ready", lambda *_args: False)
    assert check_fn(fake_service) is False


def test_xdist_sqlanywhere_isolation_level_default(xdist_sqlanywhere_isolation_level: str) -> None:
    """Ensure xdist_sqlanywhere_isolation_level defaults to server."""
    assert xdist_sqlanywhere_isolation_level == "server"


def _make_tar_bytes(files: dict[str, bytes]) -> bytes:
    buf = io.BytesIO()
    with tarfile.open(fileobj=buf, mode="w") as tar:
        for name, data in files.items():
            info = tarfile.TarInfo(name=name)
            info.size = len(data)
            tar.addfile(info, io.BytesIO(data))
    return buf.getvalue()


def test_extract_sqlanywhere_client_libs(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Verify extraction of native client libraries from container archive."""
    fake_container = MagicMock()
    fake_container.exec_run.return_value = SimpleNamespace(exit_code=0, output=b"")

    lib_archive = _make_tar_bytes({"lib64/libdbcapi_r.so": b"fake_so", "lib64/libdbtasks16_r.so": b"fake_tasks"})
    res_archive = _make_tar_bytes({"res/en.res": b"fake_res"})

    def fake_get_archive(path: str) -> tuple[list[bytes], dict[str, Any]]:
        if "lib64" in path:
            return [lib_archive], {}
        if "res" in path:
            return [res_archive], {}
        return [], {}

    fake_container.get_archive.side_effect = fake_get_archive

    monkeypatch.delenv("SQLANY16", raising=False)
    monkeypatch.delenv("SQLANY_API_DLL", raising=False)

    target_dir = tmp_path / "sqlany_client"
    res = extract_sqlanywhere_client_libs(fake_container, target_dir, preload=False)

    assert res == target_dir
    assert (target_dir / "lib64" / "libdbcapi_r.so").exists()
    assert (target_dir / "res" / "en.res").exists()


def test_extract_sqlanywhere_client_libs_preload(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Verify library preloading and environment configuration."""
    fake_container = MagicMock()
    fake_container.exec_run.return_value = SimpleNamespace(exit_code=0, output=b"")

    lib_archive = _make_tar_bytes({"lib64/libdbcapi_r.so": b"fake_so"})
    fake_container.get_archive.side_effect = lambda path: ([lib_archive], {}) if "lib64" in path else ([], {})

    mock_cdll = MagicMock()
    monkeypatch.setattr("ctypes.CDLL", mock_cdll)

    target_dir = tmp_path / "sqlany_preload"
    res = extract_sqlanywhere_client_libs(fake_container, target_dir, preload=True)

    assert res == target_dir
    assert os.environ.get("SQLANY16") == str(target_dir)
    assert os.environ.get("SQLANY_API_DLL") == str(target_dir / "lib64" / "libdbcapi_r.so")
