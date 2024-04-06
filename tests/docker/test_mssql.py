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

from pytest_databases.docker.mssql import mssql_responsive

if TYPE_CHECKING:
    from pytest_databases.docker import DockerServiceRegistry

pytestmark = pytest.mark.anyio
pytest_plugins = [
    "pytest_databases.docker.mssql",
]


async def test_mssql_default_config(
    mssql_default_version: str,
    mssql_port: int,
    mssql_database: str,
    mssql_user: str,
    mssql_password: str,
) -> None:
    assert mssql_default_version == "mssql2022"
    assert mssql_port == 4133
    assert mssql_database == "master"
    assert mssql_user == "sa"
    assert mssql_password == "Super-secret1"


async def test_mssql_2022_config(
    mssql2022_port: int,
    mssql_database: str,
    mssql_user: str,
    mssql_password: str,
) -> None:
    assert mssql2022_port == 4133
    assert mssql_database == "master"
    assert mssql_user == "sa"
    assert mssql_password == "Super-secret1"


async def test_mssql_services(
    docker_ip: str,
    mssql_service: DockerServiceRegistry,
    mssql_port: int,
    mssql_database: str,
    mssql_user: str,
    mssql_password: str,
) -> None:
    connstring = f"encrypt=no; TrustServerCertificate=yes; driver={{ODBC Driver 18 for SQL Server}}; server={docker_ip},{mssql_port}; database={mssql_database}; UID={mssql_user}; PWD={mssql_password}"

    ping = await mssql_responsive(docker_ip, connstring=connstring)
    assert ping


async def test_mssql_2022_services(
    docker_ip: str,
    mssql2022_service: DockerServiceRegistry,
    mssql2022_port: int,
    mssql_database: str,
    mssql_user: str,
    mssql_password: str,
) -> None:
    connstring = f"encrypt=no; TrustServerCertificate=yes; driver={{ODBC Driver 18 for SQL Server}}; server={docker_ip},{mssql2022_port}; database={mssql_database}; UID={mssql_user}; PWD={mssql_password}"

    ping = await mssql_responsive(docker_ip, connstring=connstring)
    assert ping
