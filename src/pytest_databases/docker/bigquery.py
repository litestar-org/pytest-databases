# MIT License

# Copyright (c) 2024 Litestar

# Permission is hereby granted, free of charge, to any person obtaining a copy
# of this software and associated documentation files (the "Software"), to deal
# in the Software without restriction, including without limitation the rights
# to use, copy, modify, merge, publish, distribute, sublicense, and/or sell
# copies of the Software, and to permit persons to whom the Software is
# furnished to do so, subject to the following conditions:

# The above copyright notice and this permission notice shall be included in all
# copies or substantial portions of the Software.

# THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
# IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,
# FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE
# AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER
# LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM,
# OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN THE
# SOFTWARE.


from __future__ import annotations

import os
import sys
from pathlib import Path
from typing import TYPE_CHECKING, AsyncGenerator

import pytest
from google.api_core.client_options import ClientOptions
from google.auth.credentials import AnonymousCredentials, Credentials
from google.cloud import bigquery

from pytest_databases.docker import DockerServiceRegistry
from pytest_databases.helpers import simple_string_hash

if TYPE_CHECKING:
    from collections.abc import Generator


COMPOSE_PROJECT_NAME: str = f"pytest-databases-bigquery-{simple_string_hash(__file__)}"


async def bigquery_responsive(
    host: str,
    bigquery_endpoint: str,
    bigquery_dataset: str,
    bigquery_client_options: ClientOptions,
    bigquery_project: str,
    bigquery_credentials: Credentials,
) -> bool:
    try:
        client = bigquery.Client(
            project=bigquery_project, client_options=bigquery_client_options, credentials=bigquery_credentials
        )

        job = client.query(query="SELECT 1 as one")

        resp = list(job.result())
        return resp[0].one == 1
    except Exception:  # noqa: BLE001
        return False


@pytest.fixture(scope="session")
def bigquery_compose_project_name() -> str:
    return os.environ.get("COMPOSE_PROJECT_NAME", COMPOSE_PROJECT_NAME)


@pytest.fixture(autouse=False, scope="session")
def bigquery_docker_services(
    bigquery_compose_project_name: str, worker_id: str = "main"
) -> Generator[DockerServiceRegistry, None, None]:
    if os.getenv("GITHUB_ACTIONS") == "true" and sys.platform != "linux":
        pytest.skip("Docker not available on this platform")

    registry = DockerServiceRegistry(worker_id, compose_project_name=bigquery_compose_project_name)
    try:
        yield registry
    finally:
        registry.down()


@pytest.fixture(scope="session")
def bigquery_port() -> int:
    return 9051


@pytest.fixture(scope="session")
def bigquery_grpc_port() -> int:
    return 9061


@pytest.fixture(scope="session")
def bigquery_dataset() -> str:
    return "test-dataset"


@pytest.fixture(scope="session")
def bigquery_project() -> str:
    return "emulator-test-project"


@pytest.fixture(scope="session")
def bigquery_client_options(bigquery_endpoint: str) -> ClientOptions:
    return ClientOptions(api_endpoint=bigquery_endpoint)


@pytest.fixture(scope="session")
def bigquery_credentials() -> Credentials:
    return AnonymousCredentials()


@pytest.fixture(scope="session")
def bigquery_docker_compose_files() -> list[Path]:
    return [Path(Path(__file__).parent / "docker-compose.bigquery.yml")]


@pytest.fixture(scope="session")
def default_bigquery_service_name() -> str:
    return "bigquery"


@pytest.fixture(scope="session")
def bigquery_docker_ip(bigquery_docker_services: DockerServiceRegistry) -> str:
    return bigquery_docker_services.docker_ip


@pytest.fixture(scope="session")
def bigquery_endpoint(bigquery_docker_ip: str, bigquery_port: int) -> str:
    return f"http://{bigquery_docker_ip}:{bigquery_port}"


@pytest.fixture(autouse=False, scope="session")
async def bigquery_service(
    bigquery_docker_services: DockerServiceRegistry,
    default_bigquery_service_name: str,
    bigquery_docker_compose_files: list[Path],
    bigquery_port: int,
    bigquery_grpc_port: int,
    bigquery_endpoint: str,
    bigquery_dataset: str,
    bigquery_project: str,
    bigquery_credentials: Credentials,
    bigquery_client_options: ClientOptions,
) -> AsyncGenerator[None, None]:
    os.environ["BIGQUERY_ENDPOINT"] = bigquery_endpoint
    os.environ["BIGQUERY_DATASET"] = bigquery_dataset
    os.environ["BIGQUERY_PORT"] = str(bigquery_port)
    os.environ["BIGQUERY_GRPC_PORT"] = str(bigquery_grpc_port)
    os.environ["GOOGLE_CLOUD_PROJECT"] = bigquery_project
    await bigquery_docker_services.start(
        name=default_bigquery_service_name,
        docker_compose_files=bigquery_docker_compose_files,
        timeout=60,
        check=bigquery_responsive,
        bigquery_endpoint=bigquery_endpoint,
        bigquery_dataset=bigquery_dataset,
        bigquery_project=bigquery_project,
        bigquery_credentials=bigquery_credentials,
        bigquery_client_options=bigquery_client_options,
    )
    yield
