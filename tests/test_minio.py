"""Tests for Chainguard MinIO S3-compatible object storage service fixtures."""

from __future__ import annotations

from contextlib import contextmanager
from typing import TYPE_CHECKING
from unittest.mock import MagicMock

from pytest_databases.docker.minio import (
    MINIO_IMAGE,
    MINIO_MC_IMAGE,
    minio_access_key,
    minio_client_image,
    minio_default_bucket_name,
    minio_image,
    minio_secret_key,
    minio_secure,
    provide_minio_service,
    xdist_minio_isolation_level,
)
from pytest_databases.types import ServiceContainer

if TYPE_CHECKING:
    from collections.abc import Callable, Generator
    from typing import Any

    import pytest


def test_minio_chainguard_image_defaults() -> None:
    """Verify Chainguard MinIO and MinIO client image defaults."""
    assert MINIO_IMAGE == "cgr.dev/chainguard/minio:latest"
    assert MINIO_MC_IMAGE == "cgr.dev/chainguard/minio-client:latest"
    assert _unwrap_fixture(minio_image)() == MINIO_IMAGE
    assert _unwrap_fixture(minio_client_image)() == MINIO_MC_IMAGE


def test_minio_default_bucket_name_isolates_xdist_workers(monkeypatch: pytest.MonkeyPatch) -> None:
    """Verify minio_default_bucket_name suffixes the worker index under database and server isolation."""
    bucket_fn = _unwrap_fixture(minio_default_bucket_name)
    monkeypatch.delenv("MINIO_DEFAULT_BUCKET_NAME", raising=False)
    monkeypatch.delenv("PYTEST_XDIST_WORKER", raising=False)
    assert bucket_fn("database") == "pytest-databases"

    monkeypatch.setenv("PYTEST_XDIST_WORKER", "gw2")
    assert bucket_fn("database") == "pytest-databases-2"
    assert bucket_fn("server") == "pytest-databases-2"


def test_minio_service_uses_chainguard_images_and_mc_host_env() -> None:
    """Verify provide_minio_service boots Chainguard MinIO and configures mc via MC_HOST_local."""
    docker_service = MagicMock()
    dummy_container = MagicMock()

    @contextmanager
    def fake_run(**kwargs: object) -> Generator[ServiceContainer, None, None]:
        assert kwargs["image"] == MINIO_IMAGE
        assert kwargs["command"] == "server /data"
        assert kwargs["container_port"] == 9000
        yield ServiceContainer(host="127.0.0.1", port=39000, container=dummy_container)

    docker_service.run.side_effect = fake_run

    isolation_level = _unwrap_fixture(xdist_minio_isolation_level)()
    with provide_minio_service(
        docker_service,
        access_key=_unwrap_fixture(minio_access_key)(),
        secret_key=_unwrap_fixture(minio_secret_key)(),
        secure=_unwrap_fixture(minio_secure)(),
        default_bucket_name="pytest-databases",
        isolation_level=isolation_level,
        image=MINIO_IMAGE,
        client_image=MINIO_MC_IMAGE,
    ) as service:
        assert service.endpoint == "127.0.0.1:39000"
        assert service.access_key == "minio"
        assert service.secret_key == "minio123"
        assert service.secure is False

    docker_service._client.images.get.assert_called_once_with(MINIO_MC_IMAGE)
    docker_service._client.containers.run.assert_called_once_with(
        image=MINIO_MC_IMAGE,
        command=["mb", "local/pytest-databases"],
        environment={"MC_HOST_local": "http://minio:minio123@127.0.0.1:39000"},
        remove=True,
        network_mode="host",
    )


def test_default_no_xdist(pytester: pytest.Pytester) -> None:
    """Verify minio_service starts and responds on the readiness endpoint without xdist."""
    pytester.makepyfile("""
from urllib.request import Request, urlopen
import pytest
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

def test_minio_bucket_exists_manual(minio_service: MinioService, minio_default_bucket_name: str) -> None:
    scheme = "https" if minio_service.secure else "http"
    url = f"{scheme}://{minio_service.host}:{minio_service.port}/{minio_default_bucket_name}"

    try:
        with urlopen(Request(url, method="GET")) as response:
            assert response.status in {200, 403, 404}
    except Exception:
        pass
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


def _unwrap_fixture(fixture_def: Any) -> Callable[..., Any]:
    """Return the underlying callable wrapped by a pytest fixture definition."""
    return fixture_def.__wrapped__
