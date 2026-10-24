"""Tests for Redis, KeyDB, and Dragonfly container service fixtures."""

from __future__ import annotations

import io
import socket
import threading
from unittest.mock import MagicMock, patch

import pytest

from pytest_databases.docker.redis import (
    RedisService,
    encode_resp_command,
    provide_deprecated_redis_client,
    read_resp_reply,
    redis_responsive,
    send_resp_command,
)
from pytest_databases.types import ServiceContainer


def test_plugin_imports_without_redis(pytester: pytest.Pytester) -> None:
    pytester.makepyfile("""
    import builtins

    def test_import() -> None:
        original_import = builtins.__import__

        def blocked_import(name, globals=None, locals=None, fromlist=(), level=0):
            if name == "redis" or name.startswith("redis."):
                raise ModuleNotFoundError(name)
            return original_import(name, globals, locals, fromlist, level)

        builtins.__import__ = blocked_import
        try:
            import pytest_databases.docker.redis
        finally:
            builtins.__import__ = original_import
    """)

    result = pytester.runpytest_subprocess("-p", "pytest_databases", "-vv")
    result.assert_outcomes(passed=1)


def test_encode_and_read_resp_protocol() -> None:
    assert encode_resp_command("PING") == b"*1\r\n$4\r\nPING\r\n"
    assert encode_resp_command("SET", "key", "val") == b"*3\r\n$3\r\nSET\r\n$3\r\nkey\r\n$3\r\nval\r\n"

    assert read_resp_reply(io.BytesIO(b"+PONG\r\n")) == "PONG"
    assert read_resp_reply(io.BytesIO(b":42\r\n")) == 42
    assert read_resp_reply(io.BytesIO(b"$-1\r\n")) is None
    assert read_resp_reply(io.BytesIO(b"$5\r\nhello\r\n")) == "hello"

    with pytest.raises(RuntimeError, match="ERR unknown command"):
        read_resp_reply(io.BytesIO(b"-ERR unknown command\r\n"))

    with pytest.raises(ConnectionError, match="Empty RESP response"):
        read_resp_reply(io.BytesIO(b""))


def test_send_resp_command_and_redis_responsive_over_socket() -> None:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as server:
        server.bind(("127.0.0.1", 0))
        server.listen(2)
        host, port = server.getsockname()

        def handle_clients() -> None:
            for _ in range(2):
                conn, _ = server.accept()
                with conn:
                    data = conn.recv(1024)
                    if b"SELECT" in data:
                        conn.sendall(b"+OK\r\n$3\r\nbar\r\n")
                    else:
                        conn.sendall(b"+PONG\r\n")

        thread = threading.Thread(target=handle_clients, daemon=True)
        thread.start()

        container = MagicMock()
        service = ServiceContainer(host=host, port=port, container=container)
        assert redis_responsive(service) is True
        assert send_resp_command(host, port, "GET", "foo", db=2) == "bar"
        thread.join(timeout=2.0)


def test_deprecated_redis_client_emits_warning() -> None:
    service = RedisService(host="127.0.0.1", port=6379, container=MagicMock(), db=3)
    fake_client = MagicMock()
    fake_redis_mod = MagicMock()
    fake_redis_mod.Redis.return_value = fake_client
    with (
        patch("importlib.import_module", return_value=fake_redis_mod),
        pytest.deprecated_call(match="deprecated"),
    ):
        gen = provide_deprecated_redis_client(service, "redis_client", "redis_service")
        yielded = next(gen)
        assert yielded is fake_client
        fake_redis_mod.Redis.assert_called_once_with(host="127.0.0.1", port=6379, db=3)
        with pytest.raises(StopIteration):
            next(gen)
        fake_client.close.assert_called_once()


REDIS_TEST_HELPERS = """
from pytest_databases.docker.redis import send_resp_command

def run_redis_cmd(service, *args, db=None):
    target_db = service.db if db is None else db
    result = send_resp_command(service.host, service.port, *args, db=target_db)
    return "" if result is None else str(result)
"""


@pytest.fixture(
    params=[
        pytest.param("redis:latest", id="redis"),
        pytest.param("valkey/valkey", id="valkey"),
        pytest.param("eqalpha/keydb", id="keydb"),
        pytest.param("docker.dragonflydb.io/dragonflydb/dragonfly", id="dragonflydb"),
    ]
)
def redis_image_name(request: pytest.FixtureRequest) -> str:
    return request.param


