"""Tests for RustFS S3-compatible object storage service fixtures."""

from __future__ import annotations

import http.server
import shutil
import socket
import ssl
import subprocess
import threading
from contextlib import contextmanager
from datetime import UTC, datetime
from typing import TYPE_CHECKING
from unittest.mock import MagicMock
from urllib.error import URLError

import pytest

from pytest_databases.docker.rustfs import (
    RUSTFS_IMAGE,
    RustfsService,
    provide_rustfs_service,
    rustfs_access_key,
    rustfs_default_bucket_name,
    rustfs_image,
    rustfs_secret_key,
)
from pytest_databases.helpers import build_bucket_request, create_s3_bucket, derive_signing_key
from pytest_databases.types import ServiceContainer
from tests.conftest import unwrap_fixture

if TYPE_CHECKING:
    from collections.abc import Generator
    from pathlib import Path


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


def _start_rustfs_loopback(
    responses: dict[tuple[str, str], list[tuple[int, bytes]]],
    *,
    ssl_context: ssl.SSLContext | None = None,
) -> tuple[http.server.ThreadingHTTPServer, list[tuple[str, str, str | None]]]:
    recorded: list[tuple[str, str, str | None]] = []
    remaining = {key: list(values) for key, values in responses.items()}

    class _Handler(http.server.BaseHTTPRequestHandler):
        def _handle(self) -> None:
            length = int(self.headers.get("Content-Length", "0"))
            if length:
                self.rfile.read(length)
            recorded.append((self.command, self.path, self.headers.get("Authorization")))
            queue = remaining.get((self.command, self.path))
            status, body = queue.pop(0) if queue else (200, b"")
            self.send_response(status)
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            if body:
                self.wfile.write(body)

        def do_GET(self) -> None:
            self._handle()

        def do_PUT(self) -> None:
            self._handle()

        def log_request(self, code: int | str = "-", size: int | str = "-") -> None:
            return

    server = http.server.ThreadingHTTPServer(("127.0.0.1", 0), _Handler)
    if ssl_context is not None:
        server.socket = ssl_context.wrap_socket(server.socket, server_side=True)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    return server, recorded


def _create_rustfs_self_signed_context(tmp_path: Path) -> ssl.SSLContext:
    cert_path = tmp_path / "rustfs-cert.pem"
    key_path = tmp_path / "rustfs-key.pem"
    openssl_bin = shutil.which("openssl")
    assert openssl_bin is not None
    subprocess.run(
        [
            openssl_bin,
            "req",
            "-x509",
            "-newkey",
            "rsa:2048",
            "-nodes",
            "-keyout",
            str(key_path),
            "-out",
            str(cert_path),
            "-days",
            "1",
            "-subj",
            "/CN=127.0.0.1",
        ],
        check=True,
        capture_output=True,
    )
    ctx = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
    ctx.load_cert_chain(certfile=str(cert_path), keyfile=str(key_path))
    return ctx


@pytest.mark.parametrize(("secure", "status_code"), [(False, 200), (True, 204)])
def test_create_s3_bucket_sends_signed_put(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, secure: bool, status_code: int
) -> None:
    """Verify create_s3_bucket sends one signed PUT bypassing proxies and skips TLS verification for https."""
    monkeypatch.setenv("HTTP_PROXY", "http://127.0.0.1:1")
    monkeypatch.setenv("HTTPS_PROXY", "http://127.0.0.1:1")
    ssl_ctx = _create_rustfs_self_signed_context(tmp_path) if secure else None
    server, recorded = _start_rustfs_loopback({("PUT", "/test-bucket"): [(status_code, b"")]}, ssl_context=ssl_ctx)
    scheme = "https" if secure else "http"
    endpoint_url = f"{scheme}://127.0.0.1:{server.server_address[1]}"
    try:
        assert create_s3_bucket(endpoint_url, "test-bucket", access_key="test-key", secret_key="test-secret") is True
    finally:
        server.shutdown()
        server.server_close()

    assert len(recorded) == 1
    method, path, auth = recorded[0]
    assert (method, path) == ("PUT", "/test-bucket")
    assert str(auth).startswith("AWS4-HMAC-SHA256 Credential=test-key/")


