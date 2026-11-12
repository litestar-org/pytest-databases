"""Tests for IBM Db2 Community Edition container service fixtures and CLI helpers."""

from __future__ import annotations

import re
import shlex
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from contextlib import contextmanager
from typing import TYPE_CHECKING, Any, cast
from unittest.mock import MagicMock

import pytest

from pytest_databases._service import ContainerService
from pytest_databases.docker import db2
from pytest_databases.docker.db2 import (
    DEFAULT_DB2_IMAGE,
    DEFAULT_DB2_IPC_MODE,
    Db2Service,
    activate_db2_database,
    create_worker_database,
    exec_db2_sql,
    validate_db2_database_name,
)
from pytest_databases.types import ServiceContainer, XdistIsolationLevel

if TYPE_CHECKING:
    from collections.abc import Generator
    from pathlib import Path

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
    """Verify default values of Db2 session configuration fixtures."""
    for var in (
        "PYTEST_XDIST_WORKER",
        "DB2_IMAGE",
        "DB2_DBNAME",
        "DB2_USER",
        "DB2_PASSWORD",
        "DB2_PORT",
        "DB2_IPC_MODE",
        "DB2_ACTIVATE_DATABASE",
    ):
        monkeypatch.delenv(var, raising=False)

    pytester.makepyfile(f"""
    pytest_plugins = ["pytest_databases.docker.db2"]

    def test_contract(
        db2_image,
        db2_dbname,
        db2_username,
        db2_password,
        db2_startup_timeout,
        db2_activate_database,
        db2_port,
        db2_ipc_mode,
        db2_volumes,
        xdist_db2_isolation_level,
    ) -> None:
        assert db2_image == {DEFAULT_DB2_IMAGE!r}
        assert db2_dbname == "pytestdb"
        assert db2_username == "db2inst1"
        assert db2_password == "pytest_db2_pwd"
        assert db2_startup_timeout == 600
        assert db2_activate_database is True
        assert db2_port is None
        assert db2_ipc_mode == {DEFAULT_DB2_IPC_MODE!r}
        assert db2_volumes is None
        assert xdist_db2_isolation_level == "database"
    """)

    result = pytester.runpytest_subprocess("-p", "pytest_databases", "-vv")
    result.assert_outcomes(passed=1)


@pytest.mark.parametrize(
    ("env_value", "expected_ipc"),
    [(None, "host"), ("", None), ("shareable", "shareable")],
)
def test_db2_ipc_mode_fixture_env_overrides(
    pytester: pytest.Pytester,
    monkeypatch: MonkeyPatch,
    env_value: str | None,
    expected_ipc: str | None,
) -> None:
    """Verify db2_ipc_mode honors DB2_IPC_MODE and maps empty strings to None."""
    if env_value is None:
        monkeypatch.delenv("DB2_IPC_MODE", raising=False)
    else:
        monkeypatch.setenv("DB2_IPC_MODE", env_value)
    pytester.makepyfile(f"""
    pytest_plugins = ["pytest_databases.docker.db2"]

    def test_ipc(db2_ipc_mode) -> None:
        assert db2_ipc_mode == {expected_ipc!r}
    """)
    result = pytester.runpytest_subprocess("-p", "pytest_databases", "-vv")
    result.assert_outcomes(passed=1)