@pytest.fixture(
    params=[
        pytest.param("redis_service", id="redis"),
        pytest.param("keydb_service", id="keydb"),
        pytest.param("dragonfly_service", id="dragonflydb"),
    ]
)
def redis_compatible_service(request: pytest.FixtureRequest) -> str:
    return request.param


def test_redis_image(pytester: pytest.Pytester, redis_image_name: str) -> None:
    pytester.makepyfile(f"""
import pytest
from pytest_databases.docker.redis import RedisService

pytest_plugins = ["pytest_databases.docker.redis"]


@pytest.fixture(scope="session")
def redis_image():
    return "{redis_image_name}"

{REDIS_TEST_HELPERS}

def test_redis_service(redis_service: RedisService) -> None:
    assert run_redis_cmd(redis_service, "PING") == "PONG"
""")
    result = pytester.runpytest_subprocess("-p", "pytest_databases")
    result.assert_outcomes(passed=1)


def test_default_no_xdist(pytester: pytest.Pytester, redis_compatible_service: str) -> None:
    pytester.makepyfile(f"""
from pytest_databases.docker.redis import RedisService

pytest_plugins = ["pytest_databases.docker.redis"]

{REDIS_TEST_HELPERS}

def test_redis_service({redis_compatible_service}: RedisService) -> None:
    assert run_redis_cmd({redis_compatible_service}, "PING") == "PONG"
""")
    result = pytester.runpytest_subprocess("-p", "pytest_databases")
    result.assert_outcomes(passed=1)


def test_xdist_isolate_database(pytester: pytest.Pytester, redis_compatible_service: str) -> None:
    pytester.makepyfile(f"""
from pytest_databases.docker.redis import RedisService
from pytest_databases.helpers import get_xdist_worker_num

pytest_plugins = ["pytest_databases.docker.redis"]

{REDIS_TEST_HELPERS}

def test_one({redis_compatible_service}: RedisService) -> None:
    assert {redis_compatible_service}.db == get_xdist_worker_num()
    assert run_redis_cmd({redis_compatible_service}, "GET", "one") == ""
    assert run_redis_cmd({redis_compatible_service}, "SET", "one", "0") == "OK"
    assert run_redis_cmd({redis_compatible_service}, "GET", "one") == "0"


def test_two({redis_compatible_service}: RedisService) -> None:
    assert {redis_compatible_service}.db == get_xdist_worker_num()
    assert run_redis_cmd({redis_compatible_service}, "GET", "one") == ""
    assert run_redis_cmd({redis_compatible_service}, "SET", "one", "1") == "OK"
    assert run_redis_cmd({redis_compatible_service}, "GET", "one") == "1"


def test_use_same_db({redis_compatible_service}: RedisService) -> None:
    assert run_redis_cmd({redis_compatible_service}, "SET", "foo", "0", db=0) == "OK"
    assert run_redis_cmd({redis_compatible_service}, "SET", "foo", "1", db=1) == "OK"
    assert run_redis_cmd({redis_compatible_service}, "GET", "foo", db=0) == "0"
    assert run_redis_cmd({redis_compatible_service}, "GET", "foo", db=1) == "1"
""")
    result = pytester.runpytest_subprocess("-p", "pytest_databases", "-n", "2")
    result.assert_outcomes(passed=3)


def test_xdist_isolate_server(pytester: pytest.Pytester, redis_compatible_service: str) -> None:
    pytester.makepyfile(f"""
import pytest
from pytest_databases.docker.redis import RedisService

pytest_plugins = ["pytest_databases.docker.redis"]


@pytest.fixture(scope="session")
def xdist_redis_isolation_level():
    return "server"

{REDIS_TEST_HELPERS}

def test_one({redis_compatible_service}: RedisService) -> None:
    assert {redis_compatible_service}.db == 0
    assert run_redis_cmd({redis_compatible_service}, "GET", "one") == ""
    assert run_redis_cmd({redis_compatible_service}, "SET", "one", "1") == "OK"


def test_two({redis_compatible_service}: RedisService) -> None:
    assert {redis_compatible_service}.db == 0
    assert run_redis_cmd({redis_compatible_service}, "GET", "one") == ""
    assert run_redis_cmd({redis_compatible_service}, "SET", "one", "1") == "OK"
""")
    result = pytester.runpytest_subprocess("-p", "pytest_databases", "-n", "2")
    result.assert_outcomes(passed=2)
