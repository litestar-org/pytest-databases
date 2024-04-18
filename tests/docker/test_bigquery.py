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

from typing import TYPE_CHECKING

import pytest

from pytest_databases.docker.bigquery import bigquery_responsive

if TYPE_CHECKING:
    from google.api_core.client_options import ClientOptions
    from google.auth.credentials import Credentials

    from pytest_databases.docker import DockerServiceRegistry

pytestmark = pytest.mark.anyio
pytest_plugins = [
    "pytest_databases.docker.bigquery",
]


def test_bigquery_default_config(
    docker_ip: str,
    bigquery_port: int,
    bigquery_grpc_port: int,
    bigquery_dataset: str,
    bigquery_endpoint: str,
    bigquery_project: str,
) -> None:
    assert bigquery_port == 9051
    assert bigquery_grpc_port == 9061
    assert bigquery_dataset == "test-dataset"
    assert bigquery_endpoint == f"http://{docker_ip}:9051"
    assert bigquery_project == "emulator-test-project"


async def test_bigquery_services(
    docker_ip: str,
    bigquery_service: DockerServiceRegistry,
    bigquery_endpoint: str,
    bigquery_dataset: str,
    bigquery_client_options: ClientOptions,
    bigquery_project: str,
    bigquery_credentials: Credentials,
) -> None:
    ping = await bigquery_responsive(
        docker_ip,
        bigquery_endpoint=bigquery_endpoint,
        bigquery_dataset=bigquery_dataset,
        bigquery_project=bigquery_project,
        bigquery_credentials=bigquery_credentials,
        bigquery_client_options=bigquery_client_options,
    )
    assert ping