@pytest.mark.parametrize(
    ("worker_num", "isolation_level", "expected_name", "expected_transient", "ipc_mode", "volumes"),
    [
        (None, "server", "db2", False, DEFAULT_DB2_IPC_MODE, None),
        (2, "database", "db2", False, None, {"/host/db2": {"bind": "/database", "mode": "rw"}}),
        (2, "server", "db2_2", True, "shareable", ["db2data:/database"]),
    ],
)
def test_db2_service_runtime_options(
    monkeypatch: MonkeyPatch,
    worker_num: int | None,
    isolation_level: XdistIsolationLevel,
    expected_name: str,
    expected_transient: bool,
    ipc_mode: str | None,
    volumes: dict[str, dict[str, str]] | list[str] | None,
) -> None:
    """Verify privileged mode, IPC/volume forwarding, and container naming/transient options."""
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
    monkeypatch.setattr(db2, "tcp_port_open", lambda *_args, **_kwargs: True)
    db_name = "ptdb_2" if isolation_level == "database" and worker_num is not None else "pytestdb"
    with db2.provide_db2_service(
        container_service=container_service,
        db2_image=DEFAULT_DB2_IMAGE,
        db2_dbname=db_name,
        db2_username="db2inst1",
        db2_password="pytest_db2_pwd",
        db2_startup_timeout=600,
        xdist_db2_isolation_level=isolation_level,
        ipc_mode=ipc_mode,
        volumes=volumes,
    ) as service:
        assert service.db_name == db_name
    assert captured_kwargs["privileged"] is True
    if ipc_mode:
        assert captured_kwargs["ipc_mode"] == ipc_mode
    else:
        assert "ipc_mode" not in captured_kwargs
    if volumes is not None:
        assert captured_kwargs["volumes"] == volumes
    else:
        assert "volumes" not in captured_kwargs
    assert captured_kwargs["wait_for_log"] == "Setup has completed"
    assert captured_kwargs["name"] == expected_name
    assert captured_kwargs["transient"] is expected_transient

    check_fn = captured_kwargs["check"]
    assert callable(check_fn)
    monkeypatch.setattr(db2, "tcp_port_open", lambda *_args, **_kwargs: False)
    assert check_fn(ServiceContainer(container=mock_container, host="127.0.0.1", port=50000)) is False


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
    monkeypatch.setattr(db2, "tcp_port_open", lambda *_args, **_kwargs: True)
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
        (True, b"SQL0293N  Error accessing a table space container.", True),
        (True, b'SQL0204N  "SYSIBM.SYSDUMMY1" is an undefined name. SQLSTATE=42705', True),
        (True, b"SQL1032N  No start database manager command was issued.", False),
        (False, b"SQL1013N  The database alias name or database name PYTESTDB could not be found.", False),
    ],
)
def test_db2_service_recreates_missing_database_once(
    monkeypatch: MonkeyPatch, enable_4k_device_support: bool, first_error: bytes, expect_recreate: bool
) -> None:
    """Verify a database missing after setup is created once with the 4K registry settings and an instance restart."""
    scripts: list[str] = []
    error_count = 3 if expect_recreate and enable_4k_device_support else 2
    responses = iter([MagicMock(exit_code=4, output=first_error) for _ in range(error_count)])

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
    monkeypatch.setattr(db2, "tcp_port_open", lambda *_args, **_kwargs: True)
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
    assert "flock -w 300 9" in recreate_scripts[0]
    assert f"/{'tmp'}/pytest_databases_db2_init.lock" in recreate_scripts[0]
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
    assert "flock -w 300 9" in script
    assert f"/{'tmp'}/pytest_databases_db2_init.lock" in script
    grep_pattern = script.split("grep -Eiq ", 1)[1].split(" || ", 1)[0].strip("'")
    found = any(
        re.search(grep_pattern.replace("[[:space:]]", r"\s"), line, re.IGNORECASE)
        for line in directory_listing.splitlines()
    )
    assert found is not expect_create


def test_db2_all_fixtures_inprocess(pytester: pytest.Pytester) -> None:
    """Verify Db2 config and service fixtures execute in-process with mocked provider."""
    pytester.makepyfile("""
    from contextlib import contextmanager
    from unittest.mock import MagicMock, patch
    import pytest
    from pytest_databases.docker.db2 import db2_dbname

    pytest_plugins = ["pytest_databases.docker.db2"]

    @pytest.fixture(scope="session")
    def container_service() -> MagicMock:
        return MagicMock()

    def test_fixtures(request: pytest.FixtureRequest) -> None:
        mock_svc = MagicMock()

        @contextmanager
        def fake_svc(*args, **kwargs):
            yield mock_svc

        with patch("pytest_databases.docker.db2.provide_db2_service", side_effect=fake_svc):
            assert request.getfixturevalue("xdist_db2_isolation_level") == "database"
            assert request.getfixturevalue("db2_4k_device_support") is True
            assert request.getfixturevalue("db2_activate_database") is True
            assert request.getfixturevalue("db2_port") is None
            assert request.getfixturevalue("db2_ipc_mode") == "host"
            assert request.getfixturevalue("db2_volumes") is None
            assert request.getfixturevalue("db2_image")
            assert request.getfixturevalue("db2_username") == "db2inst1"
            assert request.getfixturevalue("db2_password") == "pytest_db2_pwd"
            assert request.getfixturevalue("db2_dbname") == "pytestdb"
            assert request.getfixturevalue("db2_startup_timeout") == 600
            assert request.getfixturevalue("db2_service") is mock_svc

        with patch("pytest_databases.docker.db2.get_xdist_worker_num", return_value=1):
            fn = getattr(db2_dbname, "__wrapped__", db2_dbname)
            assert fn("database") == "ptdb_1"
    """)
    result = pytester.runpytest("-p", "no:sugar", "-p", "pytest_databases")
    result.assert_outcomes(passed=1)


