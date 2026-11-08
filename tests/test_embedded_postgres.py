"""Tests for the embedded PostgreSQL service."""

from __future__ import annotations

import socket
import struct
import subprocess
import sys
import threading
from contextlib import contextmanager
from types import SimpleNamespace
from typing import TYPE_CHECKING, Any
from unittest.mock import MagicMock

import pytest

from pytest_databases.embedded import _pgwire
from pytest_databases.embedded import postgres as embedded_mod
from pytest_databases.embedded.postgres import (
    EmbeddedPostgresService,
    PostgresBinaries,
    embedded_postgres_database,
    provide_embedded_postgres_service,
    resolve_postgres_binaries,
    start_cluster,
)
from tests.conftest import unwrap_fixture

if TYPE_CHECKING:
    from collections.abc import Callable
    from pathlib import Path

try:
    resolve_postgres_binaries()
except RuntimeError:
    BINARIES_AVAILABLE = False
else:
    BINARIES_AVAILABLE = True

requires_binaries = pytest.mark.skipif(not BINARIES_AVAILABLE, reason="PostgreSQL server binaries not found")


def _make_bin_dir(root: Path, names: tuple[str, ...]) -> Path:
    root.mkdir(parents=True, exist_ok=True)
    for name in names:
        binary = root / name
        binary.write_text("#!/bin/sh\nexit 0\n", encoding="utf-8")
        binary.chmod(0o755)
    return root


@pytest.fixture
def isolated_discovery(monkeypatch: pytest.MonkeyPatch) -> dict[str, Any]:
    """Hide PATH, ``PG_BIN_DIR``, system directories, and real packages from binary discovery."""
    modules: dict[str, Any] = {}

    def fake_import(name: str) -> Any:
        if name in modules:
            return modules[name]
        raise ImportError(name)

    monkeypatch.delenv("PG_BIN_DIR", raising=False)
    monkeypatch.setattr(embedded_mod.shutil, "which", lambda _name: None)
    monkeypatch.setattr(embedded_mod.importlib, "import_module", fake_import)
    monkeypatch.setattr(embedded_mod, "_SYSTEM_BIN_GLOBS", ())
    return modules


def test_from_directory_makes_pg_ctl_optional(tmp_path: Path) -> None:
    """Verify ``pg_ctl`` is optional and never replaced by another binary."""
    bin_dir = _make_bin_dir(tmp_path / "bin", ("initdb", "postgres"))

    binaries = PostgresBinaries.from_directory(bin_dir)

    assert binaries == PostgresBinaries(initdb=bin_dir / "initdb", postgres=bin_dir / "postgres", pg_ctl=None)


def test_resolve_postgres_binaries_with_explicit_dir(tmp_path: Path) -> None:
    """Verify an explicit directory is used directly."""
    bin_dir = _make_bin_dir(tmp_path / "bin", ("initdb", "postgres", "pg_ctl"))

    assert resolve_postgres_binaries(bin_dir).pg_ctl == bin_dir / "pg_ctl"


def test_resolve_postgres_binaries_explicit_dir_missing_raises(tmp_path: Path) -> None:
    """Verify an explicit directory without the binaries raises instead of searching elsewhere."""
    (tmp_path / "empty").mkdir()

    with pytest.raises(RuntimeError, match=r"PostgreSQL server binaries .* were not found in"):
        resolve_postgres_binaries(tmp_path / "empty")


@pytest.mark.parametrize(
    "module_name",
    ["pgembed._commands", "pgserver._commands", "pgserver.postgres_server"],
)
def test_resolve_postgres_binaries_from_package_submodule(
    tmp_path: Path, isolated_discovery: dict[str, Any], module_name: str
) -> None:
    """Verify the binary path is read from the package submodule that defines it (pgembed 0.2 layout included)."""
    bin_dir = _make_bin_dir(tmp_path / module_name.replace(".", "_"), ("initdb", "postgres", "pg_ctl"))
    package = module_name.split(".", 1)[0]
    isolated_discovery[package] = SimpleNamespace()
    isolated_discovery[module_name] = SimpleNamespace(POSTGRES_BIN_PATH=bin_dir)

    assert resolve_postgres_binaries().postgres == bin_dir / "postgres"


