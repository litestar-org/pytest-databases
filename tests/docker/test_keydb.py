from __future__ import annotations

import pytest
import redis

from pytest_databases.docker.keydb import KeydbService
from pytest_databases.helpers import get_xdist_worker_num

pytest_plugins = [
    "pytest_databases.docker.keydb",
]


@pytest.mark.parametrize("worker", ["1", "2"])
def test_keydb_service(
    keydb_service: KeydbService,
    worker: str,
) -> None:
    assert redis.Redis.from_url("redis://", host=keydb_service.host, port=keydb_service.port).ping()


@pytest.mark.parametrize(
    "worker",
    [
        pytest.param(
            0,
            marks=[pytest.mark.xdist_group("keydb_1")],
        ),
        pytest.param(
            1,
            marks=[
                pytest.mark.xdist_group("keydb_2"),
            ],
        ),
    ],
)
def test_keydb_service_split_db(worker: int, keydb_service: KeydbService) -> None:
    assert keydb_service.db == get_xdist_worker_num()


def test_keydb_port(keydb_port: int, keydb_service: KeydbService) -> None:
    assert keydb_port == keydb_service.port


def test_keydb_host(keydb_host: str, keydb_service: KeydbService) -> None:
    assert keydb_host == keydb_service.host
