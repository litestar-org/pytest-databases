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

from pytest_databases.docker.spanner import spanner_responsive

if TYPE_CHECKING:
    from google.auth.credentials import Credentials

    from pytest_databases.docker import DockerServiceRegistry

pytestmark = pytest.mark.anyio
pytest_plugins = [
    "pytest_databases.docker.spanner",
]


async def test_spanner_default_config(
    spanner_port: int, spanner_instance: str, spanner_database: str, spanner_project: str
) -> None:
    assert spanner_port == 9010
    assert spanner_instance == "test-instance"
    assert spanner_database == "test-database"
    assert spanner_project == "emulator-test-project"


async def test_spanner_services(
    docker_ip: str,
    spanner_service: DockerServiceRegistry,
    spanner_port: int,
    spanner_instance: str,
    spanner_database: str,
    spanner_project: str,
    spanner_credentials: Credentials,
) -> None:
    ping = spanner_responsive(
        docker_ip,
        spanner_port=spanner_port,
        spanner_instance=spanner_instance,
        spanner_database=spanner_database,
        spanner_project=spanner_project,
        spanner_credentials=spanner_credentials,
    )
    assert ping
