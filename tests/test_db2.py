"""Tests for IBM Db2 Community Edition container service fixtures and CLI helpers."""

from __future__ import annotations

import re
import shlex
from contextlib import contextmanager
from typing import TYPE_CHECKING
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
from pytest_databases.types import ServiceContainer, XdistIsolationLevel

if TYPE_CHECKING:
    from collections.abc import Generator

    from pytest import MonkeyPatch

_DB2_SET_DBM_CFG_LINE = (
    '  su - ${DB2INSTANCE?} -c ". sqllib/db2profile; db2set DB2COMM=TCPIP && '
    'db2 UPDATE DBM CFG USING DFTDBPATH $DATA_DIR IMMEDIATE"\n'
)


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


@pytest.mark.parametrize(
    ("worker_num", "isolation_level", "expected_name", "expected_transient"),
    [
        (None, "server", "db2", False),
        (2, "database", "db2", False),
        (2, "server", "db2_2", True),
    ],
)
def test_db2_service_runtime_options(
    monkeypatch: MonkeyPatch,
    worker_num: int | None,
    isolation_level: XdistIsolationLevel,
    expected_name: str,
    expected_transient: bool,
) -> None:
    """Verify the container is privileged without host IPC, and the naming and transient rule per isolation level."""
    captured_kwargs: dict[str, object] = {}
    mock_container = MagicMock()
    mock_container.exec_run.return_value = MagicMock(exit_code=0, output=b"          1\n")

    @contextmanager
    def fake_run(**kwargs: object) -> Generator[ServiceContainer, None, None]:
        captured_kwargs.update(kwargs)
        svc = ServiceContainer(container=mock_container, host="127.0.0.1", port=50000)
        check_fn = kwargs["check"]
        assert callable(check_fn)
        assert check_fn(svc) is True
        yield svc

    container_service = MagicMock()
    container_service.run.side_effect = fake_run
    monkeypatch.setattr(db2, "get_xdist_worker_num", lambda: worker_num)
    db_name = "ptdb_2" if isolation_level == "database" and worker_num is not None else "pytestdb"
    with db2.provide_db2_service(
        container_service=container_service,
        db2_image=DEFAULT_DB2_IMAGE,
        db2_dbname=db_name,
        db2_username="db2inst1",
        db2_password="pytest_db2_pwd",
        db2_startup_timeout=600,
        xdist_db2_isolation_level=isolation_level,
    ) as service:
        assert service.db_name == db_name
    assert captured_kwargs["privileged"] is True
    assert "ipc_mode" not in captured_kwargs
    assert captured_kwargs["wait_for_log"] == "Setup has completed"
    assert captured_kwargs["name"] == expected_name
    assert captured_kwargs["transient"] is expected_transient


@pytest.mark.parametrize("enable_4k_device_support", [True, False])
def test_db2_service_4k_device_support_setup_command(monkeypatch: MonkeyPatch, enable_4k_device_support: bool) -> None:
    """Verify the setup script is patched to set the 4K registry variables before ``db2start`` only when enabled."""
    captured_kwargs: dict[str, object] = {}
    mock_container = MagicMock()
    mock_container.exec_run.return_value = MagicMock(exit_code=0, output=b"1\n")

    @contextmanager
    def fake_run(**kwargs: object) -> Generator[ServiceContainer, None, None]:
        captured_kwargs.update(kwargs)
        yield ServiceContainer(container=mock_container, host="127.0.0.1", port=50000)

    container_service = MagicMock()
    container_service.run.side_effect = fake_run
    monkeypatch.setattr(db2, "get_xdist_worker_num", lambda: None)
    with db2.provide_db2_service(
        container_service=container_service,
        db2_image=DEFAULT_DB2_IMAGE,
        db2_dbname="pytestdb",
        db2_username="db2inst1",
        db2_password="pytest_db2_pwd",
        db2_startup_timeout=600,
        xdist_db2_isolation_level="database",
        enable_4k_device_support=enable_4k_device_support,
    ):
        pass

    if not enable_4k_device_support:
        assert captured_kwargs["entrypoint"] is None
        assert captured_kwargs["command"] is None
        return
    assert captured_kwargs["entrypoint"] == ["/bin/bash", "-c"]
    command = captured_kwargs["command"]
    assert isinstance(command, list)
    assert len(command) == 1
    sed_part, exec_part = command[0].split(" && exec ", 1)
    assert exec_part == "/var/db2_setup/lib/setup_db2_instance.sh"
    sed_args = shlex.split(sed_part)
    assert sed_args[:2] == ["sed", "-i"]
    assert sed_args[3] == "/var/db2_setup/include/db2_common_functions"
    _, pattern, replacement, _ = sed_args[2].split("/")
    patched = _DB2_SET_DBM_CFG_LINE.replace(pattern, replacement.replace(r"\&", "&"))
    assert patched == _DB2_SET_DBM_CFG_LINE.replace(
        "db2set DB2COMM=TCPIP && ",
        "db2set DB2COMM=TCPIP && db2set DB2_4K_DEVICE_SUPPORT=ON && db2set DB2_DIRECT_IO=NO && ",
    )