@pytest.mark.parametrize("code", ["BucketAlreadyOwnedByYou", "BucketAlreadyExists"])
def test_create_s3_bucket_accepts_existing_bucket(monkeypatch: pytest.MonkeyPatch, code: str) -> None:
    """Verify an HTTP 409 for an existing bucket returns False instead of raising."""
    monkeypatch.setenv("HTTP_PROXY", "http://127.0.0.1:1")
    body = f"<Error><Code>{code}</Code></Error>".encode()
    server, _recorded = _start_rustfs_loopback({("PUT", "/b"): [(409, body)]})
    try:
        endpoint = f"http://127.0.0.1:{server.server_address[1]}"
        assert create_s3_bucket(endpoint, "b", access_key="a", secret_key="s") is False
    finally:
        server.shutdown()
        server.server_close()


def test_create_s3_bucket_raises_on_failure(monkeypatch: pytest.MonkeyPatch) -> None:
    """Verify rejected HTTP 403 or unreachable ports raise RuntimeError."""
    monkeypatch.setenv("HTTP_PROXY", "http://127.0.0.1:1")
    server, _recorded = _start_rustfs_loopback({("PUT", "/b"): [(403, b"<Error><Code>AccessDenied</Code></Error>")]})
    try:
        endpoint = f"http://127.0.0.1:{server.server_address[1]}"
        with pytest.raises(RuntimeError, match="HTTP 403 - <Error><Code>AccessDenied"):
            create_s3_bucket(endpoint, "b", access_key="a", secret_key="s")
    finally:
        server.shutdown()
        server.server_close()

    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as closed_sock:
        closed_sock.bind(("127.0.0.1", 0))
        closed_port = int(closed_sock.getsockname()[1])
    with pytest.raises(RuntimeError, match=f"Failed to create bucket 'b' on http://127.0.0.1:{closed_port}"):
        create_s3_bucket(f"http://127.0.0.1:{closed_port}", "b", access_key="a", secret_key="s", timeout=1.0)


def test_create_s3_bucket_retries_transient_503(monkeypatch: pytest.MonkeyPatch) -> None:
    """Verify HTTP 503 waiting-for-quorum responses retry until success or timeout."""
    monkeypatch.setenv("HTTP_PROXY", "http://127.0.0.1:1")
    monkeypatch.setattr("pytest_databases.helpers.time.sleep", lambda _seconds: None)
    server, recorded = _start_rustfs_loopback({
        ("PUT", "/b"): [
            (503, b"Service not ready: waiting for storage_quorum"),
            (503, b"Service not ready: waiting for storage_quorum"),
            (200, b""),
        ]
    })
    try:
        endpoint = f"http://127.0.0.1:{server.server_address[1]}"
        assert create_s3_bucket(endpoint, "b", access_key="a", secret_key="s", timeout=5) is True
        assert len(recorded) == 3
    finally:
        server.shutdown()
        server.server_close()

    monkeypatch.setattr(
        "pytest_databases.helpers.send_http_request",
        MagicMock(return_value=(503, {}, b"Service not ready: waiting for storage_quorum")),
    )
    times = iter([0.0, 0.1, 6.0])
    monkeypatch.setattr("pytest_databases.helpers.time.monotonic", lambda: next(times))
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
    monkeypatch.setattr("pytest_databases.helpers.send_http_request", MagicMock(side_effect=URLError("refused")))

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
from pytest_databases.docker.rustfs import RustfsService
from pytest_databases.helpers import build_bucket_request

pytest_plugins = [
    "pytest_databases.docker.rustfs",
]

