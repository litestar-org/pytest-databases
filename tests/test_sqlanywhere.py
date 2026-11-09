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
    _extract_container_archive,
    _is_sqlanywhere_ready,
    exec_dbisql,
    extract_sqlanywhere_client_libs,
    provide_sqlanywhere_service,
    sqlanywhere_client_environment,
    validate_sqlanywhere_database_name,
)

if TYPE_CHECKING:
    from pathlib import Path

    from pytest_databases.types import XdistIsolationLevel

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


def _run_provide_sqlanywhere(
    monkeypatch: pytest.MonkeyPatch, worker_num: int | None, isolation: XdistIsolationLevel
) -> tuple[MagicMock, SimpleNamespace]:
    """Enter ``provide_sqlanywhere_service`` with a mocked container service and return the run mock."""
    fake_container = MagicMock()
    fake_container.exec_run.return_value = SimpleNamespace(exit_code=0, output=b"4242\n")
    fake_service = SimpleNamespace(host="127.0.0.1", port=2638, container=fake_container)
    run_ctx = MagicMock()
    run_ctx.__enter__.return_value = fake_service
    run_ctx.__exit__.return_value = False
    container_service = MagicMock()
    container_service.run.return_value = run_ctx
    monkeypatch.setattr(sqlanywhere_mod, "tcp_port_open", lambda *_args, **_kwargs: True)
    monkeypatch.setattr(sqlanywhere_mod, "get_xdist_worker_num", lambda: worker_num)

    with provide_sqlanywhere_service(
        container_service=container_service,
        sqlanywhere_image=DEFAULT_SQLANYWHERE_IMAGE,
        sqlanywhere_user=SQLANYWHERE_USER,
        sqlanywhere_password=SQLANYWHERE_PASSWORD,
        sqlanywhere_database=SQLANYWHERE_DATABASE,
        sqlanywhere_server=SQLANYWHERE_SERVER,
        sqlanywhere_startup_timeout=30,
        xdist_sqlanywhere_isolation_level=isolation,
    ) as service:
        assert (service.host, service.port, service.user) == ("127.0.0.1", 2638, "dba")
        assert (service.database, service.server_name) == ("demo", "demo")
    return container_service, fake_service


@pytest.mark.parametrize(
    ("worker_num", "name", "transient"),
    [(None, "sqlanywhere", False), (0, "sqlanywhere_0", True), (3, "sqlanywhere_3", True)],
)
def test_provide_sqlanywhere_service_lifecycle(
    monkeypatch: pytest.MonkeyPatch, worker_num: int | None, name: str, transient: bool
) -> None:
    """Verify container naming, transience, and the readiness check under server isolation."""
    container_service, fake_service = _run_provide_sqlanywhere(monkeypatch, worker_num, "server")

    kwargs = container_service.run.call_args.kwargs
    assert kwargs["container_port"] == 2638
    assert kwargs["name"] == name
    assert kwargs["transient"] is transient

    check_fn = kwargs["check"]
    assert check_fn(fake_service) is True
    script = fake_service.container.exec_run.call_args.args[0][2]
    assert "SELECT 4242 AS probe; OUTPUT TO /dev/stdout;" in script
    fake_service.container.exec_run.return_value = SimpleNamespace(
        exit_code=1, output=b"Error at line 1\nTable 'nosuch' not found\n"
    )
    assert check_fn(fake_service) is False
    monkeypatch.setattr(sqlanywhere_mod, "tcp_port_open", lambda *_args, **_kwargs: False)
    assert check_fn(fake_service) is False


@pytest.mark.parametrize("worker_num", [None, 1])
def test_provide_sqlanywhere_service_rejects_database_isolation(
    monkeypatch: pytest.MonkeyPatch, worker_num: int | None
) -> None:
    """Verify ``database`` isolation is rejected because workers cannot get their own database."""
    with pytest.raises(ValueError, match="supports only 'server' xdist isolation"):
        _run_provide_sqlanywhere(monkeypatch, worker_num, "database")


