"""Tests for embedded and non-containerized PostgreSQL service management."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any
from unittest.mock import MagicMock, patch

import pytest

from pytest_databases.embedded import postgres as embedded_pg_mod
from pytest_databases.embedded.postgres import (
    EmbeddedPostgresService,
    PostgresBinaries,
    clone_template_database,
    compute_schema_fingerprint,
    create_worker_database_from_template,
    drop_database_force,
    embedded_postgres_database,
    ensure_template_database,
    exec_psql,
    make_connection_string,
    resolve_postgres_binaries,
    sweep_worker_databases,
)

if TYPE_CHECKING:
    from pathlib import Path


@pytest.fixture
def mock_binaries(tmp_path: Path) -> PostgresBinaries:
    """Create a mock PostgresBinaries instance with executable files."""
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir(parents=True)
    initdb = bin_dir / "initdb"
    postgres = bin_dir / "postgres"
    pg_ctl = bin_dir / "pg_ctl"
    psql = bin_dir / "psql"
    for binary in (initdb, postgres, pg_ctl, psql):
        binary.write_text("#!/bin/sh\nexit 0\n", encoding="utf-8")
        binary.chmod(0o755)
    return PostgresBinaries(
        initdb=initdb,
        postgres=postgres,
        pg_ctl=pg_ctl,
        psql=psql,
    )


@pytest.fixture
def embedded_service(mock_binaries: PostgresBinaries, tmp_path: Path) -> EmbeddedPostgresService:
    """Create an EmbeddedPostgresService instance with mock binaries."""
    data_dir = tmp_path / "data"
    data_dir.mkdir(parents=True)
    return EmbeddedPostgresService(
        host="127.0.0.1",
        port=5433,
        user="postgres",
        password="test_password",
        database="postgres",
        data_dir=data_dir,
        binaries=mock_binaries,
    )


def test_make_connection_string() -> None:
    """Verify make_connection_string formats a standard libpq DSN."""
    dsn = make_connection_string(
        host="127.0.0.1",
        port=5432,
        user="postgres",
        password="secret_password",
        database="test_db",
    )
    assert dsn == "dbname=test_db user=postgres host=127.0.0.1 port=5432 password=secret_password"


def test_resolve_postgres_binaries_with_explicit_dir(mock_binaries: PostgresBinaries) -> None:
    """Verify resolve_postgres_binaries discovers binaries from an explicit directory."""
    discovered = resolve_postgres_binaries(mock_binaries.initdb.parent)
    assert discovered.initdb == mock_binaries.initdb
    assert discovered.postgres == mock_binaries.postgres
    assert discovered.psql == mock_binaries.psql


def test_resolve_postgres_binaries_with_pgserver(mock_binaries: PostgresBinaries) -> None:
    """Verify resolve_postgres_binaries discovers binaries via pgserver submodules."""
    mock_pgserver = MagicMock(spec=[])
    mock_commands = MagicMock()
    mock_commands.POSTGRES_BIN_PATH = mock_binaries.initdb.parent
    mock_pgserver._commands = mock_commands

    with (
        patch.dict("os.environ", {"PG_BIN_DIR": ""}, clear=True),
        patch("shutil.which", return_value=None),
        patch.object(embedded_pg_mod, "pgembed", None),
        patch.object(embedded_pg_mod, "pgserver", mock_pgserver),
    ):
        discovered = resolve_postgres_binaries()
        assert discovered.initdb == mock_binaries.initdb


def test_resolve_postgres_binaries_missing_raises_runtime_error(tmp_path: Path) -> None:
    """Verify resolve_postgres_binaries raises RuntimeError when binaries are absent."""
    empty_dir = tmp_path / "empty_bin"
    empty_dir.mkdir()
    with (
        patch.dict("os.environ", {"PG_BIN_DIR": ""}, clear=True),
        patch("shutil.which", return_value=None),
        patch.object(embedded_pg_mod, "pgembed", None),
        patch.object(embedded_pg_mod, "pgserver", None),
        pytest.raises(RuntimeError, match=r"PostgreSQL server binaries .* were not found"),
    ):
        resolve_postgres_binaries(empty_dir)


def test_embedded_postgres_service_properties(embedded_service: EmbeddedPostgresService) -> None:
    """Verify dsn and connection_config properties match expected formats."""
    expected_dsn = "dbname=postgres user=postgres host=127.0.0.1 port=5433 password=test_password"
    assert embedded_service.dsn == expected_dsn
    assert embedded_service.connection_config == {
        "host": "127.0.0.1",
        "port": 5433,
        "user": "postgres",
        "password": "test_password",
        "database": "postgres",
    }


def test_exec_psql_unit(mock_binaries: PostgresBinaries) -> None:
    """Verify exec_psql executes the expected command and parses output."""
    with patch("subprocess.run") as mock_run:
        mock_run.return_value = MagicMock(returncode=0, stdout=b"1\n", stderr=b"")
        code, output = exec_psql(
            mock_binaries,
            user="postgres",
            password="pwd",
            database="postgres",
            host="127.0.0.1",
            port=5432,
            sql="SELECT 1",
            tuples_only=True,
        )
        assert code == 0
        assert output == b"1\n"
        assert mock_run.call_count == 1
        args, kwargs = mock_run.call_args
        assert "-tAc" in args[0]
        assert "SELECT 1" in args[0]
        assert kwargs["env"]["PGPASSWORD"] == "pwd"


def test_clone_template_database_unit(embedded_service: EmbeddedPostgresService) -> None:
    """Verify clone_template_database executes backend termination and cloning SQL."""
    calls: list[str] = []

    def fake_exec_psql(_binaries: Any, **kwargs: Any) -> tuple[int, bytes]:
        calls.append(kwargs["sql"])
        return 0, b""

    with patch.object(embedded_pg_mod, "exec_psql", side_effect=fake_exec_psql):
        result = clone_template_database(
            embedded_service,
            target_db="worker_clone_1",
            source_db="base_tpl",
        )
        assert result == "worker_clone_1"
        assert len(calls) == 2
        assert "SELECT pg_terminate_backend(pid)" in calls[0]
        assert 'CREATE DATABASE "worker_clone_1" TEMPLATE "base_tpl";' in calls[1]
        assert embedded_service.clone_template_database("worker_clone_2", source_db="base_tpl") == "worker_clone_2"


def test_drop_database_force_unit(embedded_service: EmbeddedPostgresService) -> None:
    """Verify drop_database_force terminates connections and drops database."""
    calls: list[str] = []

    def fake_exec_psql(_binaries: Any, **kwargs: Any) -> tuple[int, bytes]:
        calls.append(kwargs["sql"])
        return 0, b""

    with patch.object(embedded_pg_mod, "exec_psql", side_effect=fake_exec_psql):
        drop_database_force(embedded_service, db_name="transient_db")
        assert len(calls) == 2
        assert "WHERE datname = 'transient_db'" in calls[0]
        assert 'DROP DATABASE IF EXISTS "transient_db";' in calls[1]
        embedded_service.drop_database_force("another_db")
        assert len(calls) == 4


def test_ensure_template_database_unit(embedded_service: EmbeddedPostgresService, tmp_path: Path) -> None:
    """Verify ensure_template_database double-checked locking, staging, and conversion flow."""
    calls: list[str] = []
    checks = 0

    def fake_exec_psql(_binaries: Any, **kwargs: Any) -> tuple[int, bytes]:
        nonlocal checks
        sql = kwargs["sql"]
        calls.append(sql)
        if "datistemplate = true" in sql:
            checks += 1
            if checks >= 3:
                return 0, b"1"
            return 0, b"0"
        return 0, b""

    lock_dir = tmp_path / "locks"
    lock_dir.mkdir()

    with patch.object(embedded_pg_mod, "exec_psql", side_effect=fake_exec_psql):
        tpl_name = ensure_template_database(
            embedded_service,
            template_name="app_schema",
            setup_sql="CREATE TABLE items (id serial PRIMARY KEY);",
            lock_dir=lock_dir,
            fingerprint_sources=["CREATE TABLE items;"],
        )
        assert tpl_name.startswith("app_schema_")
        assert any('CREATE DATABASE "' in call for call in calls)
        assert any("CREATE TABLE items" in call for call in calls)
        assert any("WITH is_template = true allow_connections = false;" in call for call in calls)
        assert any("RENAME TO" in call for call in calls)


def test_create_worker_database_from_template_unit(embedded_service: EmbeddedPostgresService) -> None:
    """Verify create_worker_database_from_template clones and verifies connectivity."""
    calls: list[str] = []

    def fake_exec_psql(_binaries: Any, **kwargs: Any) -> tuple[int, bytes]:
        sql = kwargs["sql"]
        calls.append(sql)
        if sql == "SELECT 1":
            return 0, b"1"
        return 0, b""

    with patch.object(embedded_pg_mod, "exec_psql", side_effect=fake_exec_psql):
        worker_db = create_worker_database_from_template(
            embedded_service,
            template_name="base_tpl",
            worker_db="worker_1_db",
        )
        assert worker_db == "worker_1_db"
        assert any('CREATE DATABASE "worker_1_db" TEMPLATE "base_tpl";' in call for call in calls)
        assert any('ALTER DATABASE "worker_1_db" WITH allow_connections = true;' in call for call in calls)
        assert any(call == "SELECT 1" for call in calls)


def test_sweep_worker_databases_unit(embedded_service: EmbeddedPostgresService) -> None:
    """Verify sweep_worker_databases discovers and drops transient worker databases."""
    calls: list[str] = []

    def fake_exec_psql(_binaries: Any, **kwargs: Any) -> tuple[int, bytes]:
        sql = kwargs["sql"]
        calls.append(sql)
        if "SELECT datname FROM pg_database" in sql:
            return 0, b"pytest_databases_worker_0\npytest_databases_worker_1\n"
        return 0, b""

    with patch.object(embedded_pg_mod, "exec_psql", side_effect=fake_exec_psql):
        dropped = sweep_worker_databases(embedded_service, prefix="pytest_databases_")
        assert dropped == ["pytest_databases_worker_0", "pytest_databases_worker_1"]
        assert any('DROP DATABASE IF EXISTS "pytest_databases_worker_0";' in call for call in calls)
        assert any('DROP DATABASE IF EXISTS "pytest_databases_worker_1";' in call for call in calls)


def test_compute_schema_fingerprint(tmp_path: Path) -> None:
    """Verify compute_schema_fingerprint generates consistent digests."""
    sql1 = "CREATE TABLE users (id int);"
    sql2 = "CREATE TABLE users (id int);"
    sql3 = "CREATE TABLE orders (id int);"
    digest1 = compute_schema_fingerprint(sql1)
    digest2 = compute_schema_fingerprint(sql2)
    digest3 = compute_schema_fingerprint(sql3)
    assert len(digest1) == 12
    assert digest1 == digest2
    assert digest1 != digest3

    f1 = tmp_path / "schema.sql"
    f1.write_text(sql1, encoding="utf-8")
    file_digest1 = compute_schema_fingerprint(f1)
    file_digest2 = compute_schema_fingerprint(f1)
    assert file_digest1 == file_digest2
    assert len(file_digest1) == 12


def test_plugin_imports_without_pgembed(pytester: pytest.Pytester) -> None:
    """Verify pytest_databases.embedded.postgres imports cleanly when pgembed is absent."""
    pytester.makepyfile("""