def test_resolve_postgres_binaries_skips_incomplete_candidates(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, isolated_discovery: dict[str, Any]
) -> None:
    """Verify a candidate without ``postgres`` is skipped and discovery continues to the next one."""
    incomplete = _make_bin_dir(tmp_path / "incomplete", ("initdb",))
    complete = _make_bin_dir(tmp_path / "complete", ("initdb", "postgres"))
    monkeypatch.setenv("PG_BIN_DIR", str(incomplete))
    isolated_discovery["pgembed"] = SimpleNamespace()
    isolated_discovery["pgembed._commands"] = SimpleNamespace(POSTGRES_BIN_PATH=complete)

    assert resolve_postgres_binaries().initdb == complete / "initdb"


def test_resolve_postgres_binaries_missing_raises(isolated_discovery: dict[str, Any]) -> None:
    """Verify discovery raises a hint about the extra when nothing is found."""
    with pytest.raises(RuntimeError, match=r"embedded-postgres"):
        resolve_postgres_binaries()


def test_embedded_postgres_service_properties(tmp_path: Path) -> None:
    """Verify ``dsn`` and ``connection_config`` carry no password (trust authentication)."""
    service = EmbeddedPostgresService(
        host="127.0.0.1",
        port=5433,
        user="postgres",
        database="app",
        data_dir=tmp_path,
        binaries=PostgresBinaries(initdb=tmp_path / "initdb", postgres=tmp_path / "postgres"),
    )

    assert service.dsn == "dbname=app user=postgres host=127.0.0.1 port=5433"
    assert service.connection_config == {"host": "127.0.0.1", "port": 5433, "user": "postgres", "database": "app"}


def test_embedded_postgres_database_default() -> None:
    """Verify ``embedded_postgres_database`` defaults to ``pytest_databases``."""
    assert unwrap_fixture(embedded_postgres_database)() == "pytest_databases"


def _backend(kind: bytes, payload: bytes) -> bytes:
    return kind + struct.pack("!I", len(payload) + 4) + payload


def _data_row(*values: bytes | None) -> bytes:
    body = struct.pack("!H", len(values))
    for value in values:
        body += struct.pack("!i", -1) if value is None else struct.pack("!i", len(value)) + value
    return _backend(b"D", body)


READY = _backend(b"Z", b"I")
AUTH_OK = _backend(b"R", struct.pack("!I", 0))


@pytest.fixture
def fake_backend() -> Any:
    """Serve one connection that answers the startup with ``startup`` and the query with ``reply``.

    Yields:
        A callable starting the server and returning its port and the received frontend messages.
    """
    servers: list[socket.socket] = []

    def serve(startup: bytes, reply: bytes) -> tuple[int, list[bytes]]:
        server = socket.create_server(("127.0.0.1", 0))
        servers.append(server)
        received: list[bytes] = []

        def run() -> None:
            conn, _ = server.accept()
            with conn:
                (length,) = struct.unpack("!I", conn.recv(4))
                received.append(conn.recv(length - 4))
                conn.sendall(startup)
                if reply:
                    received.append(conn.recv(65536))
                    conn.sendall(reply)

        threading.Thread(target=run, daemon=True).start()
        return server.getsockname()[1], received

    yield serve
    for server in servers:
        server.close()