@pytest.mark.parametrize(
    ("exit_code", "output", "ready"),
    [
        (0, b"4242\n", True),
        (0, b"", False),
        (0, b"14242\n", False),
        (1, b"Error at line 1\nSQLCODE=-100\n", False),
        (4, b"Error at line 1\nSpecified database not found\n", False),
    ],
)
def test_sqlanywhere_readiness_requires_exact_row(exit_code: int, output: bytes, ready: bool) -> None:
    """Verify readiness needs a zero exit code and an output line that is exactly the probe value."""
    assert _is_sqlanywhere_ready(exit_code, output) is ready


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
    """Verify preloading loads the extracted libraries and leaves the process environment untouched."""
    fake_container = MagicMock()
    fake_container.exec_run.return_value = SimpleNamespace(exit_code=0, output=b"")

    lib_archive = _make_tar_bytes({"lib64/libdbcapi_r.so": b"fake_so", "lib64/libdbtasks16_r.so": b"fake_tasks"})
    fake_container.get_archive.side_effect = lambda path: ([lib_archive], {}) if "lib64" in path else ([], {})

    mock_cdll = MagicMock()
    monkeypatch.setattr("ctypes.CDLL", mock_cdll)
    monkeypatch.delenv("SQLANY16", raising=False)
    monkeypatch.delenv("SQLANY_API_DLL", raising=False)
    environment_before = dict(os.environ)

    target_dir = tmp_path / "sqlany_preload"
    res = extract_sqlanywhere_client_libs(fake_container, target_dir, preload=True)

    assert res == target_dir
    assert dict(os.environ) == environment_before
    loaded = [call.args[0] for call in mock_cdll.call_args_list]
    assert loaded == [str(target_dir / "lib64" / "libdbtasks16_r.so"), str(target_dir / "lib64" / "libdbcapi_r.so")]
    assert sqlanywhere_client_environment(target_dir) == {
        "SQLANY16": str(target_dir),
        "SQLANY_API_DLL": str(target_dir / "lib64" / "libdbcapi_r.so"),
    }


def test_sqlanywhere_client_environment_without_dbcapi(tmp_path: Path) -> None:
    """Verify only ``SQLANY16`` is returned when no ``dbcapi`` library was extracted."""
    assert sqlanywhere_client_environment(tmp_path) == {"SQLANY16": str(tmp_path)}


