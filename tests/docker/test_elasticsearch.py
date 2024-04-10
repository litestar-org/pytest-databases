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

from typing import TYPE_CHECKING, Callable
from unittest import mock

import pytest
from elasticsearch7 import AsyncElasticsearch as Elasticsearch7
from elasticsearch8 import AsyncElasticsearch as Elasticsearch8

from pytest_databases.docker.elastic_search import elasticsearch7_responsive, elasticsearch8_responsive

if TYPE_CHECKING:
    from pytest_databases.docker import DockerServiceRegistry

pytestmark = pytest.mark.anyio
pytest_plugins = [
    "pytest_databases.docker.elastic_search",
]


def test_elasticsearch7_default_config(
    elasticsearch7_port: str, elasticsearch_user: str, elasticsearch_password: str, elasticsearch_scheme: str
) -> None:
    assert elasticsearch7_port == 9200
    assert elasticsearch_user == "elastic"
    assert elasticsearch_password == "changeme"
    assert elasticsearch_scheme == "http"


def test_elasticsearch8_default_config(
    elasticsearch8_port: str, elasticsearch_user: str, elasticsearch_password: str, elasticsearch_scheme: str
) -> None:
    assert elasticsearch8_port == 9201
    assert elasticsearch_user == "elastic"
    assert elasticsearch_password == "changeme"
    assert elasticsearch_scheme == "http"


async def test_elasticsearch7_service(
    docker_ip: str,
    elasticsearch7_service: DockerServiceRegistry,
    elasticsearch7_port: str,
    elasticsearch_user: str,
    elasticsearch_password: str,
    elasticsearch_scheme: str,
) -> None:
    async with Elasticsearch7(
        hosts=[{"host": docker_ip, "port": elasticsearch7_port, "scheme": elasticsearch_scheme}],
        verify_certs=False,
        http_auth=(elasticsearch_user, elasticsearch_password),
    ) as client:
        info = await client.info()

    assert info["version"]["number"] == "7.17.19"


async def test_elasticsearch8_service(
    docker_ip: str,
    elasticsearch8_service: DockerServiceRegistry,
    elasticsearch8_port: str,
    elasticsearch_user: str,
    elasticsearch_password: str,
    elasticsearch_scheme: str,
) -> None:
    async with Elasticsearch8(
        hosts=[{"host": docker_ip, "port": elasticsearch8_port, "scheme": elasticsearch_scheme}],
        verify_certs=False,
        basic_auth=(elasticsearch_user, elasticsearch_password),
    ) as client:
        info = await client.info()

    assert info["version"]["number"] == "8.13.0"


@pytest.mark.parametrize(
    "responsive, path_to_mock",
    (
        (elasticsearch7_responsive, "pytest_databases.docker.elastic_search.Elasticsearch7.ping"),
        (elasticsearch8_responsive, "pytest_databases.docker.elastic_search.Elasticsearch8.ping"),
    ),
)
async def test_elasticsearch_responsive(responsive: Callable, path_to_mock: str) -> None:
    with mock.patch(path_to_mock, mock.Mock(side_effect=Exception)):
        assert not await responsive(scheme="", host="", port="", user="", password="", database="")