@pytest.mark.parametrize(
    ("startup", "reply", "expected"),
    [
        pytest.param(
            AUTH_OK + _backend(b"S", b"server_version\x0017\x00") + READY,
            _backend(b"T", b"")
            + _data_row(b"a", None, b"1")
            + _data_row(b"b", b"x", b"2")
            + _backend(b"C", b"SELECT 2\x00")
            + READY,
            (0, b"a||1\nb|x|2"),
            id="rows",
        ),
        pytest.param(
            AUTH_OK + READY,
            _backend(b"C", b"CREATE DATABASE\x00") + READY,
            (0, b"CREATE DATABASE"),
            id="command-tag",
        ),
        pytest.param(
            AUTH_OK + READY,
            _backend(b"E", b"SERROR\x00VERROR\x00C42601\x00Msyntax error\x00\x00") + READY,
            (1, b"ERROR:  syntax error"),
            id="sql-error",
        ),
        pytest.param(
            _backend(b"R", struct.pack("!I", 10) + b"SCRAM-SHA-256\x00\x00"),
            b"",
            (2, b"authentication method 10 is not supported; the cluster must use trust auth"),
            id="password-auth-rejected",
        ),
        pytest.param(
            _backend(b"E", b"SFATAL\x00VFATAL\x00Mthe database system is starting up\x00\x00"),
            b"",
            (2, b"FATAL:  the database system is starting up"),
            id="startup-error",
        ),
    ],
)
def test_run_simple_query(
    fake_backend: Callable[[bytes, bytes], tuple[int, list[bytes]]],
    startup: bytes,
    reply: bytes,
    expected: tuple[int, bytes],
) -> None:
    """Verify the wire client renders rows like ``psql -tA`` and maps errors to psql exit codes."""
    port, received = fake_backend(startup, reply)

    result = _pgwire.run_simple_query("127.0.0.1", port, user="postgres", database="app", sql="SELECT 1", timeout=5)

    assert result == expected
    assert b"user\x00postgres\x00database\x00app\x00" in received[0]
    if reply:
        assert received[1].startswith(b"Q") and b"SELECT 1\x00" in received[1]


def test_run_simple_query_connection_refused() -> None:
    """Verify an unreachable server is reported with exit code 2."""
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        port = sock.getsockname()[1]

    exit_code, output = _pgwire.run_simple_query("127.0.0.1", port, user="postgres", database="x", sql="SELECT 1")

    assert exit_code == 2
    assert f"127.0.0.1:{port}".encode() in output


