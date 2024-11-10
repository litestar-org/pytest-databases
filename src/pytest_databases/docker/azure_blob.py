from __future__ import annotations

import json
import secrets
import subprocess  # noqa: S404
from dataclasses import dataclass
from typing import AsyncGenerator, Generator

import pytest
from azure.storage.blob import ContainerClient
from azure.storage.blob.aio import ContainerClient as AsyncContainerClient

from pytest_databases._service import DockerService
from pytest_databases.helpers import get_xdist_worker_num
from pytest_databases.types import ServiceContainer


@dataclass
class AzureBlobService(ServiceContainer):
    connection_string: str
    account_url: str
    account_key: str = "Eby8vdM02xNOcqFlqUwJPLlmEtlCDXJ1OUzFT50uSRZ6IFsuFq2UVErCz4I6tq/K1SZFPTOtr/KBHBeksoGMGw=="
    account_name: str = "devstoreaccount1"


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


def _get_container_logs(container_id: str) -> str:
    return subprocess.run(
        ["docker", "logs", container_id],  # noqa: S607
        capture_output=True,
        text=True,
        check=True,
    ).stdout


@pytest.fixture(scope="session")
def azure_blob_service_startup_delay() -> int:
    return 1


@pytest.fixture(scope="session")
def azure_blob_service(
    docker_service: DockerService,
) -> Generator[ServiceContainer, None, None]:
    with docker_service.run(
        image="mcr.microsoft.com/azure-storage/azurite",
        name="azurite-blob",
        command="azurite-blob --blobHost 0.0.0.0 --blobPort 10000",
        wait_for_log="Azurite Blob service successfully listens on",
        container_port=10000,
    ) as service:
        account_url = f"http://127.0.0.1:{service.port}/devstoreaccount1"
        connection_string = (
            "DefaultEndpointsProtocol=http;"
            "AccountName=devstoreaccount1;"
            "AccountKey=Eby8vdM02xNOcqFlqUwJPLlmEtlCDXJ1OUzFT50uSRZ6IFsuFq2UVErCz4I6tq/K1SZFPTOtr/KBHBeksoGMGw==;"
            f"BlobEndpoint={account_url};"
        )

        yield AzureBlobService(
            host=service.host,
            port=service.port,
            connection_string=connection_string,
            account_url=account_url,
        )


@pytest.fixture(scope="session")
def azure_blob_default_container_name() -> str:
    return f"pytest{get_xdist_worker_num()}"


@pytest.fixture(scope="session")
def azure_blob_container_client(
    azure_blob_service: AzureBlobService,
    azure_blob_default_container_name: str,
) -> Generator[ContainerClient, None, None]:
    with ContainerClient.from_connection_string(
        azure_blob_service.connection_string,
        container_name=azure_blob_default_container_name,
    ) as container_client:
        yield container_client


@pytest.fixture(scope="session")
async def azure_blob_async_container_client(
    azure_blob_service: AzureBlobService,
    azure_blob_default_container_name: str,
) -> AsyncGenerator[AsyncContainerClient, None]:
    async with AsyncContainerClient.from_connection_string(
        azure_blob_service.connection_string,
        container_name=azure_blob_default_container_name,
    ) as container_client:
        yield container_client
