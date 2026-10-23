"""Tests for PostgreSQL, pgvector, ParadeDB, and AlloyDB Omni container services."""

from __future__ import annotations

import socket
from types import SimpleNamespace
from typing import Any
from unittest.mock import MagicMock

import pytest

from pytest_databases.docker import postgres as postgres_mod
from pytest_databases.docker.postgres import (
    PostgresService,
    clone_template_database,
    drop_database_force,
    make_connection_string,
    provide_postgres_connection,
)


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


def test_make_connection_string() -> None:
    """Verify ``make_connection_string`` formats a standard libpq DSN."""
    dsn = make_connection_string(
        host="127.0.0.1",
        port=5432,
        user="postgres",
        password="secret",
        database="pytest_databases",
    )
    assert dsn == "dbname=pytest_databases user=postgres host=127.0.0.1 port=5432 password=secret"


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
        pytest.deprecated_call(match="postgres_connection"),
        provide_postgres_connection(service, fixture_name="postgres_connection") as conn,
    ):
        assert conn is fake_conn

    fake_psycopg.connect.assert_called_once_with(
        "dbname=pytest_databases user=postgres host=127.0.0.1 port=5432 password=super-secret"
    )


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