def test_start_cluster_timeout_reports_last_result_and_log(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Verify a readiness timeout names the last query result and includes the server log tail."""
    (tmp_path / "postgresql.log").write_text("LOG:  database system is ready to accept connections\n")
    process = MagicMock()
    process.poll.return_value = None
    monkeypatch.setattr(embedded_mod.subprocess, "Popen", MagicMock(return_value=process))
    monkeypatch.setattr(embedded_mod, "tcp_port_open", lambda *_args, **_kwargs: True)
    monkeypatch.setattr(embedded_mod, "run_simple_query", lambda *_args, **_kwargs: (2, b"FATAL:  role does not exist"))
    binaries = PostgresBinaries(initdb=tmp_path / "initdb", postgres=tmp_path / "postgres")

    with pytest.raises(TimeoutError) as excinfo:
        start_cluster(binaries, tmp_path, port=54321, startup_timeout=0.3)

    message = str(excinfo.value)
    assert "exit 2" in message
    assert "role does not exist" in message
    assert "ready to accept connections" in message
    process.send_signal.assert_called_once()


def test_provide_registers_and_unregisters_its_own_exit_handler(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Verify each service unregisters exactly the handler it registered, leaving other services protected."""
    registered: list[Any] = []
    unregistered: list[Any] = []
    stopped: list[Any] = []
    monkeypatch.setattr(embedded_mod.atexit, "register", registered.append)
    monkeypatch.setattr(embedded_mod.atexit, "unregister", unregistered.append)
    monkeypatch.setattr(embedded_mod, "init_cluster", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(embedded_mod, "start_cluster", lambda *_args, **_kwargs: (MagicMock(), 55432))
    monkeypatch.setattr(embedded_mod, "stop_cluster", lambda *args, **_kwargs: stopped.append(args[1]))
    binaries = PostgresBinaries(initdb=tmp_path / "initdb", postgres=tmp_path / "postgres")

    with (
        provide_embedded_postgres_service(binaries=binaries, data_dir=tmp_path / "a"),
        provide_embedded_postgres_service(binaries=binaries, data_dir=tmp_path / "b"),
    ):
        assert len(registered) == 2
        assert registered[0] is not registered[1]

    assert unregistered == [registered[1], registered[0]]
    assert stopped == [tmp_path / "b", tmp_path / "a"]


def test_shared_cluster_ignores_state_of_dead_postmaster(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Verify recorded state is discarded when its PID is gone, even if something listens on the port."""
    finished = subprocess.Popen([sys.executable, "-c", ""])
    finished.wait()
    probes: list[int] = []

    def fake_query(host: str, port: int, **_kwargs: Any) -> tuple[int, bytes]:
        probes.append(port)
        return 0, b"1"

    monkeypatch.setattr(embedded_mod, "run_simple_query", fake_query)
    cluster = embedded_mod._SharedCluster(
        tmp_path,
        worker_id="gw0",
        binaries=PostgresBinaries(initdb=tmp_path / "initdb", postgres=tmp_path / "postgres"),
        user="postgres",
        port=0,
    )
    state_file = tmp_path / "embedded_postgres_cluster.json"
    state_file.write_text(embedded_mod.json.dumps({"host": "127.0.0.1", "port": 5432, "pid": finished.pid}))

    assert cluster._read_live_state() is None
    assert probes == []


def test_plugin_imports_without_pgembed(pytester: pytest.Pytester) -> None:
    """Verify ``pytest_databases.embedded.postgres`` imports cleanly when ``pgembed`` and ``pgserver`` are absent."""
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


EMBEDDED_ISOLATION_TESTS = """
import os

import pytest
from pytest_databases.embedded.postgres import EmbeddedPostgresService

pytest_plugins = ["pytest_databases.embedded.postgres"]

@pytest.fixture(scope="session")
def xdist_embedded_postgres_isolation_level():
    return "{isolation}"

@pytest.fixture(scope="session")
def embedded_postgres_template_setup():
    return [
        "CREATE TABLE users (id serial PRIMARY KEY, name text NOT NULL)",
        "INSERT INTO users (name) VALUES ('alice'), ('bob')",
    ]

def run(service, sql):
    exit_code, output = service.exec_sql(sql)
    assert exit_code == 0, output
    return output.decode()

def _check(service: EmbeddedPostgresService) -> None:
    worker = os.environ.get("PYTEST_XDIST_WORKER")
    assert service.database == ("pytest_databases" if worker is None else f"pytest_databases_{{worker[2:]}}")
    assert run(service, "SELECT current_database()") == service.database
    seeded = run(service, "SELECT count(*) FROM pg_tables WHERE tablename = 'users'")
    assert seeded == ("1" if "{isolation}" == "template" else "0")
    if seeded == "1":
        assert run(service, "SELECT count(*) FROM users WHERE name IN ('alice', 'bob')") == "2"
    run(service, "CREATE TABLE IF NOT EXISTS scratch (id int)")

def test_one(embedded_postgres_service: EmbeddedPostgresService) -> None:
    _check(embedded_postgres_service)

def test_two(embedded_postgres_service: EmbeddedPostgresService) -> None:
    _check(embedded_postgres_service)
"""


@requires_binaries
@pytest.mark.parametrize(
    ("isolation", "args"),
    [
        pytest.param("template", ("-n", "2"), id="template-xdist"),
        pytest.param("database", ("-n", "2"), id="database-xdist"),
        pytest.param("template", (), id="template-no-xdist"),
    ],
)
def test_embedded_postgres_service_live(pytester: pytest.Pytester, isolation: str, args: tuple[str, ...]) -> None:
    """Verify a real embedded cluster isolates databases per worker and is stopped and removed afterwards."""
    pytester.makepyfile(EMBEDDED_ISOLATION_TESTS.format(isolation=isolation))

    result = pytester.runpytest_subprocess("-p", "pytest_databases.embedded.postgres", *args)

    result.assert_outcomes(passed=2)
    leftovers = [*pytester.path.rglob("embedded_postgres_cluster.json"), *pytester.path.rglob("embedded_postgres_data")]
    assert leftovers == []


def test_embedded_postgres_cluster_lifecycle_and_helpers(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Verify init_cluster, start_cluster, stop_cluster, and helper error branches."""

    bins = PostgresBinaries(
        initdb=tmp_path / "initdb",
        postgres=tmp_path / "postgres",
        pg_ctl=tmp_path / "pg_ctl",
    )
    data_dir = tmp_path / "data"

    monkeypatch.setattr(
        "pytest_databases.embedded.postgres.subprocess.run",
        lambda *_a, **_kw: SimpleNamespace(returncode=0, stderr=b"", stdout=""),
    )
    embedded_mod.init_cluster(bins, data_dir)
    assert "fsync = off" in (data_dir / "postgresql.conf").read_text(encoding="utf-8")

    (data_dir / "PG_VERSION").write_text("17", encoding="utf-8")
    embedded_mod.init_cluster(bins, data_dir)

    fail_dir = tmp_path / "fail_data"
    monkeypatch.setattr(
        "pytest_databases.embedded.postgres.subprocess.run",
        lambda *_a, **_kw: SimpleNamespace(returncode=1, stderr=b"initdb boom"),
    )
    with pytest.raises(RuntimeError, match="initdb boom"):
        embedded_mod.init_cluster(bins, fail_dir)

    monkeypatch.setattr("pytest_databases.embedded.postgres.time.sleep", lambda _: None)
    fake_proc = MagicMock()
    fake_proc.poll.return_value = None
    fake_proc.pid = 12345
    monkeypatch.setattr("pytest_databases.embedded.postgres.subprocess.Popen", lambda *_a, **_kw: fake_proc)
    monkeypatch.setattr("pytest_databases.embedded.postgres.tcp_port_open", lambda *_a, **_kw: True)
    monkeypatch.setattr("pytest_databases.embedded.postgres.run_simple_query", lambda *_a, **_kw: (0, b"1"))
    proc, port = start_cluster(bins, data_dir, port=0)
    assert proc is fake_proc
    assert port > 0

    exited_proc = MagicMock()
    exited_proc.poll.return_value = 1
    exited_proc.returncode = 1
    monkeypatch.setattr("pytest_databases.embedded.postgres.subprocess.Popen", lambda *_a, **_kw: exited_proc)
    with pytest.raises(RuntimeError, match="exited with code 1"):
        start_cluster(bins, data_dir, port=0)

    (data_dir / "postmaster.pid").write_text("99999\n", encoding="utf-8")
    monkeypatch.setattr(
        "pytest_databases.embedded.postgres.subprocess.run",
        lambda *_a, **_kw: SimpleNamespace(returncode=0),
    )
    monkeypatch.setattr("pytest_databases.embedded.postgres.os.kill", lambda *_a, **_kw: None)
    times = iter([0.0, 0.1, 20.0])
    monkeypatch.setattr("pytest_databases.embedded.postgres.time.monotonic", lambda: next(times, 20.0))
    embedded_mod.stop_cluster(bins, data_dir, process=None, timeout=1.0)
    embedded_mod.stop_cluster(bins, data_dir, process=fake_proc, timeout=1.0)

    stub_proc = MagicMock()
    stub_proc.poll.return_value = None
    stub_proc.wait.side_effect = [subprocess.TimeoutExpired(cmd="pg", timeout=1.0), 0]
    embedded_mod._terminate(stub_proc, timeout=1.0)
    stub_proc.kill.assert_called_once()

    assert embedded_mod._log_tail(tmp_path / "missing.log") == "<no server log>"
    assert embedded_mod._postmaster_pid(tmp_path / "missing_dir") is None


def test_embedded_postgres_shared_cluster_and_prepare_database(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Verify _SharedCluster live state / cleanup and _prepare_database / _create_database branches."""

    bins = PostgresBinaries(initdb=tmp_path / "initdb", postgres=tmp_path / "postgres", pg_ctl=None)
    monkeypatch.setattr("pytest_databases.embedded.postgres.init_cluster", lambda *_a, **_kw: None)
    fake_proc = MagicMock(pid=4321)
    fake_proc.poll.return_value = 0
    monkeypatch.setattr("pytest_databases.embedded.postgres.start_cluster", lambda *_a, **_kw: (fake_proc, 55432))
    monkeypatch.setattr("pytest_databases.embedded.postgres.stop_cluster", lambda *_a, **_kw: None)
    monkeypatch.setattr("pytest_databases.embedded.postgres.os.kill", lambda *_a, **_kw: None)
    monkeypatch.setattr("pytest_databases.embedded.postgres.run_simple_query", lambda *_a, **_kw: (0, b"1"))

    shared_dir = tmp_path / "shared"
    shared_dir.mkdir()
    with embedded_mod._SharedCluster(shared_dir, worker_id="gw0", binaries=bins, user="postgres", port=0) as svc1:
        assert svc1.port == 55432
        with embedded_mod._SharedCluster(shared_dir, worker_id="gw1", binaries=bins, user="postgres", port=0) as svc2:
            assert svc2.port == 55432

    assert svc1._run_sql("postgres", "SELECT 1") == (0, b"1")
    monkeypatch.setattr(svc1, "ensure_template", lambda *_a, **_kw: "tmpl_1")
    monkeypatch.setattr(svc1, "create_worker_database_from_template", lambda *_a, **_kw: None)
    monkeypatch.setattr(svc1, "drop_database_force", lambda *_a, **_kw: None)

    prepared_tmpl = embedded_mod._prepare_database(
        svc1,
        db_name="w_db",
        isolation="template",
        template_name="tmpl",
        template_setup=None,
        fingerprint_sources=(),
        lock_dir=None,
    )
    assert prepared_tmpl.database == "w_db"

    prepared_db = embedded_mod._prepare_database(
        svc1,
        db_name="w_db2",
        isolation="database",
        template_name="tmpl",
        template_setup=None,
        fingerprint_sources=(),
        lock_dir=None,
    )
    assert prepared_db.database == "w_db2"

    monkeypatch.setattr(svc1, "exec_sql", lambda *_a, **_kw: (1, b"create failed"))
    with pytest.raises(RuntimeError, match="create failed"):
        embedded_mod._create_database(svc1, "bad_db")

    monkeypatch.setattr("pytest_databases.embedded.postgres._create_database", lambda *_a, **_kw: None)
    with provide_embedded_postgres_service(binaries=bins, database="custom_db", cleanup_mode="delete") as provided:
        assert provided.database == "custom_db"

    cluster_err = embedded_mod._SharedCluster(shared_dir, worker_id="gw9", binaries=bins, user="postgres", port=0)
    monkeypatch.setattr(cluster_err, "_provision", MagicMock(side_effect=RuntimeError("boom")))
    with pytest.raises(RuntimeError, match="boom"), cluster_err:
        pass

    cluster_err._state_file.write_text('{"pid": "bad"}', encoding="utf-8")
    assert cluster_err._read_live_state() is None
    cluster_err._state_file.write_text("not-json", encoding="utf-8")
    cluster_err._stop_recorded_cluster()

    assert embedded_mod._version_key(tmp_path / "16" / "bin") != embedded_mod._version_key(tmp_path / "17" / "bin")
    monkeypatch.setattr("pytest_databases.embedded.postgres.shutil.which", lambda _: "/usr/bin/pg_config")
    monkeypatch.setattr(
        "pytest_databases.embedded.postgres.subprocess.run",
        MagicMock(side_effect=OSError("exec err")),
    )
    assert embedded_mod._pg_config_bin_dirs() == []
    assert isinstance(embedded_mod._candidate_bin_dirs(), list)

    monkeypatch.setattr("pytest_databases.embedded.postgres.get_xdist_worker_id", lambda: "gw2")
    monkeypatch.setattr("pytest_databases.embedded.postgres.get_xdist_worker_num", lambda: 2)
    monkeypatch.setattr("pytest_databases.embedded.postgres.resolve_postgres_binaries", lambda _: bins)

    @contextmanager
    def fake_shared_cluster(*_a: Any, **_kw: Any) -> Any:
        yield MagicMock()

    monkeypatch.setattr("pytest_databases.embedded.postgres._SharedCluster", fake_shared_cluster)
    monkeypatch.setattr("pytest_databases.embedded.postgres._prepare_database", lambda admin, **_kw: admin)
    fake_tpf = MagicMock()
    fake_tpf.getbasetemp.return_value = tmp_path / "basetemp"
    gen = unwrap_fixture(embedded_mod.embedded_postgres_service)(
        fake_tpf,
        "postgres",
        "pytest_databases",
        0,
        None,
        "template",
        None,
        None,
        (),
        None,
    )
    assert next(gen) is not None
    with pytest.raises(StopIteration):
        next(gen)


def test_embedded_postgres_all_fixtures_inprocess(pytester: pytest.Pytester) -> None:
    """Verify all embedded_postgres fixtures execute in-process with mocked cluster helpers."""
    pytester.makepyfile("""
    from contextlib import contextmanager
    from pathlib import Path
    from unittest.mock import MagicMock
    import pytest
    import pytest_databases.embedded.postgres as ep_mod
    from pytest_databases.embedded.postgres import EmbeddedPostgresService, PostgresBinaries

    pytest_plugins = ["pytest_databases.embedded.postgres"]

    @pytest.fixture(autouse=True, scope="session")
    def mock_embedded(tmp_path_factory):
        d = tmp_path_factory.mktemp("pg")
        bins = PostgresBinaries(initdb=d / "initdb", postgres=d / "postgres", pg_ctl=None)
        orig_res = ep_mod.resolve_postgres_binaries
        orig_prov = ep_mod.provide_embedded_postgres_service
        orig_prep = ep_mod._prepare_database
        ep_mod.resolve_postgres_binaries = lambda *a, **kw: bins

        @contextmanager
        def _fake_provide(**kwargs):
            yield EmbeddedPostgresService(
                host="127.0.0.1",
                port=55432,
                user="postgres",
                database="postgres",
                data_dir=d,
                binaries=bins,
            )

        ep_mod.provide_embedded_postgres_service = _fake_provide
        ep_mod._prepare_database = lambda admin, **kw: admin
        yield
        ep_mod.resolve_postgres_binaries = orig_res
        ep_mod.provide_embedded_postgres_service = orig_prov
        ep_mod._prepare_database = orig_prep

    def test_fixtures(
        embedded_postgres_user,
        embedded_postgres_database,
        embedded_postgres_port,
        embedded_postgres_bin_dir,
        xdist_embedded_postgres_isolation_level,
        embedded_postgres_template_name,
        embedded_postgres_template_setup,
        embedded_postgres_template_fingerprint_sources,
        embedded_postgres_template_lock_dir,
        embedded_postgres_service,
    ):
        assert embedded_postgres_user == "postgres"
        assert embedded_postgres_database == "pytest_databases"
        assert embedded_postgres_port == 0
        assert embedded_postgres_bin_dir is None
        assert xdist_embedded_postgres_isolation_level == "template"
        assert embedded_postgres_template_name is None
        assert embedded_postgres_template_setup is None
        assert embedded_postgres_template_fingerprint_sources == ()
        assert embedded_postgres_template_lock_dir is None
        assert embedded_postgres_service.port == 55432
    """)
    result = pytester.runpytest("-p", "no:sugar", "-p", "pytest_databases")
    result.assert_outcomes(passed=1)
