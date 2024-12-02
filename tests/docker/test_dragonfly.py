from __future__ import annotations

from typing import TYPE_CHECKING

import pytest
import redis

from pytest_databases.helpers import get_xdist_worker_num

if TYPE_CHECKING:
    from pytest_databases.docker.dragonfly import DragonflyService

pytest_plugins = [
    "pytest_databases.docker.dragonfly",
]


@pytest.mark.parametrize("worker", ["1", "2"])
def test_dragonfly_service(
    dragonfly_service: DragonflyService,
    worker: str,
) -> None:
    assert redis.Redis.from_url("redis://", host=dragonfly_service.host, port=dragonfly_service.port).ping()


@pytest.mark.parametrize(
    "worker",
    [
        pytest.param(
            0,
            marks=[pytest.mark.xdist_group("dragonfly_1")],
        ),
        pytest.param(
            1,
            marks=[
                pytest.mark.xdist_group("dragonfly_2"),
            ],
        ),
    ],
)
def test_dragonfly_service_split_db(worker: int, dragonfly_service: DragonflyService) -> None:
    assert dragonfly_service.db == get_xdist_worker_num()


def test_dragonfly_port(dragonfly_port: int, dragonfly_service: DragonflyService) -> None:
    assert dragonfly_port == dragonfly_service.port


def test_dragonfly_host(dragonfly_host: str, dragonfly_service: DragonflyService) -> None:
    assert dragonfly_host == dragonfly_service.host