import builtins

def test_import() -> None:
    original_import = builtins.__import__

    def blocked_import(name, globals=None, locals=None, fromlist=(), level=0):
        if name in ("pgembed", "pgserver") or name.startswith(("pgembed.", "pgserver.")):
            raise ModuleNotFoundError(name)
        return original_import(name, globals, locals, fromlist, level)

    builtins.__import__ = blocked_import
    try:
        import pytest_databases.embedded.postgres
        assert hasattr(pytest_databases.embedded.postgres, "EmbeddedPostgresService")
    finally:
        builtins.__import__ = original_import
""")

    result = pytester.runpytest_subprocess("-p", "pytest_databases.embedded.postgres", "-vv")
    result.assert_outcomes(passed=1)


def test_embedded_postgres_database_default() -> None:
    """Verify embedded_postgres_database defaults to pytest_databases."""
    fn = getattr(embedded_postgres_database, "__wrapped__", embedded_postgres_database)
    assert fn() == "pytest_databases"


def test_start_cluster_socket_handling_and_readiness(mock_binaries: PostgresBinaries, tmp_path: Path) -> None:
    """Verify start_cluster passes -k empty string by default and checks SQL readiness."""
    data_dir = tmp_path / "pgdata"
    data_dir.mkdir()

    with (
        patch("subprocess.Popen") as mock_popen,
        patch.object(embedded_pg_mod, "_check_socket_ready", return_value=True),
        patch.object(embedded_pg_mod, "exec_psql", return_value=(0, b"1\n")),
    ):
        fake_proc = MagicMock()
        fake_proc.poll.return_value = None
        mock_popen.return_value = fake_proc

        proc, port = embedded_pg_mod.start_cluster(mock_binaries, data_dir, port=54321)
        assert proc is fake_proc
        assert port == 54321
        cmd = mock_popen.call_args[0][0]
        assert "-k" in cmd
        k_idx = cmd.index("-k")
        assert cmd[k_idx + 1] == ""

        custom_socket = tmp_path / "custom_socket"
        embedded_pg_mod.start_cluster(mock_binaries, data_dir, port=54322, unix_socket_dir=custom_socket)
        cmd2 = mock_popen.call_args[0][0]
        assert cmd2[cmd2.index("-k") + 1] == str(custom_socket)


def test_resolve_postgres_binaries_system_fallback(tmp_path: Path) -> None:
    """Verify resolve_postgres_binaries falls back to system locations when not on PATH."""
    sys_dir = tmp_path / "usr_lib_pg" / "bin"
    sys_dir.mkdir(parents=True)
    for name in ("initdb", "postgres", "pg_ctl", "psql"):
        f = sys_dir / name
        f.write_text("#!/bin/sh\nexit 0\n", encoding="utf-8")
        f.chmod(0o755)

    with (
        patch.dict("os.environ", {"PG_BIN_DIR": ""}, clear=True),
        patch("shutil.which", return_value=None),
        patch.object(embedded_pg_mod, "pgembed", None),
        patch.object(embedded_pg_mod, "pgserver", None),
        patch.object(
            embedded_pg_mod,
            "_find_binaries_in_system_locations",
            return_value=PostgresBinaries(
                initdb=sys_dir / "initdb",
                postgres=sys_dir / "postgres",
                pg_ctl=sys_dir / "pg_ctl",
                psql=sys_dir / "psql",
            ),
        ),
    ):
        discovered = resolve_postgres_binaries()
        assert discovered.postgres == sys_dir / "postgres"


def test_shared_cluster_metadata_cycle(tmp_path: Path) -> None:
    """Verify active cluster metadata reading and cleanup."""
    json_file = tmp_path / "cluster.json"
    lock_file = tmp_path / "cluster.lock"

    assert embedded_pg_mod._read_active_cluster_metadata(json_file) is None

    payload = {
        "host": "127.0.0.1",
        "port": 5432,
        "user": "postgres",
        "password": "",
        "database": "pytest_databases",
        "data_dir": str(tmp_path / "data"),
        "pid": 99999999,
    }
    json_file.write_text(embedded_pg_mod.json.dumps(payload), encoding="utf-8")

    with patch.object(embedded_pg_mod, "_check_socket_ready", return_value=True):
        read_back = embedded_pg_mod._read_active_cluster_metadata(json_file)
        assert read_back is not None
        assert read_back["port"] == 5432

    embedded_pg_mod._cleanup_shared_cluster(tmp_path, lock_file, json_file)
    assert not json_file.exists()
