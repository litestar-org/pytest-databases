from __future__ import annotations

import pytest


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


REDIS_TEST_HELPERS = """
def run_redis_cli(docker_service, service, *args, db=None):
    if db is None:
        db = service.db
    output = docker_service._client.containers.run(
        image="redis:latest",
        command=["redis-cli", "-h", service.host, "-p", str(service.port), "-n", str(db), *args],
        network_mode="host",
        remove=True,
    )
    if isinstance(output, bytes):
        return output.decode().strip()
    if isinstance(output, str):
        return output.strip()
    return b"".join(output).decode().strip()
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

def test_redis_service(docker_service, redis_service: RedisService) -> None:
    assert run_redis_cli(docker_service, redis_service, "PING") == "PONG"
""")
    result = pytester.runpytest_subprocess("-p", "pytest_databases")
    result.assert_outcomes(passed=1)


def test_default_no_xdist(pytester: pytest.Pytester, redis_compatible_service: str) -> None:
    pytester.makepyfile(f"""
from pytest_databases.docker.redis import RedisService

pytest_plugins = ["pytest_databases.docker.redis"]

{REDIS_TEST_HELPERS}

def test_redis_service(docker_service, {redis_compatible_service}: RedisService) -> None:
    assert run_redis_cli(docker_service, {redis_compatible_service}, "PING") == "PONG"
""")
    result = pytester.runpytest_subprocess("-p", "pytest_databases")
    result.assert_outcomes(passed=1)


def test_xdist_isolate_database(pytester: pytest.Pytester, redis_compatible_service: str) -> None:
    pytester.makepyfile(f"""
from pytest_databases.docker.redis import RedisService
from pytest_databases.helpers import get_xdist_worker_num

pytest_plugins = ["pytest_databases.docker.redis"]

{REDIS_TEST_HELPERS}

def test_one(docker_service, {redis_compatible_service}: RedisService) -> None:
    assert {redis_compatible_service}.db == get_xdist_worker_num()
    assert run_redis_cli(docker_service, {redis_compatible_service}, "GET", "one") in ("", "(nil)")
    assert run_redis_cli(docker_service, {redis_compatible_service}, "SET", "one", "0") == "OK"
    assert run_redis_cli(docker_service, {redis_compatible_service}, "GET", "one") == "0"


def test_two(docker_service, {redis_compatible_service}: RedisService) -> None:
    assert {redis_compatible_service}.db == get_xdist_worker_num()
    assert run_redis_cli(docker_service, {redis_compatible_service}, "GET", "one") in ("", "(nil)")
    assert run_redis_cli(docker_service, {redis_compatible_service}, "SET", "one", "1") == "OK"
    assert run_redis_cli(docker_service, {redis_compatible_service}, "GET", "one") == "1"


def test_use_same_db(docker_service, {redis_compatible_service}: RedisService) -> None:
    assert run_redis_cli(docker_service, {redis_compatible_service}, "SET", "foo", "0", db=0) == "OK"
    assert run_redis_cli(docker_service, {redis_compatible_service}, "SET", "foo", "1", db=1) == "OK"
    assert run_redis_cli(docker_service, {redis_compatible_service}, "GET", "foo", db=0) == "0"
    assert run_redis_cli(docker_service, {redis_compatible_service}, "GET", "foo", db=1) == "1"
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

def test_one(docker_service, {redis_compatible_service}: RedisService) -> None:
    assert {redis_compatible_service}.db == 0
    assert run_redis_cli(docker_service, {redis_compatible_service}, "GET", "one") in ("", "(nil)")
    assert run_redis_cli(docker_service, {redis_compatible_service}, "SET", "one", "1") == "OK"


def test_two(docker_service, {redis_compatible_service}: RedisService) -> None:
    assert {redis_compatible_service}.db == 0
    assert run_redis_cli(docker_service, {redis_compatible_service}, "GET", "one") in ("", "(nil)")
    assert run_redis_cli(docker_service, {redis_compatible_service}, "SET", "one", "1") == "OK"
""")
    result = pytester.runpytest_subprocess("-p", "pytest_databases", "-n", "2")
    result.assert_outcomes(passed=2)
