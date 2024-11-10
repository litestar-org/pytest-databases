from __future__ import annotations

from typing import TYPE_CHECKING

import pytest
import redis

from pytest_databases.helpers import get_xdist_worker_num

if TYPE_CHECKING:
    from pytest_databases.docker.valkey import ValkeyService

pytest_plugins = [
    "pytest_databases.docker.valkey",
]


@pytest.mark.parametrize("worker", ["1", "2"])
def test_valkey_service(
    valkey_service: ValkeyService,
    worker: str,
) -> None:
    assert redis.Redis.from_url("redis://", host=valkey_service.host, port=valkey_service.port).ping()


@pytest.mark.parametrize(
    "worker",
    [
        pytest.param(
            0,
            marks=[pytest.mark.xdist_group("valkey_1")],
        ),
        pytest.param(
            1,
            marks=[
                pytest.mark.xdist_group("valkey_2"),
            ],
        ),
    ],
)
def test_valkey_service_split_db(worker: int, valkey_service: ValkeyService) -> None:
    assert valkey_service.db == get_xdist_worker_num()


def test_valkey_port(valkey_port: int, valkey_service: ValkeyService) -> None:
    assert valkey_port == valkey_service.port


def test_valkey_host(valkey_host: str, valkey_service: ValkeyService) -> None:
    assert valkey_host == valkey_service.host