@pytest.mark.parametrize(
    ("enable_4k_device_support", "first_error", "expect_recreate"),
    [
        (True, b"SQL1013N  The database alias name or database name PYTESTDB could not be found.", True),
        (True, b"SQL1032N  No start database manager command was issued.", False),
        (False, b"SQL1013N  The database alias name or database name PYTESTDB could not be found.", False),
    ],
)
def test_db2_service_recreates_missing_database_once(
    monkeypatch: MonkeyPatch, enable_4k_device_support: bool, first_error: bytes, expect_recreate: bool
) -> None:
    """Verify a database missing after setup is created once with the 4K registry settings and an instance restart."""
    scripts: list[str] = []
    responses = iter([MagicMock(exit_code=4, output=first_error), MagicMock(exit_code=4, output=first_error)])

    def exec_run(cmd: list[str]) -> MagicMock:
        scripts.append(cmd[4])
        if "db2stop force" in cmd[4]:
            return MagicMock(exit_code=0, output=b"DB20000I")
        return next(responses, MagicMock(exit_code=0, output=b"1\n"))

    mock_container = MagicMock()
    mock_container.exec_run.side_effect = exec_run

    @contextmanager
    def fake_run(**kwargs: object) -> Generator[ServiceContainer, None, None]:
        svc = ServiceContainer(container=mock_container, host="127.0.0.1", port=50000)
        check_fn = kwargs["check"]
        assert callable(check_fn)
        results = [check_fn(svc) for _ in range(3)]
        assert results == [False, False, True]
        yield svc

    container_service = MagicMock()
    container_service.run.side_effect = fake_run
    monkeypatch.setattr(db2, "get_xdist_worker_num", lambda: None)
    with db2.provide_db2_service(
        container_service=container_service,
        db2_image=DEFAULT_DB2_IMAGE,
        db2_dbname="pytestdb",
        db2_username="db2inst1",
        db2_password="pytest_db2_pwd",
        db2_startup_timeout=600,
        xdist_db2_isolation_level="database",
        enable_4k_device_support=enable_4k_device_support,
    ):
        pass

    recreate_scripts = [script for script in scripts if "db2stop force" in script]
    if not expect_recreate:
        assert recreate_scripts == []
        return
    assert len(recreate_scripts) == 1
    assert (
        "db2set DB2_4K_DEVICE_SUPPORT=ON && db2set DB2_DIRECT_IO=NO && db2stop force && db2start "
        "&& db2 create database pytestdb" in recreate_scripts[0]
    )


@pytest.mark.parametrize(("env_value", "expected"), [(None, True), ("off", False), ("0", False), ("on", True)])
def test_db2_4k_device_support_fixture(
    pytester: pytest.Pytester, monkeypatch: MonkeyPatch, env_value: str | None, expected: bool
) -> None:
    """Verify ``db2_4k_device_support`` is on by default and can be disabled through ``DB2_4K_DEVICE_SUPPORT``."""
    if env_value is None:
        monkeypatch.delenv("DB2_4K_DEVICE_SUPPORT", raising=False)
    else:
        monkeypatch.setenv("DB2_4K_DEVICE_SUPPORT", env_value)
    pytester.makepyfile(f"""
    pytest_plugins = ["pytest_databases.docker.db2"]

    def test_flag(db2_4k_device_support) -> None:
        assert db2_4k_device_support is {expected}
    """)
    result = pytester.runpytest_subprocess("-p", "pytest_databases")
    result.assert_outcomes(passed=1)