@pytest.mark.parametrize(
    ("exit_code", "output", "expect_error"),
    [
        (0, b"DB20000I  The ACTIVATE DATABASE command completed successfully.\n", False),
        (2, b"SQL1490W  Activate database is successful, however, there is already a connection.\n", False),
        (4, b"SQL1490W  Database is already active.\n", False),
        (4, b"SQL1013N  The database alias name or database name could not be found.\n", True),
        (None, b"", True),
    ],
)
def test_activate_db2_database_exit_codes(exit_code: int | None, output: bytes, expect_error: bool) -> None:
    """Verify activate_db2_database accepts idempotent SQL1490W warnings and raises on CLP errors."""
    container = MagicMock()
    container.exec_run.return_value = MagicMock(exit_code=exit_code, output=output)
    svc = Db2Service(
        container=container,
        host="127.0.0.1",
        port=50000,
        db_name="pytestdb",
        username="db2inst1",
        password="pw",
    )
    if expect_error:
        with pytest.raises(RuntimeError, match="Failed to activate Db2 database"):
            activate_db2_database(container, "pytestdb")
        return
    result = svc.activate_database()
    assert result == output.decode().strip()
    assert "db2 activate database pytestdb" in container.exec_run.call_args.args[0][4]


def test_provide_db2_service_registry_vars_resources_and_init_sql(
    monkeypatch: MonkeyPatch,
    tmp_path: Path,
) -> None:
    """Verify provide_db2_service wires registry_vars, resources, platform, activation toggle, and init_sql."""
    monkeypatch.setattr(db2, "get_xdist_worker_num", lambda: None)
    monkeypatch.setattr(db2, "tcp_port_open", lambda *_args, **_kwargs: True)
    monkeypatch.setenv("TMPDIR", str(tmp_path))
    monkeypatch.setattr(db2.tempfile, "tempdir", str(tmp_path))

    executed_scripts: list[str] = []
    mock_container = MagicMock()
    mock_container.id = "db2cid987654321"

    def _exec(cmd: list[str]) -> MagicMock:
        executed_scripts.append(cmd[4])
        return MagicMock(exit_code=0, output=b"1\n")

    mock_container.exec_run.side_effect = _exec
    captured_kwargs: dict[str, object] = {}

    @contextmanager
    def fake_run(**kwargs: object) -> Generator[ServiceContainer, None, None]:
        captured_kwargs.update(kwargs)
        yield ServiceContainer(container=mock_container, host="127.0.0.1", port=50123)

    cs = MagicMock()
    cs.temp_dir = tmp_path
    cs.run.side_effect = fake_run

    sql_path = tmp_path / "seed.sql"
    sql_path.write_text("CREATE TABLE seed_t (id INT)", encoding="utf-8")

    with db2.provide_db2_service(
        container_service=cs,
        db2_image=DEFAULT_DB2_IMAGE,
        db2_dbname="pytestdb",
        db2_username="db2inst1",
        db2_password="pw",
        db2_startup_timeout=300,
        xdist_db2_isolation_level="database",
        enable_4k_device_support=False,
        activate_database=True,
        host_port=50123,
        env={"ARCHIVE_LOGS": "true", "CUSTOM_FLAG": "yes"},
        registry_vars={"DB2_COMPATIBILITY_VECTOR": "ORA", "DB2_DEFERRED_PREPARE_SEMANTICS": "YES"},
        shm_size="1g",
        mem_limit="4g",
        platform="linux/amd64",
        init_sql=[sql_path, "INSERT INTO seed_t VALUES (1)"],
    ) as svc:
        assert svc.port == 50123

    assert captured_kwargs["host_port"] == 50123
    assert captured_kwargs["shm_size"] == "1g"
    assert captured_kwargs["mem_limit"] == "4g"
    assert captured_kwargs["platform"] == "linux/amd64"
    env_dict = captured_kwargs["env"]
    assert isinstance(env_dict, dict)
    assert env_dict["ARCHIVE_LOGS"] == "true"
    assert env_dict["CUSTOM_FLAG"] == "yes"
    cmd_list = captured_kwargs["command"]
    assert isinstance(cmd_list, list)
    assert "DB2_COMPATIBILITY_VECTOR=ORA" in cmd_list[0]
    assert "DB2_4K_DEVICE_SUPPORT" not in cmd_list[0]
    assert any("db2 activate database pytestdb" in s for s in executed_scripts)
    assert sum("CREATE TABLE seed_t" in s for s in executed_scripts) == 1

    with db2.provide_db2_service(
        container_service=cs,
        db2_image=DEFAULT_DB2_IMAGE,
        db2_dbname="pytestdb",
        db2_username="db2inst1",
        db2_password="pw",
        db2_startup_timeout=300,
        xdist_db2_isolation_level="database",
        enable_4k_device_support=False,
        activate_database=False,
        init_sql=[sql_path, "INSERT INTO seed_t VALUES (1)"],
    ):
        pass
    assert sum("CREATE TABLE seed_t" in s for s in executed_scripts) == 1


