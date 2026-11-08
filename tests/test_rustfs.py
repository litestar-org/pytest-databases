"""Tests for RustFS S3-compatible object storage service fixtures."""

from __future__ import annotations

import io
import ssl
from contextlib import contextmanager
from datetime import UTC, datetime
from typing import TYPE_CHECKING
from unittest.mock import MagicMock
from urllib.error import HTTPError, URLError

import pytest

from pytest_databases._s3 import build_bucket_request, create_s3_bucket, derive_signing_key
from pytest_databases.docker.rustfs import (
    RUSTFS_IMAGE,
    RustfsService,
    provide_rustfs_service,
    rustfs_access_key,
    rustfs_default_bucket_name,
    rustfs_image,
    rustfs_secret_key,
)
from pytest_databases.types import ServiceContainer
from tests.conftest import unwrap_fixture

if TYPE_CHECKING:
    from collections.abc import Generator
    from urllib.request import Request


def test_default_credentials_and_image_are_configured() -> None:
    """Verify RustFS default credentials and image fixture values."""
    access_key = unwrap_fixture(rustfs_access_key)()
    secret_key = unwrap_fixture(rustfs_secret_key)()
    assert access_key != "rustfsadmin"
    assert secret_key != "rustfsadmin"
    assert "pytest-databases" in access_key
    assert "pytest-databases" in secret_key
    assert unwrap_fixture(rustfs_image)() == RUSTFS_IMAGE


def test_rustfs_default_bucket_name_isolates_xdist_workers(monkeypatch: pytest.MonkeyPatch) -> None:
    """Verify rustfs_default_bucket_name suffixes the worker index under database and server isolation."""
    bucket_fn = unwrap_fixture(rustfs_default_bucket_name)
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


@pytest.mark.parametrize(("secure", "expected"), [(False, "http://127.0.0.1:9000"), (True, "https://127.0.0.1:9000")])
def test_rustfs_service_endpoint_url(secure: bool, expected: str) -> None:
    """Verify RustfsService.endpoint_url follows the secure flag."""
    service = RustfsService(
        host="127.0.0.1",
        port=9000,
        container=MagicMock(),
        endpoint="127.0.0.1:9000",
        access_key="key",
        secret_key="secret",
        secure=secure,
    )
    assert service.endpoint_url == expected


def test_derive_signing_key_matches_aws_reference_vector() -> None:
    """Verify signing key derivation against the AWS Signature Version 4 documentation example."""
    key = derive_signing_key(
        "wJalrXUtnFEMI/K7MDENG+bPxRfiCYEXAMPLEKEY", date_stamp="20120215", region="us-east-1", service="iam"
    )
    assert key.hex() == "f4780e2d9f65fa895f9c67b32ce1baf0b0d8a43505a000a1a9e090d414db404d"


def test_build_bucket_request_known_signature() -> None:
    """Verify the exact SigV4 Authorization header for a frozen time, key, and region."""
    request = build_bucket_request(
        "PUT",
        "http://127.0.0.1:9000",
        "pytest-databases",
        access_key="AKIAIOSFODNN7EXAMPLE",
        secret_key="wJalrXUtnFEMI/K7MDENG/bPxRfiCYEXAMPLEKEY",
        region="us-east-1",
        timestamp=datetime(2013, 5, 24, tzinfo=UTC),
    )
    assert request.method == "PUT"
    assert request.full_url == "http://127.0.0.1:9000/pytest-databases"
    assert request.data is None
    assert request.get_header("X-amz-date") == "20130524T000000Z"
    assert request.get_header("Authorization") == (
        "AWS4-HMAC-SHA256 Credential=AKIAIOSFODNN7EXAMPLE/20130524/us-east-1/s3/aws4_request, "
        "SignedHeaders=host;x-amz-content-sha256;x-amz-date, "
        "Signature=45376d62a50eb1a6c50643167103283f188f10166edf4a3bb7a3ea5bd2a96b6c"
    )


