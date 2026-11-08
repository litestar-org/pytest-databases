"""Tests for Redis, KeyDB, and Dragonfly container service fixtures."""

from __future__ import annotations

import io
import socket
import threading
from contextlib import contextmanager
from typing import TYPE_CHECKING
from unittest.mock import MagicMock, patch

import pytest

from pytest_databases.docker.redis import (
    encode_resp_command,
    provide_redis_service,
    read_resp_reply,
    redis_responsive,
    send_resp_command,
)
from pytest_databases.types import ServiceContainer

if TYPE_CHECKING:
    from collections.abc import Generator

    from pytest_databases.types import XdistIsolationLevel


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


@pytest.mark.parametrize(
    ("worker_num", "isolation_level", "expected_name", "expected_db"),
    [
        pytest.param(None, "database", "redis", 0, id="no-xdist"),
        pytest.param(0, "database", "redis", 0, id="database-gw0"),
        pytest.param(15, "database", "redis", 15, id="database-gw15"),
        pytest.param(16, "database", "redis_shared_2", 0, id="database-gw16"),
        pytest.param(33, "database", "redis_shared_3", 1, id="database-gw33"),
        pytest.param(1, "server", "redis_2", 0, id="server-gw1"),
        pytest.param(16, "server", "redis_17", 0, id="server-gw16"),
    ],
)
def test_provide_redis_service_container_slot(
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
        patch("pytest_databases.docker.redis.get_xdist_worker_num", return_value=worker_num),
        provide_redis_service(FakeDockerService(), "redis:latest", "redis", isolation_level) as service,  # type: ignore[arg-type]
    ):
        assert service.db == expected_db
    assert captured["name"] == expected_name
    assert captured["transient"] is (isolation_level == "server")


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


def test_redis_all_fixtures_inprocess(pytester: pytest.Pytester) -> None:
    """Verify all Redis, Dragonfly, and KeyDB fixtures execute in-process with mocked docker_service."""
    pytester.makepyfile("""
    from contextlib import contextmanager
    from unittest.mock import MagicMock
    import pytest
    from pytest_databases.types import ServiceContainer

    pytest_plugins = ["pytest_databases.docker.redis"]

    @pytest.fixture(scope="session")
    def docker_service():
        mock_ds = MagicMock()
        @contextmanager
        def _run(image, **kwargs):
            yield ServiceContainer(host="127.0.0.1", port=6379, container=MagicMock())
        mock_ds.run.side_effect = _run
        return mock_ds

    def test_fixtures(
        xdist_redis_isolation_level,
        redis_image,
        redis_host,
        redis_port,
        redis_service,
        dragonfly_image,
        dragonfly_host,
        dragonfly_port,
        dragonfly_service,
        keydb_image,
        keydb_host,
        keydb_port,
        keydb_service,
    ):
        assert xdist_redis_isolation_level == "database"
        assert "redis" in redis_image
        assert redis_host == "127.0.0.1"
        assert redis_port == 6379
        assert redis_service.port == 6379
        assert "dragonfly" in dragonfly_image
        assert dragonfly_host == "127.0.0.1"
        assert dragonfly_port == 6379
        assert dragonfly_service.port == 6379
        assert "keydb" in keydb_image
        assert keydb_host == "127.0.0.1"
        assert keydb_port == 6379
        assert keydb_service.port == 6379
    """)
    result = pytester.runpytest("-p", "no:sugar", "-p", "pytest_databases", "-W", "ignore::DeprecationWarning")
    result.assert_outcomes(passed=1)
