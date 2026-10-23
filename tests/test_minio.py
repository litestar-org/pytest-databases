"""Tests for Chainguard MinIO S3-compatible object storage service fixtures."""

from __future__ import annotations

from contextlib import contextmanager
from typing import TYPE_CHECKING
from unittest.mock import MagicMock

import pytest

from pytest_databases.docker.minio import (
    MINIO_IMAGE,
    MinioService,
    minio_access_key,
    minio_default_bucket_name,
    minio_image,
    minio_secret_key,
    minio_secure,
    provide_minio_service,
    xdist_minio_isolation_level,
)
from pytest_databases.types import ServiceContainer
from tests.conftest import unwrap_fixture

if TYPE_CHECKING:
    from collections.abc import Generator
    from urllib.request import Request


def test_minio_chainguard_image_default() -> None:
    """Verify the Chainguard MinIO image default."""
    assert MINIO_IMAGE == "cgr.dev/chainguard/minio:latest"
    assert unwrap_fixture(minio_image)() == MINIO_IMAGE


def test_minio_default_bucket_name_isolates_xdist_workers(monkeypatch: pytest.MonkeyPatch) -> None:
    """Verify minio_default_bucket_name suffixes the worker index under database and server isolation."""
    bucket_fn = unwrap_fixture(minio_default_bucket_name)
    monkeypatch.delenv("MINIO_DEFAULT_BUCKET_NAME", raising=False)
    monkeypatch.delenv("PYTEST_XDIST_WORKER", raising=False)
    assert bucket_fn("database") == "pytest-databases"

    monkeypatch.setenv("PYTEST_XDIST_WORKER", "gw2")
    assert bucket_fn("database") == "pytest-databases-2"
    assert bucket_fn("server") == "pytest-databases-2"


@pytest.mark.parametrize(("secure", "expected"), [(False, "http://127.0.0.1:9000"), (True, "https://127.0.0.1:9000")])
def test_minio_service_endpoint_url(secure: bool, expected: str) -> None:
    """Verify MinioService.endpoint_url follows the secure flag."""
    service = MinioService(
        host="127.0.0.1",
        port=9000,
        container=MagicMock(),
        endpoint="127.0.0.1:9000",
        access_key="key",
        secret_key="secret",
        secure=secure,
    )
    assert service.endpoint_url == expected


def test_minio_service_provisions_default_bucket_via_sigv4(monkeypatch: pytest.MonkeyPatch) -> None:
    """Verify provide_minio_service boots MinIO and creates the default bucket with a signed PUT."""
    docker_service = MagicMock()
    sent: list[Request] = []

    @contextmanager
    def fake_run(**kwargs: object) -> Generator[ServiceContainer, None, None]:
        assert kwargs["image"] == MINIO_IMAGE
        assert kwargs["command"] == "server /data"
        assert kwargs["container_port"] == 9000
        yield ServiceContainer(host="127.0.0.1", port=39000, container=MagicMock())

    def fake_urlopen(request: Request, **_: object) -> MagicMock:
        sent.append(request)
        response = MagicMock(status=200)
        response.__enter__.return_value = response
        return response

    docker_service.run.side_effect = fake_run
    monkeypatch.setattr("pytest_databases._s3.urlopen", fake_urlopen)

    with provide_minio_service(
        docker_service,
        access_key=unwrap_fixture(minio_access_key)(),
        secret_key=unwrap_fixture(minio_secret_key)(),
        secure=unwrap_fixture(minio_secure)(),
        default_bucket_name="pytest-databases",
        isolation_level=unwrap_fixture(xdist_minio_isolation_level)(),
    ) as service:
        assert service.endpoint == "127.0.0.1:39000"
        assert service.endpoint_url == "http://127.0.0.1:39000"
        assert service.access_key == "minio"
        assert service.secret_key == "minio123"
        assert service.secure is False

    assert [(request.method, request.full_url) for request in sent] == [
        ("PUT", "http://127.0.0.1:39000/pytest-databases")
    ]
    assert str(sent[0].get_header("Authorization")).startswith("AWS4-HMAC-SHA256 Credential=minio/")
    docker_service._client.containers.run.assert_not_called()


