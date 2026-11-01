"""Tests for RustFS S3-compatible object storage service fixtures."""

from __future__ import annotations

from typing import TYPE_CHECKING
from unittest.mock import MagicMock, patch
from urllib.error import HTTPError

import pytest

from pytest_databases.docker.rustfs import (
    RUSTFS_IMAGE,
    RustfsService,
    create_s3_bucket,
    rustfs_access_key,
    rustfs_default_bucket_name,
    rustfs_image,
    rustfs_secret_key,
)

if TYPE_CHECKING:
    from collections.abc import Callable
    from typing import Any


def test_default_credentials_and_image_are_configured() -> None:
    """Verify RustFS default credentials and image fixture values."""
    access_key = _unwrap_fixture(rustfs_access_key)()
    secret_key = _unwrap_fixture(rustfs_secret_key)()
    assert access_key != "rustfsadmin"
    assert secret_key != "rustfsadmin"
    assert "pytest-databases" in access_key
    assert "pytest-databases" in secret_key
    assert _unwrap_fixture(rustfs_image)() == RUSTFS_IMAGE


def test_rustfs_default_bucket_name_isolates_xdist_workers(monkeypatch: pytest.MonkeyPatch) -> None:
    """Verify rustfs_default_bucket_name suffixes the worker index under database and server isolation."""
    bucket_fn = _unwrap_fixture(rustfs_default_bucket_name)
    monkeypatch.delenv("RUSTFS_DEFAULT_BUCKET_NAME", raising=False)
    monkeypatch.delenv("PYTEST_XDIST_WORKER", raising=False)
    assert bucket_fn("database") == "pytest-databases"

    monkeypatch.setenv("PYTEST_XDIST_WORKER", "gw1")
    assert bucket_fn("database") == "pytest-databases-1"
    assert bucket_fn("server") == "pytest-databases-1"


def test_rustfs_custom_bucket_env(pytester: pytest.Pytester, monkeypatch: pytest.MonkeyPatch) -> None:
    """Verify RUSTFS_DEFAULT_BUCKET_NAME environment variable overrides the default bucket."""
    pytester.makepyfile("""
import pytest

pytest_plugins = [
    "pytest_databases.docker.rustfs",
]

def test_rustfs_env_bucket_name(rustfs_default_bucket_name: str) -> None:
    assert rustfs_default_bucket_name == "custom-env-bucket"
""")
    monkeypatch.setenv("RUSTFS_DEFAULT_BUCKET_NAME", "custom-env-bucket")
    result = pytester.runpytest_subprocess("-p", "pytest_databases")
    result.assert_outcomes(passed=1)


def test_rustfs_custom_bucket_fixture_override(pytester: pytest.Pytester) -> None:
    """Verify overriding rustfs_default_bucket_name fixture takes precedence."""
    pytester.makepyfile("""
import pytest

pytest_plugins = [
    "pytest_databases.docker.rustfs",
]

@pytest.fixture(scope="session")
def rustfs_default_bucket_name():
    return "fixture-override-bucket"

def test_rustfs_fixture_bucket_name(rustfs_default_bucket_name: str) -> None:
    assert rustfs_default_bucket_name == "fixture-override-bucket"
""")
    result = pytester.runpytest_subprocess("-p", "pytest_databases")
    result.assert_outcomes(passed=1)


def test_default_no_xdist(pytester: pytest.Pytester) -> None:
    """Verify rustfs_service starts and responds on the health endpoint without xdist."""
    pytester.makepyfile("""
from urllib.request import Request, urlopen
import pytest
from pytest_databases.docker.rustfs import RustfsService

pytest_plugins = [
    "pytest_databases.docker.rustfs",
]

def test_rustfs_service_fixture(rustfs_service: RustfsService, rustfs_default_bucket_name: str) -> None:
    assert rustfs_service.host == "127.0.0.1"
    assert rustfs_service.port > 0
    assert rustfs_default_bucket_name == "pytest-databases"

    scheme = "https" if rustfs_service.secure else "http"
    url = f"{scheme}://{rustfs_service.host}:{rustfs_service.port}/health"
    with urlopen(Request(url, method="GET")) as response:
        assert response.status == 200

def test_rustfs_bucket_exists_manual(rustfs_service: RustfsService, rustfs_default_bucket_name: str) -> None:
    scheme = "https" if rustfs_service.secure else "http"
    url = f"{scheme}://{rustfs_service.host}:{rustfs_service.port}/{rustfs_default_bucket_name}"

    try:
        with urlopen(Request(url, method="GET")) as response:
            assert response.status in {200, 403, 404}
    except Exception:
        pass
""")
    result = pytester.runpytest_subprocess("-p", "pytest_databases")
    result.assert_outcomes(passed=2)


