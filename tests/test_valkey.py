from __future__ import annotations

import pytest


@pytest.fixture(params=[pytest.param("valkey_service", id="valkey")])
def valkey_compatible_service(request: pytest.FixtureRequest) -> str:
    return request.param


def test_default_no_xdist(pytester: pytest.Pytester, valkey_compatible_service: str) -> None:
    pytester.makepyfile(f"""
import pytest
import valkey
from pytest_databases.docker.valkey import ValkeyService
from pytest_databases.helpers import get_xdist_worker_num

pytest_plugins = [
    "pytest_databases.docker.valkey",
]

def test_valkey_service({valkey_compatible_service}: ValkeyService) -> None:
    assert valkey.Valkey.from_url("valkey://", host={valkey_compatible_service}.host, port={valkey_compatible_service}.port).ping()
""")
    result = pytester.runpytest_subprocess("-p", "pytest_databases")
    result.assert_outcomes(passed=1)


def test_xdist_isolate_database(pytester: pytest.Pytester, valkey_compatible_service: str) -> None:
    pytester.makepyfile(f"""
import pytest
import valkey
from pytest_databases.docker.valkey import ValkeyService
from pytest_databases.helpers import get_xdist_worker_num

pytest_plugins = [
    "pytest_databases.docker.valkey",
]

def test_one({valkey_compatible_service}: ValkeyService) -> None:
    client = valkey.Valkey.from_url("valkey://", host={valkey_compatible_service}.host, port={valkey_compatible_service}.port)
    assert client.ping()
    assert {valkey_compatible_service}.db == get_xdist_worker_num()


def test_two({valkey_compatible_service}: ValkeyService) -> None:
    client = valkey.Valkey.from_url("valkey://", host={valkey_compatible_service}.host, port={valkey_compatible_service}.port)
    assert not client.get("one")
    client.set("one", "1")
    assert {valkey_compatible_service}.db == get_xdist_worker_num()
""")
    result = pytester.runpytest_subprocess("-p", "pytest_databases", "-n", "2")
    result.assert_outcomes(passed=2)


def test_xdist_isolate_server(pytester: pytest.Pytester, valkey_compatible_service: str) -> None:
    pytester.makepyfile(f"""
import pytest
import valkey
from pytest_databases.docker.valkey import ValkeyService
from pytest_databases.helpers import get_xdist_worker_num

pytest_plugins = [
    "pytest_databases.docker.valkey",
]

@pytest.fixture(scope="session")
def xdist_valkey_isolation_level():
    return "server"


def test_one({valkey_compatible_service}: ValkeyService) -> None:
    client = valkey.Valkey.from_url("valkey://", host={valkey_compatible_service}.host, port={valkey_compatible_service}.port)
    assert client.ping()
    assert {valkey_compatible_service}.db == 0


def test_two({valkey_compatible_service}: ValkeyService) -> None:
    client = valkey.Valkey.from_url("valkey://", host={valkey_compatible_service}.host, port={valkey_compatible_service}.port)
    assert not client.get("one")
    client.set("one", "1")
    assert {valkey_compatible_service}.db == 0
""")
    result = pytester.runpytest_subprocess("-p", "pytest_databases", "-n", "2")
    result.assert_outcomes(passed=2)