@pytest.mark.parametrize("endpoint_url", ["ftp://127.0.0.1:9000", "127.0.0.1:9000", "file:///tmp"])
def test_build_bucket_request_rejects_non_http_endpoints(endpoint_url: str) -> None:
    """Verify only absolute http(s) endpoints are signed."""
    with pytest.raises(ValueError, match="valid http"):
        build_bucket_request("PUT", endpoint_url, "bucket", access_key="a", secret_key="s")


@pytest.mark.parametrize(
    ("endpoint_url", "verifies_tls"), [("http://127.0.0.1:9000", None), ("https://127.0.0.1:9000", False)]
)
def test_create_s3_bucket_sends_signed_put(
    monkeypatch: pytest.MonkeyPatch, endpoint_url: str, verifies_tls: bool | None
) -> None:
    """Verify create_s3_bucket sends one signed PUT and skips certificate checks only for https."""
    calls: list[tuple[Request, ssl.SSLContext | None]] = []

    def fake_urlopen(request: Request, *, timeout: float, context: ssl.SSLContext | None) -> MagicMock:
        calls.append((request, context))
        response = MagicMock(status=200)
        response.__enter__.return_value = response
        return response

    monkeypatch.setattr("pytest_databases._s3.urlopen", fake_urlopen)
    create_s3_bucket(endpoint_url, "test-bucket", access_key="test-key", secret_key="test-secret")

    assert len(calls) == 1
    request, context = calls[0]
    assert (request.method, request.full_url) == ("PUT", f"{endpoint_url}/test-bucket")
    assert str(request.get_header("Authorization")).startswith("AWS4-HMAC-SHA256 Credential=test-key/")
    if verifies_tls is None:
        assert context is None
    else:
        assert context is not None
        assert context.verify_mode == ssl.CERT_NONE
        assert context.check_hostname is False


@pytest.mark.parametrize("code", ["BucketAlreadyOwnedByYou", "BucketAlreadyExists"])
def test_create_s3_bucket_accepts_existing_bucket(monkeypatch: pytest.MonkeyPatch, code: str) -> None:
    """Verify an HTTP 409 for an existing bucket is not an error."""
    body = f"<Error><Code>{code}</Code></Error>".encode()
    error = HTTPError("http://127.0.0.1:9000/b", 409, "Conflict", MagicMock(), io.BytesIO(body))
    monkeypatch.setattr("pytest_databases._s3.urlopen", MagicMock(side_effect=error))
    create_s3_bucket("http://127.0.0.1:9000", "b", access_key="a", secret_key="s")


@pytest.mark.parametrize(
    ("error", "match"),
    [
        (
            HTTPError(
                "http://127.0.0.1:9000/b",
                403,
                "Forbidden",
                MagicMock(),
                io.BytesIO(b"<Error><Code>AccessDenied</Code></Error>"),
            ),
            "HTTP 403 - <Error><Code>AccessDenied",
        ),
        (URLError("connection refused"), "connection refused"),
    ],
)
def test_create_s3_bucket_raises_on_failure(monkeypatch: pytest.MonkeyPatch, error: Exception, match: str) -> None:
    """Verify rejected or unreachable bucket creation raises RuntimeError."""
    monkeypatch.setattr("pytest_databases._s3.urlopen", MagicMock(side_effect=error))
    with pytest.raises(RuntimeError, match=match):
        create_s3_bucket("http://127.0.0.1:9000", "b", access_key="a", secret_key="s")


def test_create_s3_bucket_retries_transient_503(monkeypatch: pytest.MonkeyPatch) -> None:
    """Verify HTTP 503 waiting-for-quorum responses retry until success or timeout."""
    ok_response = MagicMock(status=200)
    ok_response.__enter__.return_value = ok_response
    unavailable = HTTPError(
        "http://127.0.0.1:9000/b",
        503,
        "Service Unavailable",
        MagicMock(),
        io.BytesIO(b"Service not ready: waiting for storage_quorum"),
    )
    urlopen_mock = MagicMock(side_effect=[unavailable, ok_response])
    monkeypatch.setattr("pytest_databases._s3.urlopen", urlopen_mock)
    monkeypatch.setattr("pytest_databases._s3.time.sleep", lambda _seconds: None)
    create_s3_bucket("http://127.0.0.1:9000", "b", access_key="a", secret_key="s", timeout=5)
    assert urlopen_mock.call_count == 2

    def _raise_503(*_args: object, **_kwargs: object) -> object:
        url = "http://127.0.0.1:9000/b"
        reason = "Service Unavailable"
        raise HTTPError(url, 503, reason, MagicMock(), io.BytesIO(b"Service not ready: waiting for storage_quorum"))

    monkeypatch.setattr("pytest_databases._s3.urlopen", MagicMock(side_effect=_raise_503))
    times = iter([0.0, 0.1, 6.0])
    monkeypatch.setattr("pytest_databases._s3.time.monotonic", lambda: next(times))
    with pytest.raises(RuntimeError, match="HTTP 503 - Service not ready: waiting for storage_quorum"):
        create_s3_bucket("http://127.0.0.1:9000", "b", access_key="a", secret_key="s", timeout=5)


