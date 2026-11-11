"""Tests for PostgreSQL, pgvector, ParadeDB, and AlloyDB Omni container services."""

from __future__ import annotations

import inspect
import socket
from types import SimpleNamespace
from typing import TYPE_CHECKING, Any
from unittest.mock import MagicMock

import pytest

from pytest_databases.docker import postgres as postgres_mod
from pytest_databases.docker.postgres import (
    ExternalPostgresService,
    PostgresService,
    PostgresTemplateOptions,
    clone_template_database,
    drop_database_force,
    make_connection_string,
    provide_external_postgres_service,
    provide_postgres_connection,
    provide_postgres_service,
)
from pytest_databases.embedded import postgres as embedded_pg_mod
from pytest_databases.helpers import tcp_port_open
from tests.conftest import unwrap_fixture

if TYPE_CHECKING:
    from pathlib import Path

    from pytest_databases.types import PostgresXdistIsolationLevel


def test_plugin_imports_without_psycopg(pytester: pytest.Pytester) -> None:
    """Verify ``pytest_databases.docker.postgres`` imports cleanly when ``psycopg`` is absent."""
    pytester.makepyfile("""
import builtins

def test_import() -> None:
    original_import = builtins.__import__

    def blocked_import(name, globals=None, locals=None, fromlist=(), level=0):
        if name == "psycopg" or name.startswith("psycopg."):
            raise ModuleNotFoundError(name)
        return original_import(name, globals, locals, fromlist, level)

    builtins.__import__ = blocked_import
    try:
        import pytest_databases.docker.postgres
    finally:
        builtins.__import__ = original_import
""")

    result = pytester.runpytest_subprocess("-p", "pytest_databases", "-vv")
    result.assert_outcomes(passed=1)


@pytest.mark.parametrize(
    ("password", "expected"),
    [
        pytest.param(
            "secret",
            "dbname=pytest_databases user=postgres host=127.0.0.1 port=5432 password=secret",
            id="plain",
        ),
        pytest.param("", "dbname=pytest_databases user=postgres host=127.0.0.1 port=5432", id="empty-omitted"),
        pytest.param(
            "it's a \\secret",
            "dbname=pytest_databases user=postgres host=127.0.0.1 port=5432 password='it\\'s a \\\\secret'",
            id="quoted",
        ),
    ],
)
def test_make_connection_string(password: str, expected: str) -> None:
    """Verify ``make_connection_string`` quotes libpq values that need it and omits empty ones."""
    dsn = make_connection_string(
        host="127.0.0.1",
        port=5432,
        user="postgres",
        password=password,
        database="pytest_databases",
    )
    assert dsn == expected


def test_alloydb_omni_gcr_images(pytester: pytest.Pytester) -> None:
    """Verify AlloyDB Omni fixtures use Google Container Registry and default to version 18."""
    pytester.makepyfile("""
from pytest_databases.docker import postgres

pytest_plugins = ["pytest_databases.docker.postgres"]

def test_default_image(alloydb_omni_image: str) -> None:
    assert alloydb_omni_image == "gcr.io/alloydb-omni/alloydbomni:18"
""")
    result = pytester.runpytest_subprocess("-p", "pytest_databases")
    result.assert_outcomes(passed=1)


def test_template_database_helpers_unit() -> None:
    """Verify ``clone_template_database`` and ``drop_database_force`` issue expected ``psql`` commands."""
    calls: list[tuple[list[str], dict[str, str]]] = []

    def fake_exec_run(cmd: list[str], environment: dict[str, str]) -> Any:
        calls.append((cmd, environment))
        return SimpleNamespace(exit_code=0, output=b"")

    container = MagicMock()
    container.exec_run.side_effect = fake_exec_run
    service = PostgresService(
        host="127.0.0.1",
        port=5432,
        container=container,
        database="pytest_databases",
        user="postgres",
        password="super-secret",
    )

    cloned = service.clone_template_database("worker_clone_1")
    assert cloned == "worker_clone_1"
    assert len(calls) == 2
    assert 'CREATE DATABASE "worker_clone_1" TEMPLATE "pytest_databases";' in calls[1][0]

    service.drop_database_force("worker_clone_1")
    assert len(calls) == 4
    assert 'DROP DATABASE IF EXISTS "worker_clone_1";' in calls[3][0]


def test_template_database_invalid_identifier_raises() -> None:
    """Verify unsafe identifiers are rejected before executing ``psql``."""
    service = PostgresService(
        host="127.0.0.1",
        port=5432,
        container=MagicMock(),
        database="pytest_databases",
        user="postgres",
        password="super-secret",
    )
    with pytest.raises(ValueError, match="Invalid PostgreSQL database identifier"):
        clone_template_database(service, target_db="bad; DROP DATABASE postgres;--")
    with pytest.raises(ValueError, match="Invalid PostgreSQL database identifier"):
        drop_database_force(service, db_name="bad-name")
    with pytest.raises(ValueError, match="Invalid PostgreSQL database identifier"):
        drop_database_force(service, db_name="trailing_newline\n")
    with pytest.raises(ValueError, match="Invalid PostgreSQL database identifier"):
        drop_database_force(service, db_name="x" * 64)