def test_rustfs_service_fixture(rustfs_service: RustfsService, rustfs_default_bucket_name: str) -> None:
    assert rustfs_service.host == "127.0.0.1"
    assert rustfs_service.port > 0
    assert rustfs_default_bucket_name == "pytest-databases"

    from pytest_databases.helpers import http_request
    scheme = "https" if rustfs_service.secure else "http"
    url = f"{scheme}://{rustfs_service.host}:{rustfs_service.port}/health"
    status, _body = http_request(url, method="GET")
    assert status == 200

def _head_bucket(service: RustfsService, bucket: str) -> int:
    from pytest_databases.helpers import send_http_request
    request = build_bucket_request(
        "HEAD", service.endpoint_url, bucket, access_key=service.access_key, secret_key=service.secret_key
    )
    status, _headers, _body = send_http_request(request)
    return status

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
    from pytest_databases.helpers import http_request
    worker_num = get_xdist_worker_num()
    assert rustfs_default_bucket_name == f"pytest-databases-{worker_num}"

    scheme = "https" if rustfs_service.secure else "http"
    url = f"{scheme}://{rustfs_service.host}:{rustfs_service.port}/health"
    status, _body = http_request(url, method="GET")
    assert status == 200

def test_isolation_two(rustfs_service: RustfsService, rustfs_default_bucket_name: str) -> None:
    from pytest_databases.helpers import http_request
    worker_num = get_xdist_worker_num()
    assert rustfs_default_bucket_name == f"pytest-databases-{worker_num}"

    scheme = "https" if rustfs_service.secure else "http"
    url = f"{scheme}://{rustfs_service.host}:{rustfs_service.port}/health"
    status, _body = http_request(url, method="GET")
    assert status == 200
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
    tmp_path: Path,
    worker_num: int | None,
    isolation_level: str,
    secure: bool,
    expected_name: str,
    expected_scheme: str,
) -> None:
    """Verify provide_rustfs_service readiness check, endpoint_url, TLS, and proxy bypass."""
    monkeypatch.setenv("HTTP_PROXY", "http://127.0.0.1:1")
    monkeypatch.setenv("HTTPS_PROXY", "http://127.0.0.1:1")
    monkeypatch.setattr("pytest_databases.docker.rustfs.get_xdist_worker_num", lambda: worker_num)

    ssl_context = _create_rustfs_self_signed_context(tmp_path) if secure else None
    server, recorded = _start_rustfs_loopback(
        {
            ("GET", "/health"): [(503, b""), (200, b"")],
            ("PUT", "/pytest-databases"): [(200, b"")],
        },
        ssl_context=ssl_context,
    )
    port = server.server_address[1]
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as closed_sock:
        closed_sock.bind(("127.0.0.1", 0))
        closed_port = int(closed_sock.getsockname()[1])

    docker_service = MagicMock()
    captured_name: list[str] = []

    @contextmanager
    def fake_run(**kwargs: object) -> Generator[ServiceContainer, None, None]:
        captured_name.append(str(kwargs["name"]))
        svc = ServiceContainer(host="127.0.0.1", port=port, container=MagicMock())
        unreachable_svc = ServiceContainer(host="127.0.0.1", port=closed_port, container=MagicMock())
        check = kwargs["check"]
        assert callable(check)
        assert check(unreachable_svc) is False
        assert check(svc) is False
        assert check(svc) is True
        yield svc

    docker_service.run.side_effect = fake_run

    try:
        with provide_rustfs_service(
            docker_service,
            access_key="rustfs",
            secret_key="rustfs123",
            secure=secure,
            default_bucket_name="pytest-databases",
            isolation_level=isolation_level,  # type: ignore[arg-type]
        ) as service:
            assert service.endpoint_url == f"{expected_scheme}://127.0.0.1:{port}"
            assert captured_name == [expected_name]
    finally:
        server.shutdown()
        server.server_close()

    assert [(m, p) for m, p, _auth in recorded] == [
        ("GET", "/health"),
        ("GET", "/health"),
        ("PUT", "/pytest-databases"),
    ]


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