def test_rustfs_service_provisions_default_bucket_and_propagates_failure(monkeypatch: pytest.MonkeyPatch) -> None:
    """Verify provide_rustfs_service creates the default bucket and fails startup when that fails."""
    docker_service = MagicMock()

    @contextmanager
    def fake_run(**kwargs: object) -> Generator[ServiceContainer, None, None]:
        assert kwargs["image"] == RUSTFS_IMAGE
        yield ServiceContainer(host="127.0.0.1", port=39001, container=MagicMock())

    docker_service.run.side_effect = fake_run
    monkeypatch.setattr("pytest_databases._s3.urlopen", MagicMock(side_effect=URLError("refused")))

    with (
        pytest.raises(RuntimeError, match="Failed to create bucket 'pytest-databases'"),
        provide_rustfs_service(
            docker_service,
            access_key="a",
            secret_key="s",
            secure=False,
            default_bucket_name="pytest-databases",
            isolation_level="database",
        ),
    ):
        pass
    docker_service._client.containers.run.assert_not_called()


def test_rustfs_service_honors_image_fixture_override(pytester: pytest.Pytester) -> None:
    """Verify overriding the rustfs_image fixture changes the image passed to the container runtime."""
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
        yield ServiceContainer(host="127.0.0.1", port=39001, container=MagicMock())


@pytest.fixture(scope="session")
def docker_service():
    return RecordingDockerService()


@pytest.fixture(scope="session", autouse=True)
def _skip_bucket_creation():
    with pytest.MonkeyPatch.context() as mp:
        mp.setattr("pytest_databases.docker.rustfs.RustfsService.ensure_bucket", lambda self, name: None)
        yield


@pytest.fixture(scope="session")
def rustfs_image():
    return "registry.example.com/custom/rustfs:1.2.3"
""")
    pytester.makepyfile("""
pytest_plugins = ["pytest_databases.docker.rustfs"]

def test_override(rustfs_service, docker_service):
    assert docker_service.images == ["registry.example.com/custom/rustfs:1.2.3"]
""")
    result = pytester.runpytest_subprocess("-p", "pytest_databases")
    result.assert_outcomes(passed=1)


def test_default_no_xdist(pytester: pytest.Pytester) -> None:
    """Verify rustfs_service starts and responds on the health endpoint without xdist."""
    pytester.makepyfile("""
from urllib.error import HTTPError
from urllib.request import Request, urlopen
import pytest
from pytest_databases._s3 import build_bucket_request
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

def _head_bucket(service: RustfsService, bucket: str) -> int:
    request = build_bucket_request(
        "HEAD", service.endpoint_url, bucket, access_key=service.access_key, secret_key=service.secret_key
    )
    try:
        with urlopen(request) as response:
            return response.status
    except HTTPError as exc:
        return exc.code

def test_rustfs_default_bucket_exists(rustfs_service: RustfsService, rustfs_default_bucket_name: str) -> None:
    assert _head_bucket(rustfs_service, rustfs_default_bucket_name) == 200
    assert _head_bucket(rustfs_service, "missing-bucket") == 404
    rustfs_service.ensure_bucket("extra-bucket")
    rustfs_service.ensure_bucket("extra-bucket")
    assert _head_bucket(rustfs_service, "extra-bucket") == 200
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


