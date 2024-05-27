from __future__ import annotations

import json
import os
import secrets
import subprocess  # noqa: S404
from pathlib import Path
from typing import AsyncGenerator, Generator

import pytest
from azure.storage.blob import ContainerClient
from azure.storage.blob.aio import ContainerClient as AsyncContainerClient

from pytest_databases.docker import DockerServiceRegistry
from pytest_databases.helpers import simple_string_hash

COMPOSE_PROJECT_NAME: str = f"pytest-databases-azure-blob-{simple_string_hash(__file__)}"


def _get_container_ids(compose_file_name: str) -> list[str]:
    proc = subprocess.run(
        [  # noqa: S607
            "docker",
            "container",
            "ls",
            f"--filter=label=com.docker.compose.project.config_files={compose_file_name}",
            "--format=json",
        ],
        capture_output=True,
        text=True,
        check=True,
    )
    return [json.loads(line)["ID"] for line in proc.stdout.splitlines()]


def _get_container_logs(compose_file_name: str) -> str:
    logs = ""
    for container_id in _get_container_ids(compose_file_name):
        stdout = subprocess.run(
            ["docker", "logs", container_id],  # noqa: S607
            capture_output=True,
            text=True,
            check=True,
        ).stdout
        logs += stdout
    return logs


@pytest.fixture(scope="session")
def azure_blob_compose_project_name() -> str:
    return os.environ.get("COMPOSE_PROJECT_NAME", COMPOSE_PROJECT_NAME)


@pytest.fixture(scope="session")
def azure_blob_service_startup_delay() -> int:
    return 1


@pytest.fixture(scope="session")
def azure_blob_docker_services(
    azure_blob_compose_project_name: str,
    azure_blob_service_startup_delay: int,
    worker_id: str = "main",
) -> Generator[DockerServiceRegistry, None, None]:
    registry = DockerServiceRegistry(
        worker_id,
        compose_project_name=azure_blob_compose_project_name,
    )
    try:
        yield registry
    finally:
        registry.down()


@pytest.fixture(scope="session")
def azure_blob_connection_string() -> str:
    return "DefaultEndpointsProtocol=http;AccountName=devstoreaccount1;AccountKey=Eby8vdM02xNOcqFlqUwJPLlmEtlCDXJ1OUzFT50uSRZ6IFsuFq2UVErCz4I6tq/K1SZFPTOtr/KBHBeksoGMGw==;BlobEndpoint=http://127.0.0.1:10000/devstoreaccount1;"


@pytest.fixture(scope="session")
def azure_blob_account_name() -> str:
    return "devstoreaccount1"


@pytest.fixture(scope="session")
def azure_blob_account_key() -> str:
    return "Eby8vdM02xNOcqFlqUwJPLlmEtlCDXJ1OUzFT50uSRZ6IFsuFq2UVErCz4I6tq/K1SZFPTOtr/KBHBeksoGMGw=="


@pytest.fixture(scope="session")
def azure_blob_account_url() -> str:
    return "http://127.0.0.1:10000/devstoreaccount1"


@pytest.fixture(scope="session")
def azure_blob_port() -> int:
    return 10000


@pytest.fixture(scope="session")
def azure_blob_docker_compose_files() -> list[Path]:
    return [Path(Path(__file__).parent / "docker-compose.azurite.yml")]


@pytest.fixture(scope="session")
def default_azure_blob_redis_service_name() -> str:
    return "azurite"


@pytest.fixture(scope="session")
def azure_blob_docker_ip(azure_blob_docker_services: DockerServiceRegistry) -> str:
    return azure_blob_docker_services.docker_ip


@pytest.fixture(scope="session")
def azure_blob_default_container_name() -> str:
    return secrets.token_hex(4)


@pytest.fixture(scope="session")
def azure_blob_container_client(
    azure_blob_connection_string: str,
    azure_blob_default_container_name: str,
    azure_blob_service: None,
) -> Generator[ContainerClient, None, None]:
    with ContainerClient.from_connection_string(
        azure_blob_connection_string, container_name=azure_blob_default_container_name
    ) as container_client:
        yield container_client


@pytest.fixture(scope="session")
async def azure_blob_async_container_client(
    azure_blob_connection_string: str, azure_blob_default_container_name: str
) -> AsyncGenerator[AsyncContainerClient, None]:
    async with AsyncContainerClient.from_connection_string(
        azure_blob_connection_string, container_name=azure_blob_default_container_name
    ) as container_client:
        yield container_client


@pytest.fixture(autouse=False, scope="session")
async def azure_blob_service(
    azure_blob_docker_services: DockerServiceRegistry,
    default_azure_blob_redis_service_name: str,
    azure_blob_docker_compose_files: list[Path],
    azure_blob_connection_string: str,
    azure_blob_port: int,
    azure_blob_default_container_name: str,
) -> AsyncGenerator[None, None]:
    os.environ["AZURE_BLOB_PORT"] = str(azure_blob_port)

    def azurite_responsive(host: str, port: int) -> bool:
        # because azurite has a bug where it will hang for a long time if you make a
        # request against it before it has completed startup we can't ping it, so we're
        # inspecting the container logs instead
        logs = _get_container_logs(str(azure_blob_docker_compose_files[0].absolute()))
        return "Azurite Blob service successfully listens on" in logs

    await azure_blob_docker_services.start(
        name=default_azure_blob_redis_service_name,
        docker_compose_files=azure_blob_docker_compose_files,
        check=azurite_responsive,
        port=azure_blob_port,
    )
    yield