@pytest.mark.parametrize(
    "bad_registry",
    [
        {"1BAD": "ON"},
        {"BAD-KEY": "ON"},
        {"DB2_WORKLOAD": ""},
        {"DB2_WORKLOAD": "ANALYTICS;id"},
    ],
)
def test_provide_db2_service_rejects_invalid_registry_vars(
    monkeypatch: MonkeyPatch,
    bad_registry: dict[str, str],
) -> None:
    """Verify provide_db2_service rejects unsafe or malformed Db2 registry variable names and values."""
    monkeypatch.setattr(db2, "get_xdist_worker_num", lambda: None)
    cs = MagicMock()
    with (
        pytest.raises(ValueError, match="Invalid Db2 registry variable"),
        db2.provide_db2_service(
            container_service=cs,
            db2_image=DEFAULT_DB2_IMAGE,
            db2_dbname="pytestdb",
            db2_username="db2inst1",
            db2_password="pw",
            db2_startup_timeout=60,
            xdist_db2_isolation_level="database",
            registry_vars=bad_registry,
        ),
    ):
        pass
    cs.run.assert_not_called()


def test_db2_4k_fallback_skips_restart_when_peer_worker_recovers(
    monkeypatch: MonkeyPatch,
    tmp_path: Path,
) -> None:
    """Verify peer worker re-probes inside FileLock and skips duplicate db2stop force recovery."""
    monkeypatch.setattr(db2, "get_xdist_worker_num", lambda: None)
    monkeypatch.setattr(db2, "tcp_port_open", lambda *_args, **_kwargs: True)

    mock_session = MagicMock()
    mock_session.config.rootpath = tmp_path
    container_service = ContainerService(cast("Any", MagicMock()), tmp_path, mock_session, owner_id="db2owner1234")

    mock_container = MagicMock()
    mock_container.id = "db2cid01"
    state_lock = threading.Lock()
    recreated = False
    recreate_count = 0

    def _exec_run(cmd: list[str]) -> MagicMock:
        nonlocal recreated, recreate_count
        script = cmd[4]
        if "db2stop force" in script:
            time.sleep(0.03)
            with state_lock:
                recreated = True
                recreate_count += 1
            return MagicMock(exit_code=0, output=b"DB20000I")
        with state_lock:
            is_ready = recreated
        if is_ready:
            return MagicMock(exit_code=0, output=b"1\n")
        return MagicMock(exit_code=4, output=b"SQL0204N  SQLSTATE=42705")

    mock_container.exec_run.side_effect = _exec_run
    captured_checks: list[object] = []

    @contextmanager
    def _fake_run(**kwargs: object) -> Generator[ServiceContainer, None, None]:
        captured_checks.append(kwargs["check"])
        yield ServiceContainer(container=mock_container, host="127.0.0.1", port=50000)

    monkeypatch.setattr(container_service, "run", _fake_run)
    for _ in range(2):
        with db2.provide_db2_service(
            container_service=container_service,
            db2_image=DEFAULT_DB2_IMAGE,
            db2_dbname="pytestdb",
            db2_username="db2inst1",
            db2_password="pw",
            db2_startup_timeout=300,
            xdist_db2_isolation_level="database",
            activate_database=False,
        ):
            pass

    svc = ServiceContainer(container=mock_container, host="127.0.0.1", port=50000)
    results: list[bool] = []
    results_lock = threading.Lock()
    barrier = threading.Barrier(2)

    def _invoke(check_fn: object) -> None:
        assert callable(check_fn)
        barrier.wait(timeout=5)
        outcome = bool(check_fn(svc))
        with results_lock:
            results.append(outcome)

    threads = [threading.Thread(target=_invoke, args=(fn,)) for fn in captured_checks]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()

    assert recreate_count == 1
    assert sorted(results) == [False, True]
    assert (tmp_path / "db2cid01_db2_init.lock").is_file()