@pytest.mark.parametrize(
    ("worker_num", "isolation_level", "secure", "expected_name", "expected_scheme"),
    [
        (None, "database", False, "rustfs", "http"),
        (2, "server", True, "rustfs_2", "https"),
    ],
)
def test_provide_rustfs_service_readiness_and_xdist(
    monkeypatch: pytest.MonkeyPatch,
    worker_num: int | None,
    isolation_level: str,
    secure: bool,
    expected_name: str,
    expected_scheme: str,
) -> None:
    """Verify provide_rustfs_service readiness check, endpoint_url, and xdist server mode."""
    monkeypatch.setattr("pytest_databases.docker.rustfs.get_xdist_worker_num", lambda: worker_num)
    monkeypatch.setattr("pytest_databases.docker.rustfs.create_s3_bucket", lambda *_a, **_kw: None)

    calls = 0

    def fake_urlopen(url: object, timeout: float = 10.0) -> object:
        nonlocal calls
        calls += 1
        if calls == 1:
            msg = "not ready"
            raise URLError(msg)
        cm = MagicMock()
        cm.__enter__.return_value = MagicMock(status=200)
        return cm

    monkeypatch.setattr("pytest_databases.docker.rustfs.urlopen", fake_urlopen)
    docker_service = MagicMock()
    captured_name: list[str] = []

    @contextmanager
    def fake_run(**kwargs: object) -> Generator[ServiceContainer, None, None]:
        captured_name.append(str(kwargs["name"]))
        svc = ServiceContainer(host="127.0.0.1", port=9000, container=MagicMock())
        check = kwargs["check"]
        assert callable(check)
        assert check(svc) is False
        assert check(svc) is True
        yield svc

    docker_service.run.side_effect = fake_run

    with provide_rustfs_service(
        docker_service,
        access_key="rustfs",
        secret_key="rustfs123",
        secure=secure,
        default_bucket_name="pytest-databases",
        isolation_level=isolation_level,  # type: ignore[arg-type]
    ) as service:
        assert service.endpoint_url == f"{expected_scheme}://127.0.0.1:9000"
        assert captured_name == [expected_name]


def test_rustfs_all_fixtures_inprocess(pytester: pytest.Pytester, monkeypatch: pytest.MonkeyPatch) -> None:
    """Verify all RustFS fixtures execute in-process with mocked docker_service."""
    monkeypatch.setenv("RUSTFS_DEFAULT_BUCKET_NAME", "custom-rustfs-bucket")
    assert unwrap_fixture(rustfs_default_bucket_name)("database") == "custom-rustfs-bucket"
    monkeypatch.delenv("RUSTFS_DEFAULT_BUCKET_NAME", raising=False)

    pytester.makepyfile("""
    from contextlib import contextmanager
    from unittest.mock import MagicMock
    import pytest
    import pytest_databases.docker.rustfs as rustfs_mod
    from pytest_databases.types import ServiceContainer

    pytest_plugins = ["pytest_databases.docker.rustfs"]

    @pytest.fixture(autouse=True, scope="session")
    def mock_bucket():
        orig = rustfs_mod.create_s3_bucket
        rustfs_mod.create_s3_bucket = lambda *a, **kw: None
        yield
        rustfs_mod.create_s3_bucket = orig

    @pytest.fixture(scope="session")
    def docker_service():
        mock_ds = MagicMock()
        @contextmanager
        def _run(image, **kwargs):
            yield ServiceContainer(host="127.0.0.1", port=9000, container=MagicMock())
        mock_ds.run.side_effect = _run
        return mock_ds

    def test_fixtures(
        rustfs_image,
        rustfs_access_key,
        rustfs_secret_key,
        rustfs_secure,
        xdist_rustfs_isolation_level,
        rustfs_default_bucket_name,
        rustfs_service,
    ):
        assert "rustfs" in rustfs_image
        assert rustfs_access_key
        assert rustfs_secret_key
        assert rustfs_secure is False
        assert xdist_rustfs_isolation_level == "database"
        assert rustfs_default_bucket_name == "pytest-databases"
        assert rustfs_service.port == 9000
    """)
    result = pytester.runpytest("-p", "no:sugar", "-p", "pytest_databases")
    result.assert_outcomes(passed=1)
