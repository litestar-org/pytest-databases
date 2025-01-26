from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, AsyncGenerator, Generator

import pytest
from azure.storage.blob import ContainerClient
from azure.storage.blob.aio import ContainerClient as AsyncContainerClient

from pytest_databases.helpers import get_xdist_worker_count, get_xdist_worker_num
from pytest_databases.types import ServiceContainer, XdistIsolationLevel

if TYPE_CHECKING:
    from pytest_databases._service import DockerService


DEFAULT_ACCOUNT_KEY = "Eby8vdM02xNOcqFlqUwJPLlmEtlCDXJ1OUzFT50uSRZ6IFsuFq2UVErCz4I6tq/K1SZFPTOtr/KBHBeksoGMGw=="
DEFAULT_ACCOUNT_NAME = "devstoreaccount1"


@dataclass
class AzureBlobService(ServiceContainer):
    connection_string: str
    account_url: str
    account_key: str
    account_name: str


@pytest.fixture(scope="session")
def azure_blob_xdist_isolation_level() -> XdistIsolationLevel:
    return "database"


@pytest.fixture(scope="session")
def azurite_in_memory() -> bool:
    return True


def _create_account_options(number: int) -> list[tuple[str, str]]:
    return [(f"test_account_{i}", DEFAULT_ACCOUNT_KEY) for i in range(number)]


@pytest.fixture(scope="session")
def azure_blob_service(
    docker_service: DockerService,
    azurite_in_memory: bool,
    azure_blob_xdist_isolation_level: XdistIsolationLevel,
) -> Generator[ServiceContainer, None, None]:
    command = "azurite-blob --blobHost 0.0.0.0 --blobPort 10000"
    if azurite_in_memory:
        command += " --inMemoryPersistence"

    name = "azurite-blob"
    env = {}
    account_name = DEFAULT_ACCOUNT_NAME
    account_key = DEFAULT_ACCOUNT_KEY

    worker_num = get_xdist_worker_num()

    if worker_num is not None:
        if azure_blob_xdist_isolation_level == "server":
            name = f"{name}_{worker_num}"
        else:
            accounts = _create_account_options(get_xdist_worker_count())
            env["AZURITE_ACCOUNTS"] = ";".join(f"{name}:{key}" for name, key in accounts)
            account_name, account_key = accounts[worker_num]

    with docker_service.run(
        image="mcr.microsoft.com/azure-storage/azurite",
        name=name,
        command=command,
        wait_for_log="Azurite Blob service successfully listens on",
        container_port=10000,
        env=env,
    ) as service:
        account_url = f"http://127.0.0.1:{service.port}/{account_name}"
        connection_string = (
            "DefaultEndpointsProtocol=http;"
            f"AccountName={account_name};"
            f"AccountKey={account_key};"
            f"BlobEndpoint={account_url};"
        )

        yield AzureBlobService(
            host=service.host,
            port=service.port,
            connection_string=connection_string,
            account_url=account_url,
            account_key=account_key,
            account_name=account_name,
        )


@pytest.fixture(scope="session")
def azure_blob_default_container_name() -> str:
    return "pytest-databases"


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