def test_db2_create_worker_database_serializes_concurrent_workers(
    monkeypatch: MonkeyPatch,
    tmp_path: Path,
) -> None:
    """Verify Db2Service.create_worker_database and xdist finalization serialize catalog writes via FileLock."""
    monkeypatch.setattr(db2, "get_xdist_worker_num", lambda: None)
    monkeypatch.setattr(db2, "tcp_port_open", lambda *_args, **_kwargs: True)

    mock_session = MagicMock()
    mock_session.config.rootpath = tmp_path
    container_service = ContainerService(cast("Any", MagicMock()), tmp_path, mock_session, owner_id="db2owner5678")

    mock_container = MagicMock()
    mock_container.id = "db2cid02"
    state_lock = threading.Lock()
    active_creates = 0
    max_active_creates = 0

    def _exec_run(cmd: list[str]) -> MagicMock:
        nonlocal active_creates, max_active_creates
        script = cmd[4]
        if "db2 create database" in script:
            with state_lock:
                active_creates += 1
                max_active_creates = max(max_active_creates, active_creates)
            try:
                time.sleep(0.03)
            finally:
                with state_lock:
                    active_creates -= 1
            return MagicMock(exit_code=0, output=b"DB20000I")
        return MagicMock(exit_code=0, output=b"1\n")

    mock_container.exec_run.side_effect = _exec_run

    @contextmanager
    def _fake_run(**_kwargs: object) -> Generator[ServiceContainer, None, None]:
        yield ServiceContainer(container=mock_container, host="127.0.0.1", port=50000)

    monkeypatch.setattr(container_service, "run", _fake_run)

    with (
        db2.provide_db2_service(
            container_service=container_service,
            db2_image=DEFAULT_DB2_IMAGE,
            db2_dbname="pytestdb",
            db2_username="db2inst1",
            db2_password="pw",
            db2_startup_timeout=300,
            xdist_db2_isolation_level="database",
        ) as svc,
        ThreadPoolExecutor(max_workers=3) as pool,
    ):
        futures = [pool.submit(svc.create_worker_database, f"ptdb_{idx}") for idx in range(3)]
        for future in futures:
            future.result()

    assert max_active_creates == 1
    assert (tmp_path / "db2cid02_db2_init.lock").is_file()

    monkeypatch.setattr(db2, "get_xdist_worker_num", lambda: 1)
    with db2.provide_db2_service(
        container_service=container_service,
        db2_image=DEFAULT_DB2_IMAGE,
        db2_dbname="ptdb_1",
        db2_username="db2inst1",
        db2_password="pw",
        db2_startup_timeout=300,
        xdist_db2_isolation_level="database",
    ) as worker_svc:
        assert worker_svc.db_name == "ptdb_1"


@pytest.mark.parametrize(
    ("clp_output", "container_logs", "expected_marker"),
    [
        (b"SQL1042C  An unexpected system error occurred.\n", b"", "SQL1042C"),
        (b"SQL5005C  System Error. SQLSTATE=57019\n", b"", "57019"),
        (
            b"SQL1032N  No start database manager command was issued.\n",
            b"ADM0503C  Instance stopped SQL1042C\n",
            "SQL1042C",
        ),
    ],
)
def test_db2_check_fails_fast_on_fatal_startup_errors(
    monkeypatch: MonkeyPatch,
    clp_output: bytes,
    container_logs: bytes,
    expected_marker: str,
) -> None:
    """Verify check() re-raises fatal SQL1042C/57019 failures immediately without attempting 4Kn restart."""
    monkeypatch.setattr(db2, "get_xdist_worker_num", lambda: None)
    monkeypatch.setattr(db2, "tcp_port_open", lambda *_args, **_kwargs: True)

    scripts: list[str] = []
    mock_container = MagicMock()
    mock_container.logs.return_value = container_logs

    def _exec_run(cmd: list[str]) -> MagicMock:
        scripts.append(cmd[4])
        return MagicMock(exit_code=4, output=clp_output)

    mock_container.exec_run.side_effect = _exec_run

    @contextmanager
    def _fake_run(**kwargs: object) -> Generator[ServiceContainer, None, None]:
        check_fn = kwargs["check"]
        assert callable(check_fn)
        svc = ServiceContainer(container=mock_container, host="127.0.0.1", port=50000)
        with pytest.raises(RuntimeError, match=expected_marker) as exc_info:
            check_fn(svc)
        assert "pytestdb" in str(exc_info.value)
        yield svc

    container_service = MagicMock()
    container_service.run.side_effect = _fake_run
    with db2.provide_db2_service(
        container_service=container_service,
        db2_image=DEFAULT_DB2_IMAGE,
        db2_dbname="pytestdb",
        db2_username="db2inst1",
        db2_password="pw",
        db2_startup_timeout=300,
        xdist_db2_isolation_level="database",
        activate_database=False,
    ):
        pass
    assert not any("db2stop force" in script for script in scripts)