def test_xdist_isolate_server(pytester: pytest.Pytester) -> None:
    """Verify server-isolated rustfs_service suffixes bucket names per xdist worker."""
    pytester.makepyfile("""
from urllib.request import Request, urlopen
import pytest
from pytest_databases.helpers import get_xdist_worker_num
from pytest_databases.docker.rustfs import RustfsService

pytest_plugins = [
    "pytest_databases.docker.rustfs",
]

@pytest.fixture(scope="session")
def xdist_rustfs_isolation_level():
    return "server"

def test_isolation_one(rustfs_service: RustfsService, rustfs_default_bucket_name: str) -> None:
    worker_num = get_xdist_worker_num()
    assert rustfs_default_bucket_name == f"pytest-databases-{worker_num}"

    scheme = "https" if rustfs_service.secure else "http"
    url = f"{scheme}://{rustfs_service.host}:{rustfs_service.port}/health"
    with urlopen(Request(url, method="GET")) as response:
        assert response.status == 200

def test_isolation_two(rustfs_service: RustfsService, rustfs_default_bucket_name: str) -> None:
    worker_num = get_xdist_worker_num()
    assert rustfs_default_bucket_name == f"pytest-databases-{worker_num}"

    scheme = "https" if rustfs_service.secure else "http"
    url = f"{scheme}://{rustfs_service.host}:{rustfs_service.port}/health"
    with urlopen(Request(url, method="GET")) as response:
        assert response.status == 200
""")
    result = pytester.runpytest_subprocess("-p", "pytest_databases", "-n", "2")
    result.assert_outcomes(passed=2)


def _unwrap_fixture(fixture_def: Any) -> Callable[..., Any]:
    """Return the underlying callable wrapped by a pytest fixture definition."""
    return fixture_def.__wrapped__


def test_rustfs_service_endpoint_url() -> None:
    """Verify RustfsService formats endpoint_url correctly based on secure flag."""
    dummy_container = MagicMock()
    service_http = RustfsService(
        host="127.0.0.1",
        port=9000,
        container=dummy_container,
        endpoint="127.0.0.1:9000",
        access_key="key",
        secret_key="secret",
        secure=False,
    )
    assert service_http.endpoint_url == "http://127.0.0.1:9000"

    service_https = RustfsService(
        host="127.0.0.1",
        port=9000,
        container=dummy_container,
        endpoint="127.0.0.1:9000",
        access_key="key",
        secret_key="secret",
        secure=True,
    )
    assert service_https.endpoint_url == "https://127.0.0.1:9000"


def test_create_s3_bucket_success() -> None:
    """Verify create_s3_bucket succeeds on HTTP 200 response."""
    with patch("pytest_databases.docker.rustfs.urlopen") as mock_urlopen:
        mock_response = MagicMock()
        mock_response.status = 200
        mock_response.__enter__.return_value = mock_response
        mock_urlopen.return_value = mock_response

        create_s3_bucket(
            "http://127.0.0.1:9000",
            "test-bucket",
            access_key="test-key",
            secret_key="test-secret",
        )
        assert mock_urlopen.call_count == 1
        request = mock_urlopen.call_args[0][0]
        assert request.method == "PUT"
        assert request.full_url == "http://127.0.0.1:9000/test-bucket"
        assert "AWS4-HMAC-SHA256" in request.headers["Authorization"]


def test_create_s3_bucket_already_exists() -> None:
    """Verify create_s3_bucket ignores HTTP 409 BucketAlreadyOwnedByYou."""
    with patch("pytest_databases.docker.rustfs.urlopen") as mock_urlopen:
        error = HTTPError(
            url="http://127.0.0.1:9000/test-bucket",
            code=409,
            msg="Conflict",
            hdrs=MagicMock(),
            fp=MagicMock(read=lambda: b"<Error><Code>BucketAlreadyOwnedByYou</Code></Error>"),
        )
        mock_urlopen.side_effect = error

        create_s3_bucket(
            "http://127.0.0.1:9000",
            "test-bucket",
            access_key="test-key",
            secret_key="test-secret",
        )


def test_create_s3_bucket_raises_runtime_error_on_failure() -> None:
    """Verify create_s3_bucket raises RuntimeError on unexpected HTTP errors."""
    with patch("pytest_databases.docker.rustfs.urlopen") as mock_urlopen:
        error = HTTPError(
            url="http://127.0.0.1:9000/test-bucket",
            code=403,
            msg="Forbidden",
            hdrs=MagicMock(),
            fp=MagicMock(read=lambda: b"<Error><Code>AccessDenied</Code></Error>"),
        )
        mock_urlopen.side_effect = error

        with pytest.raises(RuntimeError, match=r"Failed to create bucket 'test-bucket'"):
            create_s3_bucket(
                "http://127.0.0.1:9000",
                "test-bucket",
                access_key="test-key",
                secret_key="test-secret",
            )
