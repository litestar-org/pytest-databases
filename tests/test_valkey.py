from __future__ import annotations

import pytest


def test_plugin_imports_without_valkey(pytester: pytest.Pytester) -> None:
    pytester.makepyfile("""
    import builtins

    def test_import() -> None:
        original_import = builtins.__import__

        def blocked_import(name, globals=None, locals=None, fromlist=(), level=0):
            if name == "valkey" or name.startswith("valkey."):
                raise ModuleNotFoundError(name)
            return original_import(name, globals, locals, fromlist, level)

        builtins.__import__ = blocked_import
        try:
            import pytest_databases.docker.valkey
        finally:
            builtins.__import__ = original_import
    """)

    result = pytester.runpytest_subprocess("-p", "pytest_databases", "-vv")
    result.assert_outcomes(passed=1)


VALKEY_TEST_HELPERS = """
def run_valkey(service, *args, db=None):
    if db is None:
        db = service.db
    result = service.container.exec_run([
        "valkey-cli",
        "-h",
        "localhost",
        "-p",
        "6379",
        "-n",
        str(db),
        *args,
    ])
    assert result.exit_code == 0, result.output.decode(errors="replace")
    output = result.output
    if isinstance(output, bytes):
        return output.decode().strip()
    if isinstance(output, str):
        return output.strip()
    return b"".join(output).decode().strip()
"""


@pytest.fixture(params=[pytest.param("valkey_service", id="valkey")])
def valkey_compatible_service(request: pytest.FixtureRequest) -> str:
    return request.param


def test_default_no_xdist(pytester: pytest.Pytester, valkey_compatible_service: str) -> None:
    pytester.makepyfile(f"""
from pytest_databases.docker.valkey import ValkeyService

pytest_plugins = ["pytest_databases.docker.valkey"]

{VALKEY_TEST_HELPERS}

def test_valkey_service({valkey_compatible_service}: ValkeyService) -> None:
    assert run_valkey({valkey_compatible_service}, "PING") == "PONG"
""")
    result = pytester.runpytest_subprocess("-p", "pytest_databases")
    result.assert_outcomes(passed=1)


def test_xdist_isolate_database(pytester: pytest.Pytester, valkey_compatible_service: str) -> None:
    pytester.makepyfile(f"""
from pytest_databases.docker.valkey import ValkeyService
from pytest_databases.helpers import get_xdist_worker_num

pytest_plugins = ["pytest_databases.docker.valkey"]

{VALKEY_TEST_HELPERS}

def test_one({valkey_compatible_service}: ValkeyService) -> None:
    assert run_valkey({valkey_compatible_service}, "PING") == "PONG"
    assert {valkey_compatible_service}.db == get_xdist_worker_num()


def test_two({valkey_compatible_service}: ValkeyService) -> None:
    assert run_valkey({valkey_compatible_service}, "GET", "one") in ("", "(nil)")
    assert run_valkey({valkey_compatible_service}, "SET", "one", "1") == "OK"
    assert {valkey_compatible_service}.db == get_xdist_worker_num()
""")
    result = pytester.runpytest_subprocess("-p", "pytest_databases", "-n", "2")
    result.assert_outcomes(passed=2)


def test_xdist_isolate_server(pytester: pytest.Pytester, valkey_compatible_service: str) -> None:
    pytester.makepyfile(f"""
import pytest
from pytest_databases.docker.valkey import ValkeyService

pytest_plugins = ["pytest_databases.docker.valkey"]


@pytest.fixture(scope="session")
def xdist_valkey_isolation_level():
    return "server"

{VALKEY_TEST_HELPERS}

def test_one({valkey_compatible_service}: ValkeyService) -> None:
    assert run_valkey({valkey_compatible_service}, "PING") == "PONG"
    assert {valkey_compatible_service}.db == 0


def test_two({valkey_compatible_service}: ValkeyService) -> None:
    assert run_valkey({valkey_compatible_service}, "GET", "one") in ("", "(nil)")
    assert run_valkey({valkey_compatible_service}, "SET", "one", "1") == "OK"
    assert {valkey_compatible_service}.db == 0
""")
    result = pytester.runpytest_subprocess("-p", "pytest_databases", "-n", "2")
    result.assert_outcomes(passed=2)
