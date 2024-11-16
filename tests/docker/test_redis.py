from __future__ import annotations

from typing import TYPE_CHECKING

import pytest
import redis

from pytest_databases.helpers import get_xdist_worker_num

if TYPE_CHECKING:
    from pytest_databases.docker.redis import RedisService

pytest_plugins = [
    "pytest_databases.docker.redis",
]


@pytest.mark.parametrize("worker", ["1", "2"])
def test_redis_service(
    redis_service: RedisService,
    worker: str,
) -> None:
    assert redis.Redis.from_url("redis://", host=redis_service.host, port=redis_service.port).ping()


@pytest.mark.parametrize(
    "worker",
    [
        pytest.param(
            0,
            marks=[pytest.mark.xdist_group("redis_1")],
        ),
        pytest.param(
            1,
            marks=[
                pytest.mark.xdist_group("redis_2"),
            ],
        ),
    ],
)
def test_redis_service_split_db(worker: int, redis_service: RedisService) -> None:
    assert redis_service.db == get_xdist_worker_num()


def test_redis_port(redis_port: int, redis_service: RedisService) -> None:
    assert redis_port == redis_service.port


def test_redis_host(redis_host: str, redis_service: RedisService) -> None:
    assert redis_host == redis_service.host
