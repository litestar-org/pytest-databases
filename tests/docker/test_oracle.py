from __future__ import annotations

from typing import TYPE_CHECKING

import pytest

from pytest_databases.docker.oracle import oracle_responsive

if TYPE_CHECKING:
    from pytest_databases.docker import DockerServiceRegistry

pytestmark = pytest.mark.anyio


def test_oracle18c_default_config(
    oracle_user: str, oracle_password: str, oracle18c_service_name: str, oracle18c_port: int
) -> None:
    assert oracle_user == "app"
    assert oracle_password == "super-secret"
    assert oracle18c_service_name == "xepdb1"
    assert oracle18c_port == 1512


def test_oracle23c_default_config(
    oracle_user: str, oracle_password: str, oracle23c_service_name: str, oracle23c_port: int
) -> None:
    assert oracle_user == "app"
    assert oracle_password == "super-secret"
    assert oracle23c_service_name == "FREEPDB1"
    assert oracle23c_port == 1513


def test_oracle_default_config(
    oracle_user: str,
    oracle_password: str,
    oracle_service_name: str,
    oracle_port: int,
    oracle23c_port: int,
    oracle_default_version: str,
) -> None:
    assert oracle_default_version == "oracle23c"
    assert oracle_user == "app"
    assert oracle_password == "super-secret"
    assert oracle_service_name == "FREEPDB1"
    assert oracle_port == 1513
    assert oracle_port == oracle23c_port


async def test_oracle18c_service(docker_ip: str, oracle18c_service: DockerServiceRegistry) -> None:
    assert oracle_responsive(
        host=docker_ip,
        port=1512,
        service_name="xepdb1",
        user="app",
        password="super-secret",
    )


async def test_oracle23c_service(docker_ip: str, oracle23c_service: DockerServiceRegistry) -> None:
    assert oracle_responsive(
        host=docker_ip,
        port=1513,
        service_name="FREEPDB1",
        user="app",
        password="super-secret",
    )