def test_sqlanywhere_client_libs_fixture_restores_environment(
    pytester: pytest.Pytester, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Verify the fixture sets ``SQLANY16``/``SQLANY_API_DLL`` for the session and restores them afterwards."""
    pytester.makeconftest("""
    import os
    from types import SimpleNamespace
    from unittest.mock import MagicMock

    import pytest

    pytest_plugins = ["pytest_databases.docker.sqlanywhere"]


    @pytest.fixture(scope="session")
    def sqlanywhere_service():
        container = MagicMock()
        container.exec_run.return_value = SimpleNamespace(exit_code=1, output=b"")
        container.get_archive.return_value = ([], {})
        return SimpleNamespace(container=container)


    def pytest_sessionfinish(session):
        assert os.environ.get("SQLANY16") == "before"
        assert "SQLANY_API_DLL" not in os.environ
    """)
    pytester.makepyfile("""
    import os


    def test_env(sqlanywhere_client_libs):
        assert os.environ["SQLANY16"] == str(sqlanywhere_client_libs)
    """)
    monkeypatch.setenv("SQLANY16", "before")
    monkeypatch.delenv("SQLANY_API_DLL", raising=False)
    result = pytester.runpytest_subprocess("-p", "pytest_databases", "-p", "no:xdist")
    result.assert_outcomes(passed=1)


@pytest.mark.parametrize("member_name", ["../escape.txt", "../sqlany_client2/escape.txt"])
def test_extract_container_archive_skips_members_outside_target(tmp_path: Path, member_name: str) -> None:
    """Verify archive members resolving outside the target, including sibling-prefix paths, are skipped."""
    fake_container = MagicMock()
    fake_container.get_archive.return_value = ([_make_tar_bytes({member_name: b"x", "lib64/ok.so": b"ok"})], {})
    target_dir = tmp_path / "sqlany_client"
    target_dir.mkdir()

    _extract_container_archive(fake_container, "/opt/sqlanywhere16/lib64", target_dir)

    assert (target_dir / "lib64" / "ok.so").read_bytes() == b"ok"
    assert not (tmp_path / "escape.txt").exists()
    assert not (tmp_path / "sqlany_client2" / "escape.txt").exists()


def test_sqlanywhere_service_live(pytester: pytest.Pytester) -> None:
    """Start SQL Anywhere for two xdist workers and run SQL in each worker's own container."""
    pytester.makepyfile("""
    from pytest_databases.docker.sqlanywhere import SQLAnywhereService
    from pytest_databases.helpers import get_xdist_worker_num

    pytest_plugins = ["pytest_databases.docker.sqlanywhere"]


    def _assert_worker_container(sqlanywhere_service: SQLAnywhereService) -> None:
        assert f"_sqlanywhere_{get_xdist_worker_num()}_" in sqlanywhere_service.container.name
        code, output = sqlanywhere_service.exec_sql("SELECT 6 * 7; OUTPUT TO /dev/stdout")
        assert code == 0, output
        assert output.decode().split() == ["42"]
        code, output = sqlanywhere_service.exec_sql("SELECT * FROM missing_table")
        assert code != 0
        assert b"Table 'missing_table' not found" in output


    def test_one(sqlanywhere_service: SQLAnywhereService) -> None:
        _assert_worker_container(sqlanywhere_service)


    def test_two(sqlanywhere_service: SQLAnywhereService) -> None:
        _assert_worker_container(sqlanywhere_service)
    """)
    result = pytester.runpytest_subprocess("-p", "pytest_databases", "-n", "2", timeout=600)
    result.assert_outcomes(passed=2)


def test_sqlanywhere_all_fixtures_inprocess(pytester: pytest.Pytester) -> None:
    """Verify SQL Anywhere config and service fixtures execute in-process with mocked provider."""
    pytester.makepyfile("""
    from contextlib import contextmanager
    from pathlib import Path
    from unittest.mock import MagicMock, patch
    import pytest

    pytest_plugins = ["pytest_databases.docker.sqlanywhere"]

    @pytest.fixture(scope="session")
    def container_service() -> MagicMock:
        return MagicMock()

    def test_fixtures(request: pytest.FixtureRequest, tmp_path: Path) -> None:
        mock_svc = MagicMock()
        mock_svc.container = MagicMock()

        @contextmanager
        def fake_svc(*args, **kwargs):
            yield mock_svc

        with (
            patch("pytest_databases.docker.sqlanywhere.provide_sqlanywhere_service", side_effect=fake_svc),
            patch("pytest_databases.docker.sqlanywhere.extract_sqlanywhere_client_libs", return_value=tmp_path),
            patch("pytest_databases.docker.sqlanywhere.sqlanywhere_client_environment", return_value={"SQLANY16": str(tmp_path)}),
        ):
            assert request.getfixturevalue("sqlanywhere_image")
            assert request.getfixturevalue("sqlanywhere_user") == "dba"
            assert request.getfixturevalue("sqlanywhere_password") == "sql"
            assert request.getfixturevalue("sqlanywhere_database") == "demo"
            assert request.getfixturevalue("sqlanywhere_startup_timeout") == 60
            assert request.getfixturevalue("xdist_sqlanywhere_isolation_level") == "server"
            assert request.getfixturevalue("sqlanywhere_service") is mock_svc
            assert request.getfixturevalue("sqlanywhere_client_libs") == tmp_path
    """)
    result = pytester.runpytest("-p", "no:sugar", "-p", "pytest_databases")
    result.assert_outcomes(passed=1)
