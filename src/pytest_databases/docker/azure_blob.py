"""Azure Blob Storage (Azurite) container service fixtures."""

from __future__ import annotations

import base64
import email.utils
import hashlib
import hmac
import importlib
import urllib.error
import urllib.request
import warnings
from contextlib import asynccontextmanager, contextmanager
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

import pytest

from pytest_databases.helpers import get_xdist_worker_count, get_xdist_worker_num
from pytest_databases.types import ServiceContainer, XdistIsolationLevel

if TYPE_CHECKING:
    from collections.abc import AsyncGenerator, Generator

    from pytest_databases._service import DockerService

__all__ = (
    "AZURE_API_VERSION",
    "DEFAULT_ACCOUNT_KEY",
    "DEFAULT_ACCOUNT_NAME",
    "AzureBlobService",
    "azure_blob_async_container_client",
    "azure_blob_container_client",
    "azure_blob_default_container",
    "azure_blob_default_container_name",
    "azure_blob_service",
    "azure_blob_xdist_isolation_level",
    "azurite_container_exists",
    "azurite_in_memory",
    "build_shared_key_authorization",
    "ensure_azurite_container",
    "provide_azure_blob_async_container_client",
    "provide_azure_blob_container_client",
)

DEFAULT_ACCOUNT_KEY = "Eby8vdM02xNOcqFlqUwJPLlmEtlCDXJ1OUzFT50uSRZ6IFsuFq2UVErCz4I6tq/K1SZFPTOtr/KBHBeksoGMGw=="
DEFAULT_ACCOUNT_NAME = "devstoreaccount1"
AZURE_API_VERSION = "2021-08-06"


@dataclass
class AzureBlobService(ServiceContainer):
    """Connection metadata for an Azurite Blob Storage container service."""

    connection_string: str
    account_url: str
    account_key: str
    account_name: str


def build_shared_key_authorization(
    *,
    method: str,
    account_name: str,
    account_key: str,
    container_name: str,
    ms_date: str,
    api_version: str = AZURE_API_VERSION,
    content_length: int = 0,
) -> str:
    """Build an Azure Storage ``SharedKey`` ``Authorization`` header for a path-style container request."""
    length_header = str(content_length) if content_length > 0 else ""
    string_to_sign = "\n".join([
        method.upper(),
        "",
        "",
        length_header,
        "",
        "",
        "",
        "",
        "",
        "",
        "",
        "",
        f"x-ms-date:{ms_date}",
        f"x-ms-version:{api_version}",
        f"/{account_name}/{account_name}/{container_name}",
        "restype:container",
    ])
    decoded_key = base64.b64decode(account_key)
    digest = hmac.new(decoded_key, string_to_sign.encode("utf-8"), hashlib.sha256).digest()
    signature = base64.b64encode(digest).decode("ascii")
    return f"SharedKey {account_name}:{signature}"


def ensure_azurite_container(
    *,
    account_url: str,
    account_name: str,
    account_key: str,
    container_name: str,
    timeout: float = 5.0,
) -> bool:
    """Ensure ``container_name`` exists in Azurite using a signed ``PUT ?restype=container`` request."""
    try:
        status = _send_azurite_container_request(
            method="PUT",
            account_url=account_url,
            account_name=account_name,
            account_key=account_key,
            container_name=container_name,
            timeout=timeout,
        )
    except (urllib.error.URLError, TimeoutError, OSError):
        return False
    return status in {201, 409}


def azurite_container_exists(
    *,
    account_url: str,
    account_name: str,
    account_key: str,
    container_name: str,
    timeout: float = 5.0,
) -> bool:
    """Return ``True`` if ``container_name`` exists in Azurite using a signed ``GET ?restype=container`` request."""
    try:
        status = _send_azurite_container_request(
            method="GET",
            account_url=account_url,
            account_name=account_name,
            account_key=account_key,
            container_name=container_name,
            timeout=timeout,
        )
    except (urllib.error.URLError, TimeoutError, OSError):
        return False
    return status == 200


@contextmanager
def provide_azure_blob_container_client(
    azure_blob_service: AzureBlobService,
    container_name: str,
    *,
    fixture_name: str = "azure_blob_container_client",
) -> Generator[Any, None, None]:
    """Emit a deprecation warning and yield an Azure ``ContainerClient``.

    Yields:
        A synchronous ``azure.storage.blob.ContainerClient`` instance.
    """
    warnings.warn(
        f"The '{fixture_name}' fixture is deprecated and will be removed in a future release. "
        "Use 'azure_blob_service' and construct your own Azure Blob client.",
        DeprecationWarning,
        stacklevel=2,
    )
    blob_mod: Any = importlib.import_module("azure.storage.blob")
    with blob_mod.ContainerClient.from_connection_string(
        azure_blob_service.connection_string,
        container_name=container_name,
    ) as container_client:
        yield container_client


@asynccontextmanager
async def provide_azure_blob_async_container_client(
    azure_blob_service: AzureBlobService,
    container_name: str,
    *,
    fixture_name: str = "azure_blob_async_container_client",
) -> AsyncGenerator[Any, None]:
    """Emit a deprecation warning and yield an async Azure ``ContainerClient``.

    Yields:
        An asynchronous ``azure.storage.blob.aio.ContainerClient`` instance.
    """
    warnings.warn(
        f"The '{fixture_name}' fixture is deprecated and will be removed in a future release. "
        "Use 'azure_blob_service' and construct your own async Azure Blob client.",
        DeprecationWarning,
        stacklevel=2,
    )
    aio_mod: Any = importlib.import_module("azure.storage.blob.aio")
    async with aio_mod.ContainerClient.from_connection_string(
        azure_blob_service.connection_string,
        container_name=container_name,
    ) as container_client:
        yield container_client


