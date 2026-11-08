"""Unit tests for SAP Sybase ASE container fixtures and CLI helpers."""

from __future__ import annotations

from types import SimpleNamespace
from typing import TYPE_CHECKING
from unittest.mock import MagicMock

import pytest

import pytest_databases.docker.sybase as sybase_mod
from pytest_databases.docker.sybase import (
    DEFAULT_SYBASE_IMAGE,
    SYBASE_DATABASE,
    SYBASE_PASSWORD,
    SYBASE_USER,
    SybaseService,
    _is_sybase_ready,
    _resolve_sybase_database,
    create_worker_database,
    exec_isql,
    provide_sybase_service,
    validate_sybase_database_name,
)

if TYPE_CHECKING:
    from pytest_databases.types import XdistIsolationLevel

ISQL_SELECT_OUTPUT = b"        4242 \n\n(1 row affected)\n"
ISQL_SERVER_ERROR = (
    b"Msg 208, Level 16, State 1:\n"
    b"Server 'MYSYBASE', Line 1:\n"
    b"nosuch not found. Specify owner.objectname or use sp_help to check whether the object exists.\n"
)
ISQL_CREATE_DATABASE_ERROR = (
    b"CREATE DATABASE: allocating 512 logical pages (8.0 megabytes) on disk 'master'.\n"
    b"Msg 1810, Level 16, State 1:\n"
    b"Server 'MYSYBASE', Line 3:\n"
    b"CREATE DATABASE failed because of incorrectly specified or unavailable space.\n"
)
ISQL_LOCALIZATION_ERROR = (
    b"\n\nThe context allocation routine failed when it tried to load localization files!!\n"
    b"Cannot access the sybase home directory, please check environment variable SYBASE or ~sybase\n"
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
    assert validate_sybase_database_name("a" * 30) == "a" * 30


@pytest.mark.parametrize("name", ["1_starts_with_number", "a" * 31, "invalid-hyphen", "trailing_newline\n"])
def test_sybase_validate_database_name_rejects(name: str) -> None:
    """Verify invalid identifiers, including over-long and newline-terminated names, are rejected."""
    with pytest.raises(ValueError, match="Invalid Sybase database name"):
        validate_sybase_database_name(name)


def test_sybase_exec_isql_command_construction() -> None:
    """Verify exec_isql sources the image environment and runs isql against the local port with server errors."""
    fake_container = MagicMock()
    fake_container.exec_run.return_value = SimpleNamespace(exit_code=0, output=ISQL_SELECT_OUTPUT)

    exit_code, output = exec_isql(fake_container, "SELECT 4242", database="master", user="sa", password="myPassword")

    assert (exit_code, output) == (0, ISQL_SELECT_OUTPUT)
    command = fake_container.exec_run.call_args.args[0]
    assert command[:2] == ["sh", "-c"]
    script = command[2]
    assert ". /opt/sybase/SYBASE.sh" in script
    assert "-S 127.0.0.1:5000 -U sa -P myPassword -D master -w 2048 --retserverror -b" in script
    assert "SELECT 4242\ngo\nEOF" in script
    assert "sqsh" not in script


@pytest.mark.parametrize(
    ("exit_code", "output", "expected_code"),
    [
        (0, ISQL_SELECT_OUTPUT, 0),
        (0, ISQL_SERVER_ERROR, 1),
        (0, ISQL_LOCALIZATION_ERROR, 1),
        (0, b"Msg 5701, Level 10, State 1:\nChanged database context to 'master'.\n", 0),
        (2, ISQL_SERVER_ERROR + b"Msg\t208\n", 2),
        (255, b"CT-LIBRARY error:\n\tct_connect(): protocol specific layer: external error.\n", 255),
    ],
)
def test_sybase_exec_isql_reports_server_errors(exit_code: int, output: bytes, expected_code: int) -> None:
    """Verify a zero isql exit code is replaced when the output holds a severity 11+ or client library error."""
    fake_container = MagicMock()
    fake_container.exec_run.return_value = SimpleNamespace(exit_code=exit_code, output=output)

    assert exec_isql(fake_container, "SELECT 1") == (expected_code, output)


def test_sybase_create_worker_database() -> None:
    """Verify create_worker_database creates a device next to the master device and a database on it."""
    fake_container = MagicMock()
    fake_container.exec_run.side_effect = [
        SimpleNamespace(exit_code=0, output=b" /opt/sybase/data/master.dat \n\n(1 row affected)\n"),
        SimpleNamespace(exit_code=0, output=b"CREATE DATABASE: allocating 3072 logical pages (48.0 megabytes).\n"),
    ]

    create_worker_database(fake_container, "worker_db")

    script = fake_container.exec_run.call_args_list[1].args[0][2]
    assert "DISK INIT name = 'worker_db_dev', physname = '/opt/sybase/data/worker_db.dat', size = '48M'" in script
    assert "CREATE DATABASE worker_db ON worker_db_dev = '48M'" in script
    assert "WHERE name = 'worker_db')" in script


def test_sybase_create_worker_database_failure() -> None:
    """Verify a server error that isql reports with exit code 0 makes create_worker_database raise."""
    fake_container = MagicMock()
    fake_container.exec_run.side_effect = [
        SimpleNamespace(exit_code=0, output=b" /opt/sybase/data/master.dat \n\n(1 row affected)\n"),
        SimpleNamespace(exit_code=0, output=ISQL_CREATE_DATABASE_ERROR),
    ]

    with pytest.raises(RuntimeError, match=r"(?s)Failed to create Sybase database 'failed_db' \(exit 1\).*Msg 1810"):
        create_worker_database(fake_container, "failed_db")


def test_sybase_create_worker_database_retries_when_model_in_use(monkeypatch: pytest.MonkeyPatch) -> None:
    """Verify create_worker_database retries when SAP ASE reports model is locked (Msg 1807)."""
    monkeypatch.setattr(sybase_mod.time, "sleep", lambda _delay: None)
    fake_container = MagicMock()
    fake_container.id = "abcdef1234567890"
    model_busy = b"Msg 1807, Level 17, State 1:\nMODEL database in use, cannot create new database.\n"
    fake_container.exec_run.side_effect = [
        SimpleNamespace(exit_code=0, output=b" /opt/sybase/data/master.dat \n\n(1 row affected)\n"),
        SimpleNamespace(exit_code=0, output=model_busy),
        SimpleNamespace(exit_code=0, output=b"CREATE DATABASE: allocating 3072 logical pages (48.0 megabytes).\n"),
    ]

    create_worker_database(fake_container, "worker_db")

    assert fake_container.exec_run.call_count == 3


def test_sybase_create_worker_database_without_master_device() -> None:
    """Verify create_worker_database raises when the master device path cannot be read."""
    fake_container = MagicMock()
    fake_container.exec_run.return_value = SimpleNamespace(exit_code=0, output=ISQL_LOCALIZATION_ERROR)

    with pytest.raises(RuntimeError, match="Failed to locate the Sybase master device"):
        create_worker_database(fake_container, "worker_db")


@pytest.mark.parametrize(
    ("exit_code", "output", "ready"),
    [
        (0, ISQL_SELECT_OUTPUT, True),
        (0, b"", False),
        (1, ISQL_SERVER_ERROR, False),
        (0, b"Msg 911, Level 11, State 2:\nServer 'MYSYBASE', Line 1:\n", False),
        (0, b"        14242 \n\n(1 row affected)\n", False),
        (2, ISQL_SELECT_OUTPUT, False),
    ],
)
def test_sybase_readiness_requires_exact_row(exit_code: int, output: bytes, ready: bool) -> None:
    """Verify readiness needs a zero exit code and an output line that is exactly the probe value."""
    assert _is_sybase_ready(exit_code, output) is ready


@pytest.mark.parametrize(
    ("database", "worker_num", "isolation", "expected"),
    [
        ("master", None, "database", "master"),
        ("appdb", None, "database", "appdb"),
        ("master", 0, "database", "pytestdb_0"),
        ("master", 11, "database", "pytestdb_11"),
        ("appdb", 1, "database", "appdb_1"),
        ("master", 1, "server", "master"),
        ("appdb", 1, "server", "appdb"),
    ],
)
def test_sybase_resolve_database(
    database: str, worker_num: int | None, isolation: XdistIsolationLevel, expected: str
) -> None:
    """Verify each xdist worker gets its own database derived from ``sybase_database`` under database isolation."""
    assert _resolve_sybase_database(database, worker_num, isolation) == expected


def test_sybase_resolve_database_rejects_long_worker_name() -> None:
    """Verify the worker suffix is validated against the 30-character ASE identifier limit."""
    with pytest.raises(ValueError, match="at most 30 characters"):
        _resolve_sybase_database("a" * 28, 10, "database")


@pytest.mark.parametrize(
    ("worker_num", "isolation", "name", "transient", "created"),
    [
        (None, "database", "sybase", False, None),
        (2, "database", "sybase", False, "pytestdb_2"),
        (2, "server", "sybase_2", True, None),
    ],
)
def test_provide_sybase_service_lifecycle(
    monkeypatch: pytest.MonkeyPatch,
    worker_num: int | None,
    isolation: XdistIsolationLevel,
    name: str,
    transient: bool,
    created: str | None,
) -> None:
    """Verify container naming, transience, worker database creation, and the readiness check."""
    fake_container = MagicMock()
    fake_container.logs.return_value = b"=============== SYBASE INITIALIZED =========================="
    fake_container.exec_run.return_value = SimpleNamespace(exit_code=0, output=ISQL_SELECT_OUTPUT)
    fake_service = SimpleNamespace(host="127.0.0.1", port=5000, container=fake_container)
    run_ctx = MagicMock()
    run_ctx.__enter__.return_value = fake_service
    run_ctx.__exit__.return_value = False
    container_service = MagicMock()
    container_service.run.return_value = run_ctx
    created_databases: list[str] = []

    monkeypatch.setattr(sybase_mod, "tcp_port_open", lambda *_args, **_kwargs: True)
    monkeypatch.setattr(sybase_mod, "get_xdist_worker_num", lambda: worker_num)
    monkeypatch.setattr(
        sybase_mod, "create_worker_database", lambda _container, db_name, **_kwargs: created_databases.append(db_name)
    )

    with provide_sybase_service(
        container_service=container_service,
        sybase_image=DEFAULT_SYBASE_IMAGE,
        sybase_user=SYBASE_USER,
        sybase_password=SYBASE_PASSWORD,
        sybase_database=SYBASE_DATABASE,
        sybase_startup_timeout=60,
        xdist_sybase_isolation_level=isolation,
    ) as service:
        assert (service.host, service.port, service.user) == ("127.0.0.1", 5000, "sa")
        assert service.database == (created or "master")

    kwargs = container_service.run.call_args.kwargs
    assert kwargs["container_port"] == 5000
    assert kwargs["name"] == name
    assert kwargs["transient"] is transient
    assert created_databases == ([created] if created else [])

    check_fn = kwargs["check"]
    assert check_fn(fake_service) is True
    fake_container.exec_run.return_value = SimpleNamespace(exit_code=0, output=ISQL_SERVER_ERROR)
    assert check_fn(fake_service) is False
    fake_container.exec_run.return_value = SimpleNamespace(exit_code=0, output=ISQL_SELECT_OUTPUT)
    fake_container.logs.return_value = b"Starting Sybase ASE..."
    assert check_fn(fake_service) is False
    monkeypatch.setattr(sybase_mod, "tcp_port_open", lambda *_args, **_kwargs: False)
    assert check_fn(fake_service) is False


def test_provide_sybase_service_timeout_diagnostics(monkeypatch: pytest.MonkeyPatch) -> None:
    """Timeout errors from Sybase readiness polling include container diagnostics."""
    fake_container = MagicMock()
    fake_container.logs.return_value = b"=============== SYBASE INITIALIZED =========================="
    fake_container.exec_run.return_value = SimpleNamespace(exit_code=0, output=b"dataserver\nMYSYBASE failed")
    fake_service = SimpleNamespace(host="127.0.0.1", port=5000, container=fake_container)

    def _fail_enter(*_args: object) -> object:
        kwargs = container_service.run.call_args.kwargs
        kwargs["check"](fake_service)
        msg = "Service 'pytest_databases_sybase' failed to come online"
        raise ValueError(msg)

    run_ctx = MagicMock()
    run_ctx.__enter__.side_effect = _fail_enter
    container_service = MagicMock()
    container_service.run.return_value = run_ctx

    monkeypatch.setattr(sybase_mod, "get_xdist_worker_num", lambda: None)
    monkeypatch.setattr(sybase_mod, "tcp_port_open", lambda *_args, **_kwargs: True)
    monkeypatch.setattr(sybase_mod, "exec_isql", lambda *_args, **_kwargs: (1, b""))

    with (
        pytest.raises(ValueError, match="Last Sybase readiness stage: isql") as exc_info,
        provide_sybase_service(
            container_service=container_service,
            sybase_image=DEFAULT_SYBASE_IMAGE,
            sybase_user=SYBASE_USER,
            sybase_password=SYBASE_PASSWORD,
            sybase_database=SYBASE_DATABASE,
            sybase_startup_timeout=5,
            xdist_sybase_isolation_level="database",
        ),
    ):
        pass

    message = str(exc_info.value)
    assert "=============== SYBASE INITIALIZED ==========================" in message
    assert "MYSYBASE failed" in message


def test_sybase_service_live(pytester: pytest.Pytester) -> None:
    """Start Sybase ASE without xdist and run SQL through the in-container isql."""
    pytester.makepyfile("""
    from pytest_databases.docker.sybase import SybaseService

    pytest_plugins = ["pytest_databases.docker.sybase"]


    def test_query(sybase_service: SybaseService) -> None:
        assert sybase_service.database == "master"
        code, output = sybase_service.exec_sql("SELECT 6 * 7")
        assert code == 0
        assert "42" in output.decode().split()
        code, output = sybase_service.exec_sql("SELECT * FROM missing_table")
        assert code != 0
        assert b"Msg 208, Level 16" in output
    """)
    result = pytester.runpytest_subprocess("-p", "pytest_databases", timeout=900)
    result.assert_outcomes(passed=1)


def test_sybase_service_live_database_isolation(pytester: pytest.Pytester) -> None:
    """Start one Sybase ASE container for two xdist workers and check each worker uses its own database."""
    pytester.makepyfile("""
    from pytest_databases.docker.sybase import SybaseService
    from pytest_databases.helpers import get_xdist_worker_num

    pytest_plugins = ["pytest_databases.docker.sybase"]


    def _assert_worker_database(sybase_service: SybaseService) -> None:
        expected = f"pytestdb_{get_xdist_worker_num()}"
        assert sybase_service.database == expected
        code, output = sybase_service.exec_sql("SELECT db_name()")
        assert code == 0, output
        assert expected in output.decode().split()
        code, output = sybase_service.exec_sql(
            "CREATE TABLE worker_rows (id int)\\ngo\\nINSERT INTO worker_rows VALUES (42)\\ngo\\n"
            "SELECT count(*) FROM worker_rows"
        )
        assert code == 0, output
        assert "1" in output.decode().split()


    def test_one(sybase_service: SybaseService) -> None:
        _assert_worker_database(sybase_service)


    def test_two(sybase_service: SybaseService) -> None:
        _assert_worker_database(sybase_service)
    """)
    result = pytester.runpytest_subprocess("-p", "pytest_databases", "-n", "2", timeout=900)
    result.assert_outcomes(passed=2)


def test_sybase_all_fixtures_inprocess(pytester: pytest.Pytester) -> None:
    """Verify Sybase config and service fixtures execute in-process with mocked provider."""
    pytester.makepyfile("""
    from contextlib import contextmanager
    from unittest.mock import MagicMock, patch
    import pytest

    pytest_plugins = ["pytest_databases.docker.sybase"]

    @pytest.fixture(scope="session")
    def container_service() -> MagicMock:
        return MagicMock()

    def test_fixtures(request: pytest.FixtureRequest) -> None:
        mock_svc = MagicMock()

        @contextmanager
        def fake_svc(*args, **kwargs):
            yield mock_svc

        with patch("pytest_databases.docker.sybase.provide_sybase_service", side_effect=fake_svc):
            assert request.getfixturevalue("sybase_image")
            assert request.getfixturevalue("sybase_user") == "sa"
            assert request.getfixturevalue("sybase_password")
            assert request.getfixturevalue("sybase_database") == "master"
            assert request.getfixturevalue("sybase_startup_timeout") == 300
            assert request.getfixturevalue("xdist_sybase_isolation_level") == "database"
            assert request.getfixturevalue("sybase_service") is mock_svc
    """)
    result = pytester.runpytest("-p", "no:sugar", "-p", "pytest_databases")
    result.assert_outcomes(passed=1)
