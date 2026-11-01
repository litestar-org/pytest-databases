"""Tests for Valkey container service fixtures."""

from __future__ import annotations

from contextlib import contextmanager
from typing import TYPE_CHECKING
from unittest.mock import MagicMock, patch

from pytest_databases.docker.valkey import provide_valkey_service
from pytest_databases.types import ServiceContainer

if TYPE_CHECKING:
    from collections.abc import Generator

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


def test_provide_valkey_service_shares_container_for_database_isolation() -> None:
    captured_names: list[str] = []

    class FakeDockerService:
        @contextmanager
        def run(self, image: str, **kwargs: object) -> Generator[ServiceContainer, None, None]:
            _ = image
            captured_names.append(str(kwargs["name"]))
            yield ServiceContainer(host="127.0.0.1", port=6379, container=MagicMock())

    fake_docker = FakeDockerService()
    with (
        patch("pytest_databases.docker.valkey.get_xdist_worker_num", return_value=0),
        provide_valkey_service(fake_docker, "valkey/valkey:latest", "database") as svc_0,  # type: ignore[arg-type]
    ):
        assert svc_0.db == 0
    with (
        patch("pytest_databases.docker.valkey.get_xdist_worker_num", return_value=1),
        provide_valkey_service(fake_docker, "valkey/valkey:latest", "database") as svc_1,  # type: ignore[arg-type]
    ):
        assert svc_1.db == 1
    assert captured_names == ["valkey", "valkey"]


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


def test_default_no_xdist(pytester: pytest.Pytester) -> None:
    pytester.makepyfile(f"""
from pytest_databases.docker.valkey import ValkeyService

pytest_plugins = ["pytest_databases.docker.valkey"]

{VALKEY_TEST_HELPERS}

def test_valkey_service(valkey_service: ValkeyService) -> None:
    assert run_valkey(valkey_service, "PING") == "PONG"
""")
    result = pytester.runpytest_subprocess("-p", "pytest_databases")
    result.assert_outcomes(passed=1)


def test_xdist_isolate_database(pytester: pytest.Pytester) -> None:
    pytester.makepyfile(f"""
from pytest_databases.docker.valkey import ValkeyService
from pytest_databases.helpers import get_xdist_worker_num

pytest_plugins = ["pytest_databases.docker.valkey"]

{VALKEY_TEST_HELPERS}

def test_one(valkey_service: ValkeyService) -> None:
    assert run_valkey(valkey_service, "PING") == "PONG"
    assert valkey_service.db == get_xdist_worker_num()


def test_two(valkey_service: ValkeyService) -> None:
    assert run_valkey(valkey_service, "GET", "one") in ("", "(nil)")
    assert run_valkey(valkey_service, "SET", "one", "1") == "OK"
    assert valkey_service.db == get_xdist_worker_num()
""")
    result = pytester.runpytest_subprocess("-p", "pytest_databases", "-n", "2")
    result.assert_outcomes(passed=2)


def test_xdist_isolate_server(pytester: pytest.Pytester) -> None:
    pytester.makepyfile(f"""
import pytest
from pytest_databases.docker.valkey import ValkeyService

pytest_plugins = ["pytest_databases.docker.valkey"]


@pytest.fixture(scope="session")
def xdist_valkey_isolation_level():
    return "server"

{VALKEY_TEST_HELPERS}

def test_one(valkey_service: ValkeyService) -> None:
    assert run_valkey(valkey_service, "PING") == "PONG"
    assert valkey_service.db == 0


def test_two(valkey_service: ValkeyService) -> None:
    assert run_valkey(valkey_service, "GET", "one") in ("", "(nil)")
    assert run_valkey(valkey_service, "SET", "one", "1") == "OK"
    assert valkey_service.db == 0
""")
    result = pytester.runpytest_subprocess("-p", "pytest_databases", "-n", "2")
    result.assert_outcomes(passed=2)