def test_db2_service_live_database_isolation(pytester: pytest.Pytester) -> None:
    """Start Db2 for two xdist workers and query each worker's own database through the in-container CLP."""
    pytester.makepyfile("""
    from pytest_databases.docker.db2 import Db2Service
    from pytest_databases.helpers import get_xdist_worker_num

    pytest_plugins = ["pytest_databases.docker.db2"]


    def _assert_worker_database(db2_service: Db2Service) -> None:
        assert db2_service.db_name == f"ptdb_{get_xdist_worker_num()}"
        assert db2_service.exec_sql("SELECT 1 FROM SYSIBM.SYSDUMMY1") == "1"
        assert db2_service.exec_sql("SELECT CURRENT SERVER FROM SYSIBM.SYSDUMMY1") == db2_service.db_name.upper()
        registry = db2_service.container.exec_run(["su", "-", db2_service.username, "-c", "db2set -all"]).output
        assert b"DB2_4K_DEVICE_SUPPORT=ON" in registry
        db2_service.exec_sql("CREATE TABLE t (id INTEGER)")
        db2_service.exec_sql("INSERT INTO t VALUES (42)")
        assert db2_service.exec_sql("SELECT id FROM t") == "42"


    def test_one(db2_service: Db2Service) -> None:
        _assert_worker_database(db2_service)


    def test_two(db2_service: Db2Service) -> None:
        _assert_worker_database(db2_service)
    """)
    result = pytester.runpytest_subprocess("-p", "pytest_databases", "-n", "2", timeout=1200)
    result.assert_outcomes(passed=2)


@pytest.mark.parametrize(
    ("exit_code", "output", "raises"),
    [
        (0, b"          1\n", False),
        (1, b"SQL0100W  No row was found for FETCH, UPDATE or DELETE.\n", False),
        (2, b"SQL0347W  The recursive common table expression may contain an infinite loop.\n", False),
        (4, b'SQL0204N  "DB2INST1.MISSING" is an undefined name.\n', True),
        (8, b"DB21034E  The command was processed as an SQL statement.\n", True),
    ],
)
def test_exec_db2_sql_clp_exit_codes(exit_code: int, output: bytes, raises: bool) -> None:
    """Verify CLP exit codes 0-2 succeed with their message text returned and codes of 4 or more raise."""
    container = MagicMock()
    container.exec_run.return_value = MagicMock(exit_code=exit_code, output=output)
    if raises:
        with pytest.raises(RuntimeError, match=f"exit {exit_code}"):
            exec_db2_sql(container, "SELECT * FROM missing", db_name="pytestdb")
    else:
        assert exec_db2_sql(container, "SELECT * FROM missing", db_name="pytestdb") == output.decode().strip()
    script = container.exec_run.call_args.args[0][4]
    assert "db2 connect reset" in script
    assert 'exit "$rc"' in script


@pytest.mark.parametrize(
    ("directory_listing", "expect_create"),
    [
        (" Database name                        = PTDB_10\n", True),
        (" Database name                        = PTDB_1\n", False),
        (" Database alias                       = PTDB_1\n", True),
    ],
)
def test_create_worker_database_matches_exact_name(directory_listing: str, expect_create: bool) -> None:
    """Verify the database directory match is anchored, so ``PTDB_1`` is not found inside ``PTDB_10``."""
    container = MagicMock()
    container.exec_run.return_value = MagicMock(exit_code=0, output=b"")
    create_worker_database(container, "ptdb_1")
    script = container.exec_run.call_args.args[0][4]
    grep_pattern = script.split("grep -Eiq ", 1)[1].split(" || ", 1)[0].strip("'")
    found = any(
        re.search(grep_pattern.replace("[[:space:]]", r"\s"), line, re.IGNORECASE)
        for line in directory_listing.splitlines()
    )
    assert found is not expect_create