def test_deprecated_postgres_connection_warns(monkeypatch: pytest.MonkeyPatch) -> None:
    """Verify ``provide_postgres_connection`` emits ``DeprecationWarning`` and lazily connects."""
    fake_conn = MagicMock()
    fake_ctx = MagicMock()
    fake_ctx.__enter__.return_value = fake_conn
    fake_ctx.__exit__.return_value = False
    fake_psycopg = SimpleNamespace(connect=MagicMock(return_value=fake_ctx))

    monkeypatch.setattr(postgres_mod.importlib, "import_module", lambda _name: fake_psycopg)

    service = PostgresService(
        host="127.0.0.1",
        port=5432,
        container=MagicMock(),
        database="pytest_databases",
        user="postgres",
        password="super-secret",
    )

    with (
        pytest.warns(DeprecationWarning, match=r"postgres_connection.*v1\.0\.0") as record,
        provide_postgres_connection(service, fixture_name="postgres_connection") as conn,
    ):
        assert conn is fake_conn

    assert len(record) == 1
    assert record[0].filename == __file__

    fake_psycopg.connect.assert_called_once_with(
        "dbname=pytest_databases user=postgres host=127.0.0.1 port=5432 password=super-secret"
    )


def test_provide_postgres_service_readiness_timeout(monkeypatch: pytest.MonkeyPatch) -> None:
    """Verify ``provide_postgres_service`` configures a 60s readiness timeout for container startup."""
    fake_container = MagicMock()
    fake_service = SimpleNamespace(host="127.0.0.1", port=5432, container=fake_container)
    run_ctx = MagicMock()
    run_ctx.__enter__.return_value = fake_service
    run_ctx.__exit__.return_value = False
    docker_service = MagicMock()
    docker_service.run.return_value = run_ctx

    monkeypatch.setattr(postgres_mod, "create_worker_database", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(postgres_mod, "get_xdist_worker_num", lambda: None)

    with provide_postgres_service(
        docker_service,
        image="gcr.io/alloydb-omni/alloydbomni:18",
        name="alloydb-omni-18",
        host="127.0.0.1",
        user="postgres",
        password="super-secret",
        xdist_postgres_isolate="database",
    ) as service:
        assert service.host == "127.0.0.1"
        assert service.port == 5432

    call_kwargs = docker_service.run.call_args.kwargs
    assert call_kwargs["timeout"] == 60
    assert call_kwargs["pause"] == pytest.approx(0.5)


@pytest.mark.parametrize(
    ("exit_code", "output", "host_port_open", "expected"),
    [
        pytest.param(0, b"1\n", True, True, id="ready"),
        pytest.param(0, b"1\n", False, False, id="host-port-not-forwarded"),
        pytest.param(2, b"", True, False, id="psql-failed"),
        pytest.param(0, b"11\n", True, False, id="unexpected-value"),
    ],
)
def test_provide_postgres_service_readiness_probes_host_port(
    monkeypatch: pytest.MonkeyPatch,
    exit_code: int,
    output: bytes,
    host_port_open: bool,
    expected: bool,
) -> None:
    """Verify readiness needs the in-container ``psql`` check and a reachable published host port."""
    fake_container = MagicMock()
    fake_container.exec_run.return_value = SimpleNamespace(exit_code=exit_code, output=output)
    fake_service = SimpleNamespace(host="127.0.0.1", port=55432, container=fake_container)
    run_ctx = MagicMock()
    run_ctx.__enter__.return_value = fake_service
    run_ctx.__exit__.return_value = False
    docker_service = MagicMock()
    docker_service.run.return_value = run_ctx
    probed: list[tuple[str, int]] = []

    def fake_tcp_port_open(host: str, port: int, timeout: float = 2.0) -> bool:
        probed.append((host, port))
        return host_port_open

    monkeypatch.setattr(postgres_mod, "create_worker_database", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(postgres_mod, "get_xdist_worker_num", lambda: None)
    monkeypatch.setattr(postgres_mod, "tcp_port_open", fake_tcp_port_open)

    with provide_postgres_service(
        docker_service,
        image="postgres:18",
        name="postgres-18",
        host="127.0.0.1",
        user="postgres",
        password="super-secret",
        xdist_postgres_isolate="database",
    ):
        check = docker_service.run.call_args.kwargs["check"]
        assert check(fake_service) is expected

    if exit_code == 0 and output.strip() == b"1":
        assert probed == [("127.0.0.1", 55432)]
    else:
        assert probed == []


def test_tcp_port_open() -> None:
    """Verify ``tcp_port_open`` reports a listening port as open and a closed port as closed."""
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as listener:
        listener.bind(("127.0.0.1", 0))
        listener.listen(1)
        open_port = listener.getsockname()[1]
        assert tcp_port_open("127.0.0.1", open_port, timeout=1.0) is True
    closed_port = _pick_free_port()
    assert tcp_port_open("127.0.0.1", closed_port, timeout=1.0) is False


POSTGRES_TEST_HELPERS = """
def run_psql(service, sql, *, database=None, tuples_only=False):
    cmd = ["psql", "-v", "ON_ERROR_STOP=1", "-h", "localhost", "-p", "5432", "-U", service.user, "-d", database or service.database]
    cmd.extend(["-tAc", sql] if tuples_only else ["-c", sql])
    result = service.container.exec_run(cmd, environment={"PGPASSWORD": service.password})
    output = result.output
    if isinstance(output, bytes):
        decoded = output.decode(errors="replace")
    elif isinstance(output, str):
        decoded = output
    else:
        decoded = b"".join(output).decode(errors="replace")
    assert result.exit_code == 0, decoded
    return decoded.strip()
"""


@pytest.mark.parametrize(
    ("service_fixture", "env_var"),
    [
        ("postgres_15_service", "POSTGRES_15_PORT"),
        ("pgvector_18_service", "PGVECTOR_18_PORT"),
        ("paradedb_18_service", "PARADEDB_18_PORT"),
        ("alloydb_omni_17_service", "ALLOYDB_OMNI_17_PORT"),
        ("alloydb_omni_18_service", "ALLOYDB_OMNI_18_PORT"),
    ],
)
def test_port_pinning_via_env(
    pytester: pytest.Pytester,
    monkeypatch: pytest.MonkeyPatch,
    service_fixture: str,
    env_var: str,
) -> None:
    """Verify host port pinning via environment variable for PostgreSQL family fixtures."""
    free_port = _pick_free_port()
    pytester.makepyfile(f"""
pytest_plugins = ["pytest_databases.docker.postgres"]

def test_pinned({service_fixture}) -> None:
    assert {service_fixture}.port == {free_port}
""")
    monkeypatch.setenv(env_var, str(free_port))
    result = pytester.runpytest_subprocess("-p", "pytest_databases")
    result.assert_outcomes(passed=1)


@pytest.mark.parametrize(
    "service_fixture",
    [
        "postgres_service",
        "postgres_12_service",
        "postgres_13_service",
        "postgres_14_service",
        "postgres_15_service",
        "postgres_16_service",
        "postgres_17_service",
        "postgres_18_service",
        "alloydb_omni_service",
        "alloydb_omni_15_service",
        "alloydb_omni_16_service",
        "alloydb_omni_17_service",
        "alloydb_omni_18_service",
        "pgvector_service",
        "pgvector_13_service",
        "pgvector_14_service",
        "pgvector_15_service",
        "pgvector_16_service",
        "pgvector_17_service",
        "pgvector_18_service",
        "paradedb_service",
        "paradedb_15_service",
        "paradedb_16_service",
        "paradedb_17_service",
        "paradedb_18_service",
    ],
)
def test_service_fixture(pytester: pytest.Pytester, service_fixture: str) -> None:
    """Verify each PostgreSQL family service fixture starts and responds to ``psql``."""
    pytester.makepyfile(f"""
from pytest_databases.docker.postgres import PostgresService

pytest_plugins = ["pytest_databases.docker.postgres"]

{POSTGRES_TEST_HELPERS}

def test({service_fixture}: PostgresService) -> None:
    assert run_psql({service_fixture}, "SELECT 1", tuples_only=True) == "1"
""")

    result = pytester.runpytest_subprocess("-p", "pytest_databases")
    result.assert_outcomes(passed=1)


@pytest.mark.parametrize(
    "service_fixture",
    [
        "postgres_service",
        "postgres_18_service",
        "alloydb_omni_service",
        "pgvector_service",
        "paradedb_service",
    ],
)
def test_startup_table_roundtrip(pytester: pytest.Pytester, service_fixture: str) -> None:
    """Verify table creation and query round-trip across default PostgreSQL family services."""
    pytester.makepyfile(f"""
from pytest_databases.docker.postgres import PostgresService

pytest_plugins = ["pytest_databases.docker.postgres"]

{POSTGRES_TEST_HELPERS}

def test({service_fixture}: PostgresService) -> None:
    run_psql({service_fixture}, "CREATE TABLE IF NOT EXISTS simple_table AS SELECT 1 AS x")
    assert run_psql({service_fixture}, "SELECT x FROM simple_table", tuples_only=True) == "1"
""")

    result = pytester.runpytest_subprocess("-p", "pytest_databases")
    result.assert_outcomes(passed=1)


def test_xdist_isolate_db(pytester: pytest.Pytester) -> None:
    """Verify ``database`` isolation creates distinct databases per worker on a shared container."""
    pytester.makepyfile(f"""
from pytest_databases.docker.postgres import PostgresService

pytest_plugins = ["pytest_databases.docker.postgres"]

{POSTGRES_TEST_HELPERS}

def test_one(postgres_service: PostgresService) -> None:
    run_psql(postgres_service, "CREATE TABLE foo AS SELECT 1")

def test_two(postgres_service: PostgresService) -> None:
    run_psql(postgres_service, "CREATE TABLE foo AS SELECT 1")
""")

    result = pytester.runpytest_subprocess("-p", "pytest_databases", "-n", "2")
    result.assert_outcomes(passed=2)


def test_xdist_isolate_server(pytester: pytest.Pytester) -> None:
    """Verify ``server`` isolation starts separate PostgreSQL containers per worker."""
    pytester.makepyfile(f"""
import pytest
from pytest_databases.docker.postgres import PostgresService

pytest_plugins = ["pytest_databases.docker.postgres"]

@pytest.fixture(scope="session")
def xdist_postgres_isolation_level():
    return "server"

{POSTGRES_TEST_HELPERS}

def test_one(postgres_service: PostgresService) -> None:
    run_psql(postgres_service, "CREATE DATABASE foo", database="postgres")

def test_two(postgres_service: PostgresService) -> None:
    run_psql(postgres_service, "CREATE DATABASE foo", database="postgres")
""")

    result = pytester.runpytest_subprocess("-p", "pytest_databases", "-n", "2")
    result.assert_outcomes(passed=2)


def _pick_free_port() -> int:
    """Bind an ephemeral loopback socket and return its port number."""
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.bind(("127.0.0.1", 0))
        return int(sock.getsockname()[1])


class RecordingContainer:
    """Fake container that records every ``psql`` statement and answers from a callback."""

    def __init__(self, respond: Any = None) -> None:
        self.statements: list[tuple[str, str]] = []
        self._respond = respond

    def exec_run(self, cmd: list[str], environment: dict[str, str]) -> Any:
        database = cmd[cmd.index("-d") + 1]
        sql = cmd[-1]
        self.statements.append((database, sql))
        if self._respond is not None:
            return self._respond(database, sql)
        return SimpleNamespace(exit_code=0, output=b"1\n" if sql == "SELECT 1" else b"")


def _template_service(container: RecordingContainer) -> PostgresService:
    return PostgresService(
        host="127.0.0.1",
        port=5432,
        container=container,  # type: ignore[arg-type]
        database="postgres",
        user="postgres",
        password="super-secret",
    )


def _no_template_yet(database: str, sql: str) -> Any:
    if "datistemplate = true" in sql:
        return SimpleNamespace(exit_code=0, output=b"")
    return SimpleNamespace(exit_code=0, output=b"1\n" if sql == "SELECT 1" else b"")


def test_compute_fingerprint(tmp_path: Path) -> None:
    """Verify ``compute_fingerprint`` is deterministic for text and tracks directory contents."""
    fp1 = PostgresService.compute_fingerprint("CREATE TABLE t1 (id int);")
    assert fp1 == PostgresService.compute_fingerprint("CREATE TABLE t1 (id int);")
    assert fp1 != PostgresService.compute_fingerprint("CREATE TABLE t2 (id int);")
    assert len(fp1) == 12

    (tmp_path / "01_init.sql").write_text("CREATE TABLE users (id int);")
    (tmp_path / "02_seed.sql").write_text("INSERT INTO users VALUES (1);")
    dir_fp1 = PostgresService.compute_fingerprint(tmp_path)
    assert dir_fp1 == PostgresService.compute_fingerprint(tmp_path)
    (tmp_path / "03_more.sql").write_text("INSERT INTO users VALUES (2);")
    assert PostgresService.compute_fingerprint(tmp_path) != dir_fp1


def test_ensure_template_fast_path(tmp_path: Path) -> None:
    """Verify ``ensure_template`` reuses an existing template without staging anything."""
    container = RecordingContainer(lambda _database, _sql: SimpleNamespace(exit_code=0, output=b"1\n"))

    assert _template_service(container).ensure_template("my_template", lock_dir=tmp_path) == "my_template"
    assert container.statements == [
        ("postgres", "SELECT 1 FROM pg_database WHERE datname = 'my_template' AND datistemplate = true;")
    ]


def test_ensure_template_lifecycle(tmp_path: Path) -> None:
    """Verify ``ensure_template`` builds in staging, runs SQL then the callable, marks, and renames."""
    container = RecordingContainer(_no_template_yet)
    service = _template_service(container)
    staged: list[str] = []
    setup_sql = "CREATE TABLE test_table (id serial);"

    template = service.ensure_template(
        "my_template",
        setup_fn=lambda staging_svc: staged.append(staging_svc.database),
        setup_sql=setup_sql,
        lock_dir=tmp_path,
    )

    digest = PostgresService.compute_fingerprint(setup_sql.encode())
    assert template == f"my_template_{digest}"
    staging = f"{template}_staging"
    assert staged == [staging]
    executed = [sql for _, sql in container.statements]
    ordered = [
        f'CREATE DATABASE "{staging}";',
        setup_sql,
        f'ALTER DATABASE "{staging}" WITH is_template = true allow_connections = false;',
        f'ALTER DATABASE "{staging}" RENAME TO "{template}";',
    ]
    positions = [executed.index(sql) for sql in ordered]
    assert positions == sorted(positions)
    assert (staging, setup_sql) in container.statements
    assert list(tmp_path.glob("pytest_databases_tpl_127_0_0_1_5432_*.lock"))


@pytest.mark.parametrize(
    ("first", "second", "same"),
    [
        pytest.param("CREATE TABLE a (id int);", "CREATE TABLE a (id int);", True, id="unchanged-sql"),
        pytest.param("CREATE TABLE a (id int);", "CREATE TABLE b (id int);", False, id="changed-sql"),
    ],
)
def test_ensure_template_name_tracks_setup_sql(tmp_path: Path, first: str, second: str, same: bool) -> None:
    """Verify a changed ``setup_sql`` produces a new template name instead of reusing a stale template."""
    service = _template_service(RecordingContainer(_no_template_yet))

    first_name = service.ensure_template(setup_sql=first, lock_dir=tmp_path)
    second_name = service.ensure_template(setup_sql=second, lock_dir=tmp_path)

    assert first_name.startswith("pytest_databases_template_")
    assert (first_name == second_name) is same


def test_ensure_template_hashes_setup_file_contents(tmp_path: Path) -> None:
    """Verify ``.sql`` paths are executed by content and their content is part of the template name."""
    container = RecordingContainer(_no_template_yet)
    service = _template_service(container)
    script = tmp_path / "schema.sql"
    script.write_text("CREATE TABLE from_file (id int);")

    first = service.ensure_template(setup_sql=[script], lock_dir=tmp_path)
    script.write_text("CREATE TABLE from_file (id bigint);")
    second = service.ensure_template(setup_sql=[script], lock_dir=tmp_path)

    assert first != second
    assert (f"{first}_staging", "CREATE TABLE from_file (id int);") in container.statements
    assert (f"{second}_staging", "CREATE TABLE from_file (id bigint);") in container.statements


def test_ensure_template_drops_staging_when_setup_fails(tmp_path: Path) -> None:
    """Verify a failing setup statement raises and drops the half-built staging database."""

    def respond(database: str, sql: str) -> Any:
        if sql.startswith("CREATE TABLE"):
            return SimpleNamespace(exit_code=1, output=b"ERROR: syntax error")
        return _no_template_yet(database, sql)

    container = RecordingContainer(respond)

    with pytest.raises(RuntimeError, match="syntax error"):
        _template_service(container).ensure_template("tpl", setup_sql="CREATE TABLE broken (", lock_dir=tmp_path)

    drops = [sql for _, sql in container.statements if sql.startswith("DROP DATABASE")]
    assert drops[-1].startswith('DROP DATABASE IF EXISTS "tpl_') and drops[-1].endswith('_staging";')


def test_create_worker_database_from_template_sends_single_create() -> None:
    """Verify the clone is one ``CREATE DATABASE ... TEMPLATE`` statement with no follow-up ``ALTER``."""
    container = RecordingContainer()

    worker_db = _template_service(container).create_worker_database_from_template("app_template", "worker_0")

    assert worker_db == "worker_0"
    executed = [sql for _, sql in container.statements]
    assert 'CREATE DATABASE "worker_0" TEMPLATE "app_template";' in executed
    assert not any(sql.startswith("ALTER DATABASE") for sql in executed)
    assert container.statements[-1] == ("worker_0", "SELECT 1")


def test_sweep_worker_databases_escapes_prefix_and_skips_staging() -> None:
    """Verify the sweep treats ``_`` literally, skips staging and own databases, and drops the rest."""

    def respond(database: str, sql: str) -> Any:
        if sql.startswith("SELECT datname FROM pg_database"):
            return SimpleNamespace(exit_code=0, output=b"worker_1\nworker_2\npostgres\n")
        return SimpleNamespace(exit_code=0, output=b"")

    container = RecordingContainer(respond)

    assert _template_service(container).sweep_worker_databases(prefix="worker_") == ["worker_1", "worker_2"]

    query = container.statements[0][1]
    assert "LIKE 'worker\\_%' ESCAPE '\\'" in query
    assert "NOT LIKE '%\\_staging' ESCAPE '\\'" in query
    assert "datistemplate = false" in query
    executed = [sql for _, sql in container.statements]
    assert 'DROP DATABASE IF EXISTS "worker_1";' in executed
    assert 'DROP DATABASE IF EXISTS "worker_2";' in executed
    assert 'DROP DATABASE IF EXISTS "postgres";' not in executed


@pytest.mark.parametrize(
    ("worker_num", "expected_db"),
    [pytest.param(None, "pytest_databases", id="no-xdist"), pytest.param(1, "pytest_databases_1", id="xdist")],
)
def test_provide_postgres_service_template_isolation(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, worker_num: int | None, expected_db: str
) -> None:
    """Verify ``"template"`` isolation builds the configured template and clones the service database from it."""
    container = RecordingContainer(_no_template_yet)
    fake_service = SimpleNamespace(host="127.0.0.1", port=5432, container=container)
    run_ctx = MagicMock()
    run_ctx.__enter__.return_value = fake_service
    run_ctx.__exit__.return_value = False
    docker_service = MagicMock()
    docker_service.run.return_value = run_ctx
    monkeypatch.setattr(postgres_mod, "get_xdist_worker_num", lambda: worker_num)
    setup_sql = "CREATE TABLE users (id int);"

    with provide_postgres_service(
        docker_service,
        image="postgres:18",
        name="postgres",
        host="127.0.0.1",
        user="postgres",
        password="super-secret",
        xdist_postgres_isolate="template",
        template=PostgresTemplateOptions(name="my_custom_tpl", setup=setup_sql, lock_dir=tmp_path),
    ) as service:
        assert service.database == expected_db

    template = f"my_custom_tpl_{PostgresService.compute_fingerprint(setup_sql.encode())}"
    executed = [sql for _, sql in container.statements]
    assert f'CREATE DATABASE "{expected_db}" TEMPLATE "{template}";' in executed
    assert (f"{template}_staging", setup_sql) in container.statements
    assert docker_service.run.call_args.kwargs["transient"] is False


@pytest.mark.parametrize(
    "fixture_name",
    [
        name
        for name in postgres_mod.__all__
        if name.endswith("_service") and name not in {"provide_postgres_service", "provide_external_postgres_service"}
    ],
)
def test_family_services_forward_template_options(fixture_name: str) -> None:
    """Verify every PostgreSQL family service fixture requests ``postgres_template_options``."""
    parameters = inspect.signature(unwrap_fixture(getattr(postgres_mod, fixture_name))).parameters
    assert "postgres_template_options" in parameters, fixture_name


def test_family_services_template_count() -> None:
    """Verify all PostgreSQL family service fixtures remain covered."""
    service_fixtures = [
        name
        for name in postgres_mod.__all__
        if name.endswith("_service") and name not in {"provide_postgres_service", "provide_external_postgres_service"}
    ]
    assert len(service_fixtures) == 27


def test_xdist_isolate_template(pytester: pytest.Pytester) -> None:
    """Verify ``"template"`` isolation clones a seeded template into a separate database for each worker."""
    pytester.makepyfile(f"""
import pytest
from pytest_databases.docker.postgres import PostgresService

pytest_plugins = ["pytest_databases.docker.postgres"]

@pytest.fixture(scope="session")
def xdist_postgres_isolation_level():
    return "template"

@pytest.fixture(scope="session")
def postgres_template_setup():
    return [
        "CREATE TABLE users (id serial PRIMARY KEY, name text NOT NULL)",
        "INSERT INTO users (name) VALUES ('alice'), ('bob')",
    ]

{POSTGRES_TEST_HELPERS}

def _check(service: PostgresService) -> None:
    assert run_psql(service, "SELECT current_database()", tuples_only=True) == service.database
    assert run_psql(service, "SELECT count(*) FROM users", tuples_only=True) == "2"
    run_psql(service, "INSERT INTO users (name) VALUES ('carol')")
    assert run_psql(service, "SELECT count(*) FROM users", tuples_only=True) == "3"
    templates = run_psql(
        service,
        "SELECT datname FROM pg_database WHERE datistemplate AND starts_with(datname, 'pytest_databases_template_')",
        database="postgres",
        tuples_only=True,
    )
    assert len(templates.splitlines()) == 1, templates

def test_one(postgres_service: PostgresService) -> None:
    _check(postgres_service)

def test_two(postgres_service: PostgresService) -> None:
    _check(postgres_service)
""")

    result = pytester.runpytest_subprocess("-p", "pytest_databases", "-n", "2")
    result.assert_outcomes(passed=2)


def test_create_worker_database_and_provide_postgres_xdist_modes(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Verify create_worker_database retry/verification failure and provide_postgres_service xdist modes."""
    monkeypatch.setattr(postgres_mod.time, "sleep", lambda _s: None)
    container = MagicMock()

    container.exec_run.return_value = SimpleNamespace(exit_code=1, output=b"booting")
    with pytest.raises(RuntimeError, match="failed after 10 attempts"):
        postgres_mod.create_worker_database(container, user="postgres", password="p", db_name="w1")

    container.exec_run.side_effect = [
        SimpleNamespace(exit_code=0, output=b""),
        SimpleNamespace(exit_code=1, output=b"verify failed"),
    ]
    with pytest.raises(RuntimeError, match="Verification SELECT against 'w1' failed"):
        postgres_mod.create_worker_database(container, user="postgres", password="p", db_name="w1")

    container.exec_run.side_effect = [
        SimpleNamespace(exit_code=1, output=b"already exists"),
        SimpleNamespace(exit_code=0, output=b"1\n"),
    ]
    postgres_mod.create_worker_database(container, user="postgres", password="p", db_name="w1")

    container.exec_run.side_effect = None
    container.exec_run.return_value = SimpleNamespace(exit_code=0, output=b"1\n")
    fake_service = SimpleNamespace(host="127.0.0.1", port=5432, container=container)
    run_ctx = MagicMock()
    run_ctx.__enter__.return_value = fake_service
    run_ctx.__exit__.return_value = False
    docker_service = MagicMock()
    docker_service.run.return_value = run_ctx
    monkeypatch.setattr(postgres_mod, "get_xdist_worker_num", lambda: 2)

    with provide_postgres_service(
        docker_service,
        image="postgres:18",
        name="postgres",
        host="127.0.0.1",
        user="postgres",
        password="p",
        xdist_postgres_isolate="database",
    ) as svc_db:
        assert svc_db.database == "pytest_databases_2"

    with provide_postgres_service(
        docker_service,
        image="postgres:18",
        name="postgres",
        host="127.0.0.1",
        user="postgres",
        password="p",
        xdist_postgres_isolate="server",
    ) as svc_srv:
        assert svc_srv.database == "pytest_databases"
    assert docker_service.run.call_args.kwargs["transient"] is True


def test_postgres_all_fixtures_inprocess(pytester: pytest.Pytester) -> None:
    """Exercise all PostgreSQL, AlloyDB Omni, TimescaleDB, pgvector, ParadeDB, and SpiceDB fixtures in-process."""
    pytester.makepyfile("""
    from contextlib import contextmanager
    from types import SimpleNamespace
    from unittest.mock import MagicMock, patch
    import pytest
    from pytest_databases.docker import postgres as postgres_mod
    from pytest_databases.docker.postgres import ExternalPostgresService, PostgresService

    pytest_plugins = ["pytest_databases.docker.postgres"]

    @pytest.fixture(scope="session")
    def docker_service():
        svc = MagicMock()
        ctx = MagicMock()
        ctx.__enter__.return_value = SimpleNamespace(host="127.0.0.1", port=50051, container=MagicMock())
        ctx.__exit__.return_value = False
        svc.run.return_value = ctx
        return svc

    @contextmanager
    def _fake_provide_service(*args, **kwargs):
        yield PostgresService(
            host=kwargs.get("host", "127.0.0.1"),
            port=kwargs.get("port") or 5432,
            container=MagicMock(),
            database=kwargs.get("database", "pytest_databases"),
            user=kwargs.get("user", "postgres"),
            password=kwargs.get("password", "super-secret"),
        )

    @contextmanager
    def _fake_provide_external(host, port=5432, **kwargs):
        yield ExternalPostgresService(
            host=host,
            port=port,
            database=kwargs.get("database", "pytest_databases"),
            user=kwargs.get("user", "postgres"),
            password=kwargs.get("password", ""),
        )

    @contextmanager
    def _fake_provide_conn(service, *, fixture_name):
        yield MagicMock(service=service, fixture_name=fixture_name)

    def test_all_fixtures(request):
        with (
            patch.object(postgres_mod, "provide_postgres_service", _fake_provide_service),
            patch.object(postgres_mod, "provide_external_postgres_service", _fake_provide_external),
            patch.object(postgres_mod, "provide_postgres_connection", _fake_provide_conn),
        ):
            for name in postgres_mod.__all__:
                if name.endswith(("_port", "_image", "_service", "_connection")) or name.startswith(
                    ("postgres_", "xdist_")
                ):
                    if name in {
                        "ExternalPostgresService",
                        "PostgresService",
                        "PostgresTemplateOptions",
                        "postgres_external_service",
                        "postgres_responsive",
                        "provide_external_postgres_service",
                        "provide_postgres_service",
                        "provide_postgres_connection",
                    }:
                        continue
                    val = request.getfixturevalue(name)
                    if name.endswith("_port") or name == "postgres_external_host":
                        assert val is None
            with pytest.raises(pytest.skip.Exception):
                request.getfixturevalue("postgres_external_service")
    """)
    result = pytester.runpytest("-p", "no:sugar", "-p", "pytest_databases")
    result.assert_outcomes(passed=1)


def test_provide_postgres_service_env_resources_and_init_sql(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    """Verify custom user/database env forwarding, container resource options, init_sql, and service helpers."""
    monkeypatch.setattr(postgres_mod, "get_xdist_worker_num", lambda: None)
    monkeypatch.setenv("TMPDIR", str(tmp_path))
    monkeypatch.setattr(postgres_mod.tempfile, "tempdir", str(tmp_path))

    sql_file = tmp_path / "ext.sql"
    sql_file.write_text("CREATE EXTENSION IF NOT EXISTS pg_stat_statements;", encoding="utf-8")

    container = RecordingContainer()
    container.id = "pgcontainer123456"  # type: ignore[attr-defined]
    fake_service = SimpleNamespace(host="127.0.0.1", port=15432, container=container)
    run_ctx = MagicMock()
    run_ctx.__enter__.return_value = fake_service
    run_ctx.__exit__.return_value = False
    docker_service = MagicMock()
    docker_service.run.return_value = run_ctx

    cmd = ["postgres", "-c", "shared_preload_libraries=pg_stat_statements"]
    with provide_postgres_service(
        docker_service,
        image="postgres:18",
        name="postgres-18",
        host="127.0.0.1",
        user="custom_admin",
        password="pw",
        xdist_postgres_isolate="database",
        database="metrics_db",
        command=cmd,
        env={"PGAPPNAME": "collector_suite"},
        shm_size="256m",
        mem_limit="1g",
        volumes=["/host/conf:/etc/pg:ro"],
        init_sql=[sql_file, "CREATE TABLE t (id int);"],
    ) as svc:
        assert svc.user == "custom_admin"
        assert svc.database == "metrics_db"
        assert "user=custom_admin" in svc.dsn
        assert svc.connection_config == {
            "host": "127.0.0.1",
            "port": 15432,
            "user": "custom_admin",
            "database": "metrics_db",
            "password": "pw",
        }
        code, out = svc.exec_sql("SELECT 1", tuples_only=True)
        assert (code, out) == (0, b"1\n")

    run_kwargs = docker_service.run.call_args.kwargs
    assert run_kwargs["env"] == {
        "POSTGRES_USER": "custom_admin",
        "POSTGRES_DB": "metrics_db",
        "POSTGRES_PASSWORD": "pw",
        "PGAPPNAME": "collector_suite",
    }
    assert run_kwargs["command"] == cmd
    assert run_kwargs["shm_size"] == "256m"
    assert run_kwargs["mem_limit"] == "1g"
    assert run_kwargs["volumes"] == ["/host/conf:/etc/pg:ro"]
    assert ("metrics_db", "CREATE EXTENSION IF NOT EXISTS pg_stat_statements;") in container.statements
    assert ("metrics_db", "CREATE TABLE t (id int);") in container.statements

    before_count = sum(1 for _, stmt in container.statements if "CREATE TABLE t" in stmt)
    with provide_postgres_service(
        docker_service,
        image="postgres:18",
        name="postgres-18",
        host="127.0.0.1",
        user="custom_admin",
        password="",
        xdist_postgres_isolate="database",
        database="metrics_db",
        env={"POSTGRES_HOST_AUTH_METHOD": "trust"},
        init_sql=[sql_file, "CREATE TABLE t (id int);"],
    ) as trust_svc:
        assert "password" not in trust_svc.connection_config
    assert "POSTGRES_PASSWORD" not in docker_service.run.call_args.kwargs["env"]
    after_count = sum(1 for _, stmt in container.statements if "CREATE TABLE t" in stmt)
    assert after_count == before_count == 1


@pytest.mark.parametrize(
    ("user", "database", "init_fail", "exc_type", "pattern"),
    [
        ("", "pytest_databases", False, ValueError, "user must be non-empty"),
        ("postgres", "bad-name", False, ValueError, "Invalid PostgreSQL database identifier"),
        ("postgres", "pytest_databases", True, RuntimeError, "PostgreSQL init_sql failed"),
    ],
)
def test_provide_postgres_service_error_branches(
    monkeypatch: pytest.MonkeyPatch,
    user: str,
    database: str,
    init_fail: bool,
    exc_type: type[Exception],
    pattern: str,
) -> None:
    """Verify provide_postgres_service rejects invalid parameters and surfaces init_sql failures."""
    monkeypatch.setattr(postgres_mod, "get_xdist_worker_num", lambda: None)

    def _respond(_db: str, sql: str) -> Any:
        if init_fail and "BROKEN" in sql:
            return SimpleNamespace(exit_code=1, output=b"ERROR: syntax error")
        return SimpleNamespace(exit_code=0, output=b"1\n" if sql == "SELECT 1" else b"")

    container = RecordingContainer(_respond)
    run_ctx = MagicMock()
    run_ctx.__enter__.return_value = SimpleNamespace(host="127.0.0.1", port=5432, container=container)
    run_ctx.__exit__.return_value = False
    docker_service = MagicMock()
    docker_service.run.return_value = run_ctx

    with (
        pytest.raises(exc_type, match=pattern),
        provide_postgres_service(
            docker_service,
            image="postgres:18",
            name="pg",
            host="127.0.0.1",
            user=user,
            password="pw",
            xdist_postgres_isolate="database",
            database=database,
            init_sql="BROKEN SQL" if init_fail else None,
        ),
    ):
        pass


@pytest.mark.parametrize(
    ("kwargs", "exc_type", "pattern"),
    [
        ({"user": ""}, ValueError, "user must be non-empty"),
        ({"xdist_postgres_isolate": "server"}, ValueError, "not supported for external"),
        ({"timeout": 0}, ValueError, "strictly greater than zero"),
        ({"pause": 0}, ValueError, "strictly greater than zero"),
        ({"timeout": 0.05, "pause": 0.01}, TimeoutError, "was not ready within"),
    ],
)
def test_provide_external_postgres_service_validation_and_timeout(
    kwargs: dict[str, Any],
    exc_type: type[Exception],
    pattern: str,
) -> None:
    """Verify provide_external_postgres_service validates parameters and raises TimeoutError when unreachable."""
    free_port = _pick_free_port()
    with pytest.raises(exc_type, match=pattern), provide_external_postgres_service("127.0.0.1", free_port, **kwargs):
        pass


def _try_resolve_local_pg() -> embedded_pg_mod.PostgresBinaries | None:
    try:
        return embedded_pg_mod.resolve_postgres_binaries()
    except FileNotFoundError:
        return None


_LOCAL_PG_BINARIES = _try_resolve_local_pg()


def _bootstrap_scram_cluster(data_dir: Path) -> tuple[Any, int]:
    """Initialize and launch a temporary local PostgreSQL cluster configured with SCRAM-SHA-256."""
    assert _LOCAL_PG_BINARIES is not None
    embedded_pg_mod.init_cluster(_LOCAL_PG_BINARIES, data_dir, user="postgres")
    proc, port = embedded_pg_mod.start_cluster(
        _LOCAL_PG_BINARIES, data_dir, host="127.0.0.1", port=0, startup_timeout=30.0
    )
    boot = ExternalPostgresService(host="127.0.0.1", port=port, database="postgres", user="postgres")
    code, out = boot.exec_sql(
        "SET password_encryption = 'scram-sha-256'; CREATE ROLE ext_admin WITH SUPERUSER LOGIN PASSWORD 'S3cret!Pass';"
    )
    if code != 0:
        embedded_pg_mod.stop_cluster(_LOCAL_PG_BINARIES, data_dir, proc)
        raise AssertionError(out.decode(errors="replace"))
    (data_dir / "pg_hba.conf").write_text("host all all 127.0.0.1/32 scram-sha-256\n", encoding="utf-8")
    reload_code, reload_out = boot.exec_sql("SELECT pg_reload_conf();")
    if reload_code != 0 and b"authentication" not in reload_out.lower():
        embedded_pg_mod.stop_cluster(_LOCAL_PG_BINARIES, data_dir, proc)
        raise AssertionError(reload_out.decode(errors="replace"))
    return proc, port


@pytest.mark.skipif(_LOCAL_PG_BINARIES is None, reason="Local PostgreSQL server binaries are not installed")
@pytest.mark.parametrize("isolate_mode", ["database", "template"])
def test_provide_external_postgres_service_live_scram_and_template(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    isolate_mode: PostgresXdistIsolationLevel,
) -> None:
    """Verify ExternalPostgresService authenticates via real SCRAM-SHA-256 and provisions isolated databases."""
    assert _LOCAL_PG_BINARIES is not None
    data_dir = tmp_path / "pgdata"
    proc, port = _bootstrap_scram_cluster(data_dir)
    try:
        bad_code, _bad_out = ExternalPostgresService(
            host="127.0.0.1",
            port=port,
            database="postgres",
            user="ext_admin",
            password="wrong-password",
        ).exec_sql("SELECT 1")
        assert bad_code != 0

        monkeypatch.setattr(postgres_mod, "get_xdist_worker_num", lambda: 1)
        tpl = PostgresTemplateOptions(
            name="ext_tpl",
            setup="CREATE TABLE seeded (v int); INSERT INTO seeded VALUES (42);",
            lock_dir=tmp_path,
        )
        init_file = tmp_path / "init.sql"
        init_file.write_text("CREATE TABLE boot_marker (label text); INSERT INTO boot_marker VALUES ('ok');")

        with provide_external_postgres_service(
            "127.0.0.1",
            port,
            user="ext_admin",
            password="S3cret!Pass",
            database="ext_suite",
            xdist_postgres_isolate=isolate_mode,
            template=tpl if isolate_mode == "template" else None,
            init_sql=init_file,
            lock_dir=tmp_path,
            timeout=15.0,
        ) as ext_svc:
            assert ext_svc.database == "ext_suite_1"
            assert "password=S3cret!Pass" in ext_svc.dsn
            assert ext_svc.connection_config["password"] == "S3cret!Pass"
            q_code, q_out = ext_svc.exec_sql("SELECT label FROM boot_marker")
            assert (q_code, q_out.strip()) == (0, b"ok")
            if isolate_mode == "template":
                t_code, t_out = ext_svc.exec_sql("SELECT v FROM seeded")
                assert (t_code, t_out.strip()) == (0, b"42")
    finally:
        embedded_pg_mod.stop_cluster(_LOCAL_PG_BINARIES, data_dir, proc)
