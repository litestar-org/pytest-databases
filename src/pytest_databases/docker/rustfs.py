from __future__ import annotations

import os
from dataclasses import dataclass
from typing import TYPE_CHECKING
from urllib.error import URLError
from urllib.request import Request, urlopen

import boto3
import pytest
from botocore.config import Config
from botocore.exceptions import ClientError

from pytest_databases.docker import TRUE_VALUES
from pytest_databases.helpers import get_xdist_worker_num
from pytest_databases.types import ServiceContainer, XdistIsolationLevel

if TYPE_CHECKING:
    from collections.abc import Generator
    from typing import Any

    from pytest_databases._service import DockerService


@dataclass
class RustfsService(ServiceContainer):
    endpoint: str
    access_key: str
    secret_key: str
    secure: bool


@pytest.fixture(scope="session")
def rustfs_access_key() -> str:
    return os.getenv("RUSTFS_ACCESS_KEY", "rustfsadmin")


@pytest.fixture(scope="session")
def rustfs_secret_key() -> str:
    return os.getenv("RUSTFS_SECRET_KEY", "rustfsadmin")


@pytest.fixture(scope="session")
def rustfs_secure() -> bool:
    return os.getenv("RUSTFS_SECURE", "false").lower() in TRUE_VALUES


@pytest.fixture(scope="session")
def xdist_rustfs_isolation_level() -> XdistIsolationLevel:
    return "database"


@pytest.fixture(scope="session")
def rustfs_default_bucket_name(xdist_rustfs_isolation_level: XdistIsolationLevel) -> str:
    worker_num = get_xdist_worker_num()
    if worker_num is not None and xdist_rustfs_isolation_level == "server":
        return f"pytest-databases-{worker_num}"
    return "pytest-databases"


@pytest.fixture(scope="session")
def rustfs_service(
    docker_service: DockerService,
    rustfs_access_key: str,
    rustfs_secret_key: str,
    rustfs_secure: bool,
    xdist_rustfs_isolation_level: XdistIsolationLevel,
) -> Generator[RustfsService, None, None]:
    def check(_service: ServiceContainer) -> bool:
        scheme = "https" if rustfs_secure else "http"
        url = f"{scheme}://{_service.host}:{_service.port}/health"
        if not url.startswith(("http:", "https:")):
            msg = "URL must start with 'http:' or 'https:'"
            raise ValueError(msg)
        try:
            with urlopen(url=Request(url, method="GET"), timeout=10) as response:  # noqa: S310
                return response.status == 200
        except (URLError, ConnectionError):
            return False

    worker_num = get_xdist_worker_num()
    name = "rustfs"
    transient = False

    if worker_num is not None and xdist_rustfs_isolation_level == "server":
        name = f"{name}_{worker_num}"
        transient = True

    env = {
        "RUSTFS_ROOT_USER": rustfs_access_key,
        "RUSTFS_ROOT_PASSWORD": rustfs_secret_key,
    }

    with docker_service.run(
        image="rustfs/rustfs:latest",
        name=name,
        container_port=9000,
        timeout=30,
        pause=0.5,
        env=env,
        check=check,
        transient=transient,
    ) as service:
        yield RustfsService(
            host=service.host,
            port=service.port,
            endpoint=f"{service.host}:{service.port}",
            access_key=rustfs_access_key,
            secret_key=rustfs_secret_key,
            secure=rustfs_secure,
        )


@pytest.fixture(scope="session")
def rustfs_client(
    rustfs_service: RustfsService,
    rustfs_default_bucket_name: str,
) -> Generator[Any, None, None]:
    scheme = "https" if rustfs_service.secure else "http"
    endpoint_url = f"{scheme}://{rustfs_service.endpoint}"

    client = boto3.client(
        "s3",
        endpoint_url=endpoint_url,
        aws_access_key_id=rustfs_service.access_key,
        aws_secret_access_key=rustfs_service.secret_key,
        config=Config(signature_version="s3v4"),
        region_name="us-east-1",
    )

    try:
        client.head_bucket(Bucket=rustfs_default_bucket_name)
    except ClientError as e:
        error_code = e.response.get("Error", {}).get("Code", "")
        if error_code in {"404", "NoSuchBucket"}:
            try:
                client.create_bucket(Bucket=rustfs_default_bucket_name)
            except ClientError as create_error:
                msg = f"Failed to create bucket {rustfs_default_bucket_name}"
                raise RuntimeError(msg) from create_error
        else:
            msg = f"Failed to access bucket {rustfs_default_bucket_name}: {e}"
            raise RuntimeError(msg) from e
    except Exception as e:
        msg = f"Failed to check bucket {rustfs_default_bucket_name}"
        raise RuntimeError(msg) from e

    yield client