@pytest.fixture(scope="session")
def azure_blob_xdist_isolation_level() -> XdistIsolationLevel:
    """Return the default pytest-xdist isolation level for Azure Blob Storage."""
    return "database"


@pytest.fixture(scope="session")
def azurite_in_memory() -> bool:
    """Return whether Azurite should run with in-memory persistence."""
    return True


@pytest.fixture(scope="session")
def azure_blob_default_container_name() -> str:
    """Return the default blob container name created on startup."""
    return "pytest-databases"


@pytest.fixture(scope="session")
def azure_blob_service(
    docker_service: DockerService,
    azurite_in_memory: bool,
    azure_blob_xdist_isolation_level: XdistIsolationLevel,
    azure_blob_default_container_name: str,
) -> Generator[AzureBlobService, None, None]:
    """Provide a session-scoped Azurite Blob Storage service with the default container initialized.

    Yields:
        A running :class:`AzureBlobService` instance.
    """
    command = "azurite-blob --blobHost 0.0.0.0 --blobPort 10000 --skipApiVersionCheck"
    if azurite_in_memory:
        command += " --inMemoryPersistence"

    name = "azurite-blob"
    env: dict[str, str] = {}
    account_name = DEFAULT_ACCOUNT_NAME
    account_key = DEFAULT_ACCOUNT_KEY

    worker_num = get_xdist_worker_num()

    if worker_num is not None:
        if azure_blob_xdist_isolation_level == "server":
            name = f"{name}_{worker_num}"
        else:
            accounts = _create_account_options(get_xdist_worker_count())
            env["AZURITE_ACCOUNTS"] = ";".join(f"{acct_name}:{key}" for acct_name, key in accounts)
            account_name, account_key = accounts[worker_num]

    def check(_service: ServiceContainer) -> bool:
        account_url = f"http://{_service.host}:{_service.port}/{account_name}"
        return ensure_azurite_container(
            account_url=account_url,
            account_name=account_name,
            account_key=account_key,
            container_name=azure_blob_default_container_name,
        )

    with docker_service.run(
        image="mcr.microsoft.com/azure-storage/azurite",
        name=name,
        command=command,
        wait_for_log="Azurite Blob service successfully listens on",
        check=check,
        container_port=10000,
        env=env,
        transient=azure_blob_xdist_isolation_level == "server",
    ) as service:
        account_url = f"http://{service.host}:{service.port}/{account_name}"
        connection_string = (
            "DefaultEndpointsProtocol=http;"
            f"AccountName={account_name};"
            f"AccountKey={account_key};"
            f"BlobEndpoint={account_url};"
        )

        yield AzureBlobService(
            host=service.host,
            port=service.port,
            container=service.container,
            connection_string=connection_string,
            account_url=account_url,
            account_key=account_key,
            account_name=account_name,
        )


@pytest.fixture(scope="session")
def azure_blob_container_client(
    azure_blob_service: AzureBlobService,
    azure_blob_default_container_name: str,
) -> Generator[Any, None, None]:
    """Provide a deprecated synchronous Azure Blob ``ContainerClient``.

    Yields:
        A synchronous ``ContainerClient`` connected to the default container.
    """
    with provide_azure_blob_container_client(
        azure_blob_service,
        azure_blob_default_container_name,
        fixture_name="azure_blob_container_client",
    ) as container_client:
        yield container_client


@pytest.fixture(scope="session")
def azure_blob_default_container(
    azure_blob_service: AzureBlobService,
    azure_blob_default_container_name: str,
) -> Generator[Any, None, None]:
    """Provide a deprecated alias for :func:`azure_blob_container_client`.

    Yields:
        A synchronous ``ContainerClient`` connected to the default container.
    """
    with provide_azure_blob_container_client(
        azure_blob_service,
        azure_blob_default_container_name,
        fixture_name="azure_blob_default_container",
    ) as container_client:
        yield container_client


@pytest.fixture(scope="session")
async def azure_blob_async_container_client(
    azure_blob_service: AzureBlobService,
    azure_blob_default_container_name: str,
) -> AsyncGenerator[Any, None]:
    """Provide a deprecated asynchronous Azure Blob ``ContainerClient``.

    Yields:
        An asynchronous ``ContainerClient`` connected to the default container.
    """
    async with provide_azure_blob_async_container_client(
        azure_blob_service,
        azure_blob_default_container_name,
        fixture_name="azure_blob_async_container_client",
    ) as container_client:
        yield container_client


def _send_azurite_container_request(
    *,
    method: str,
    account_url: str,
    account_name: str,
    account_key: str,
    container_name: str,
    timeout: float = 5.0,
) -> int:
    """Issue a signed HTTP request against an Azurite blob container endpoint and return the status code."""
    ms_date = email.utils.formatdate(usegmt=True)
    auth_header = build_shared_key_authorization(
        method=method,
        account_name=account_name,
        account_key=account_key,
        container_name=container_name,
        ms_date=ms_date,
    )
    url = f"{account_url.rstrip('/')}/{container_name}?restype=container"
    headers = {
        "x-ms-date": ms_date,
        "x-ms-version": AZURE_API_VERSION,
        "Authorization": auth_header,
    }
    if method.upper() == "PUT":
        headers["Content-Length"] = "0"
    request = urllib.request.Request(
        url,
        data=None,
        headers=headers,
        method=method.upper(),
    )
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            return int(response.status)
    except urllib.error.HTTPError as exc:
        return int(exc.code)


def _create_account_options(number: int) -> list[tuple[str, str]]:
    """Generate worker-isolated Azurite account name and key pairs."""
    return [(f"test_account_{i}", DEFAULT_ACCOUNT_KEY) for i in range(number)]
