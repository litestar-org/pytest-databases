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

from pytest_databases.docker.cockroachdb import cockroachdb_responsive

if TYPE_CHECKING:
    from pytest_databases.docker import DockerServiceRegistry

pytestmark = pytest.mark.anyio
pytest_plugins = [
    "pytest_databases.docker.cockroachdb",
]


def test_cockroachdb_default_config(
    cockroachdb_port: int, cockroachdb_database: str, cockroachdb_driver_opts: dict[str, str]
) -> None:
    assert cockroachdb_port == 26257
    assert cockroachdb_database == "defaultdb"
    assert cockroachdb_driver_opts == {"sslmode": "disable"}


async def test_cockroachdb_service(
    docker_ip: str,
    cockroachdb_service: DockerServiceRegistry,
    cockroachdb_database: str,
    cockroachdb_port: int,
    cockroachdb_driver_opts: dict[str, str],
) -> None:
    ping = await cockroachdb_responsive(docker_ip, cockroachdb_port, cockroachdb_database, cockroachdb_driver_opts)
    assert ping