def test_minio_service_honors_image_fixture_override(pytester: pytest.Pytester) -> None:
    """Verify overriding the minio_image fixture changes the image passed to the container runtime."""
    pytester.makeconftest("""
from contextlib import contextmanager

import pytest
from unittest.mock import MagicMock

from pytest_databases.types import ServiceContainer


class RecordingDockerService:
    def __init__(self):
        self.images = []

    @contextmanager
    def run(self, *, image, **kwargs):
        self.images.append(image)
        yield ServiceContainer(host="127.0.0.1", port=39000, container=MagicMock())


@pytest.fixture(scope="session")
def docker_service():
    return RecordingDockerService()


@pytest.fixture(scope="session", autouse=True)
def _skip_bucket_creation():
    with pytest.MonkeyPatch.context() as mp:
        mp.setattr("pytest_databases.docker.minio.MinioService.ensure_bucket", lambda self, name: None)
        yield


@pytest.fixture(scope="session")
def minio_image():
    return "registry.example.com/custom/minio:1.2.3"
""")
    pytester.makepyfile("""
pytest_plugins = ["pytest_databases.docker.minio"]

def test_override(minio_service, docker_service):
    assert docker_service.images == ["registry.example.com/custom/minio:1.2.3"]
""")
    result = pytester.runpytest_subprocess("-p", "pytest_databases")
    result.assert_outcomes(passed=1)


def test_default_no_xdist(pytester: pytest.Pytester) -> None:
    """Verify minio_service starts and responds on the readiness endpoint without xdist."""
    pytester.makepyfile("""
from urllib.error import HTTPError
from urllib.request import Request, urlopen
import pytest
from pytest_databases._s3 import build_bucket_request
from pytest_databases.docker.minio import MinioService

pytest_plugins = [
    "pytest_databases.docker.minio",
]

def test_minio_service_fixture(minio_service: MinioService, minio_default_bucket_name: str) -> None:
    assert minio_service.host == "127.0.0.1"
    assert minio_service.port > 0
    assert minio_default_bucket_name == "pytest-databases"

    scheme = "https" if minio_service.secure else "http"
    url = f"{scheme}://{minio_service.host}:{minio_service.port}/minio/health/ready"
    with urlopen(Request(url, method="GET")) as response:
        assert response.status == 200

def _head_bucket(service: MinioService, bucket: str) -> int:
    request = build_bucket_request(
        "HEAD", service.endpoint_url, bucket, access_key=service.access_key, secret_key=service.secret_key
    )
    try:
        with urlopen(request) as response:
            return response.status
    except HTTPError as exc:
        return exc.code

def test_minio_default_bucket_exists(minio_service: MinioService, minio_default_bucket_name: str) -> None:
    assert _head_bucket(minio_service, minio_default_bucket_name) == 200
    assert _head_bucket(minio_service, "missing-bucket") == 404
    minio_service.ensure_bucket("extra-bucket")
    minio_service.ensure_bucket("extra-bucket")
    assert _head_bucket(minio_service, "extra-bucket") == 200
""")
    result = pytester.runpytest_subprocess("-p", "pytest_databases")
    result.assert_outcomes(passed=2)


def test_xdist_isolate_server(pytester: pytest.Pytester) -> None:
    """Verify server-isolated minio_service suffixes bucket names per xdist worker."""
    pytester.makepyfile("""
from urllib.request import Request, urlopen
import pytest
from pytest_databases.helpers import get_xdist_worker_num
from pytest_databases.docker.minio import MinioService

pytest_plugins = [
    "pytest_databases.docker.minio",
]

@pytest.fixture(scope="session")
def xdist_minio_isolation_level():
    return "server"

def test_isolation_one(minio_service: MinioService, minio_default_bucket_name: str) -> None:
    worker_num = get_xdist_worker_num()
    assert minio_default_bucket_name == f"pytest-databases-{worker_num}"

    scheme = "https" if minio_service.secure else "http"
    url = f"{scheme}://{minio_service.host}:{minio_service.port}/minio/health/ready"
    with urlopen(Request(url, method="GET")) as response:
        assert response.status == 200

def test_isolation_two(minio_service: MinioService, minio_default_bucket_name: str) -> None:
    worker_num = get_xdist_worker_num()
    assert minio_default_bucket_name == f"pytest-databases-{worker_num}"

    scheme = "https" if minio_service.secure else "http"
    url = f"{scheme}://{minio_service.host}:{minio_service.port}/minio/health/ready"
    with urlopen(Request(url, method="GET")) as response:
        assert response.status == 200
""")
    result = pytester.runpytest_subprocess("-p", "pytest_databases", "-n", "2")
    result.assert_outcomes(passed=2)
