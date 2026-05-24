from __future__ import annotations

import socket

import pytest


def _pick_free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.bind(("127.0.0.1", 0))
        return sock.getsockname()[1]


def test_plugin_imports_without_psycopg(pytester: pytest.Pytester) -> None:
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


POSTGRES_TEST_HELPERS = """
def run_psql(service, sql, *, database=None, tuples_only=False):
    cmd = ["psql", "-v", "ON_ERROR_STOP=1", "-U", service.user, "-d", database or service.database]
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
    ],
)
def test_port_pinning_via_env(
    pytester: pytest.Pytester,
    monkeypatch: pytest.MonkeyPatch,
    service_fixture: str,
    env_var: str,
) -> None:
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
