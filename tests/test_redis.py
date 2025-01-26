from __future__ import annotations

import pytest

pytest_plugins = [
    "pytest_databases.docker.redis",
]


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


def test_default_no_xdist(pytester: pytest.Pytester, redis_image_name: str) -> None:
    pytester.makepyfile(f"""
import pytest
import redis
from pytest_databases.docker.redis import RedisService
from pytest_databases.helpers import get_xdist_worker_num

pytest_plugins = [
    "pytest_databases.docker.redis",
]

@pytest.fixture(scope="session")
def redis_image():
    return "{redis_image_name}"


def test_redis_service(redis_service: RedisService) -> None:
    assert redis.Redis.from_url("redis://", host=redis_service.host, port=redis_service.port).ping()
""")
    result = pytester.runpytest()
    result.assert_outcomes(passed=1)


def test_xdist_isolate_database(pytester: pytest.Pytester, redis_image_name: str) -> None:
    pytester.makepyfile(f"""
import pytest
import redis
from pytest_databases.helpers import get_xdist_worker_num

pytest_plugins = [
    "pytest_databases.docker.redis",
]


@pytest.fixture(scope="session")
def redis_image():
    return "{redis_image_name}"


def test_one(redis_service):
    client = redis.Redis.from_url("redis://", host=redis_service.host, port=redis_service.port, db=redis_service.db)
    assert not client.get("one")
    client.set("one", "1")
    assert redis_service.db == get_xdist_worker_num()


def test_two(redis_service):
    client = redis.Redis.from_url("redis://", host=redis_service.host, port=redis_service.port, db=redis_service.db)
    assert not client.get("one")
    client.set("one", "1")
    assert redis_service.db == get_xdist_worker_num()
""")
    result = pytester.runpytest("-n", "2")
    result.assert_outcomes(passed=2)


def test_xdist_isolate_server(pytester: pytest.Pytester, redis_image_name: str) -> None:
    pytester.makepyfile(f"""
import pytest
import redis
from pytest_databases.helpers import get_xdist_worker_num

pytest_plugins = [
    "pytest_databases.docker.redis",
]

@pytest.fixture(scope="session")
def redis_image():
    return "{redis_image_name}"


@pytest.fixture(scope="session")
def xdist_redis_isolation_level():
    return "server"


def test_one(redis_service):
    client = redis.Redis.from_url("redis://", host=redis_service.host, port=redis_service.port, db=redis_service.db)
    assert not client.get("one")
    client.set("one", "1")
    assert redis_service.db == 0


def test_two(redis_service):
    client = redis.Redis.from_url("redis://", host=redis_service.host, port=redis_service.port, db=redis_service.db)
    assert not client.get("one")
    client.set("one", "1")
    assert redis_service.db == 0
""")
    result = pytester.runpytest("-n", "2")
    result.assert_outcomes(passed=2)
