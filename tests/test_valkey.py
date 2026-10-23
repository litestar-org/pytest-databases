"""Tests for Valkey container service fixtures."""

from __future__ import annotations

from contextlib import contextmanager
from typing import TYPE_CHECKING
from unittest.mock import MagicMock, patch

import pytest

from pytest_databases.docker.valkey import provide_valkey_service, valkey_responsive
from pytest_databases.types import ServiceContainer

if TYPE_CHECKING:
    from collections.abc import Generator

    from pytest_databases.types import XdistIsolationLevel


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


@pytest.mark.parametrize(
    ("worker_num", "isolation_level", "expected_name", "expected_db"),
    [
        pytest.param(None, "database", "valkey", 0, id="no-xdist"),
        pytest.param(0, "database", "valkey", 0, id="database-gw0"),
        pytest.param(1, "database", "valkey", 1, id="database-gw1"),
        pytest.param(15, "database", "valkey", 15, id="database-gw15"),
        pytest.param(16, "database", "valkey_shared_2", 0, id="database-gw16"),
        pytest.param(33, "database", "valkey_shared_3", 1, id="database-gw33"),
        pytest.param(1, "server", "valkey_2", 0, id="server-gw1"),
    ],
)
def test_provide_valkey_service_container_slot(
    worker_num: int | None,
    isolation_level: XdistIsolationLevel,
    expected_name: str,
    expected_db: int,
) -> None:
    captured: dict[str, object] = {}

    class FakeDockerService:
        @contextmanager
        def run(self, image: str, **kwargs: object) -> Generator[ServiceContainer, None, None]:
            captured.update(kwargs, image=image)
            yield ServiceContainer(host="127.0.0.1", port=6379, container=MagicMock())

    with (
        patch("pytest_databases.docker.valkey.get_xdist_worker_num", return_value=worker_num),
        provide_valkey_service(FakeDockerService(), "valkey/valkey:latest", isolation_level) as service,  # type: ignore[arg-type]
    ):
        assert service.db == expected_db
    assert captured["name"] == expected_name
    assert captured["transient"] is (isolation_level == "server")


def test_valkey_responsive_is_deprecated_alias_for_redis_responsive() -> None:
    service = ServiceContainer(host="127.0.0.1", port=6379, container=MagicMock())
    with (
        patch("pytest_databases.docker.valkey.redis_responsive", return_value=True) as probe,
        pytest.warns(DeprecationWarning, match=r"removed in v1\.0\.0") as record,
    ):
        assert valkey_responsive(service) is True
    probe.assert_called_once_with(service)
    assert len(record) == 1
    assert record[0].filename == __file__


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
