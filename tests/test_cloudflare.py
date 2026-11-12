"""Tests for the Miniflare-backed Cloudflare KV, R2, and D1 emulator fixtures."""

from __future__ import annotations

import contextlib
import hashlib
import hmac
import http.server
import json
import os
import re
import shutil
import socket
import subprocess
import threading
import urllib.parse
from datetime import UTC, datetime
from typing import TYPE_CHECKING, Any, ClassVar
from unittest.mock import MagicMock

import pytest

from pytest_databases import helpers
from pytest_databases.docker import cloudflare
from pytest_databases.docker.cloudflare import (
    CLOUDFLARE_PORT,
    DEFAULT_CLOUDFLARE_IMAGE,
    DEFAULT_MINIFLARE_VERSION,
    LOCAL_EXPLORER_PATH,
    R2_S3_REGION,
    CloudflareService,
    provide_cloudflare_service,
)
from pytest_databases.helpers import EMPTY_PAYLOAD_SHA256, build_bucket_request, derive_signing_key
from pytest_databases.types import ServiceContainer

if TYPE_CHECKING:
    from collections.abc import Generator

    from pytest_databases._service import ContainerService

_TRICKY_NAMES = ('quote"name', "back\\slash", "</script>", "line\u2028sep", "\u65e5\u672c", "$(touch /tmp/x)")


class FakeExplorer(http.server.BaseHTTPRequestHandler):
    """Answer like Miniflare's Local Explorer API with in-memory KV, R2, and D1 state."""

    kv: ClassVar[dict[tuple[str, str], bytes]] = {}
    r2: ClassVar[dict[tuple[str, str], bytes]] = {}
    d1_requests: ClassVar[list[tuple[str, dict[str, Any]]]] = []
    raw_paths: ClassVar[list[str]] = []
    bound: ClassVar[dict[str, list[str]]] = {"kv": [], "r2": [], "d1": []}
    ready: ClassVar[bool] = True

    def do_GET(self) -> None:
        """Serve listings and stored values."""
        parts = self._parts()
        if parts == ["storage", "kv", "namespaces"]:
            if not self.ready:
                self._json(503, {"success": False, "errors": [{"code": 1, "message": "starting"}], "result": None})
                return
            self._ok([{"id": name, "title": f"KV_{i}"} for i, name in enumerate(self.bound["kv"])])
        elif parts == ["r2", "buckets"]:
            self._ok({"buckets": [{"name": name} for name in self.bound["r2"]]})
        elif parts == ["d1", "database"]:
            self._ok([{"name": f"D1_{i}", "uuid": name} for i, name in enumerate(self.bound["d1"])])
        elif len(parts) == 6 and parts[:3] == ["storage", "kv", "namespaces"]:
            self._raw(self.kv.get((parts[3], parts[5])))
        elif len(parts) == 5 and parts[:2] == ["r2", "buckets"]:
            self._raw(self.r2.get((parts[2], parts[4])))
        else:
            self._json(404, {"success": False, "errors": [{"code": 7003, "message": "No route"}], "result": None})

    def do_PUT(self) -> None:
        """Store KV values and R2 objects."""
        parts = self._parts()
        body = self.rfile.read(int(self.headers.get("Content-Length", "0")))
        if len(parts) == 6 and parts[:3] == ["storage", "kv", "namespaces"]:
            self.kv[parts[3], parts[5]] = body
            self._ok({})
        elif len(parts) == 5 and parts[:2] == ["r2", "buckets"]:
            self.r2[parts[2], parts[4]] = body
            self._ok({"key": parts[4], "size": len(body)})
        else:
            self._json(404, {"success": False, "errors": [], "result": None})

    def do_POST(self) -> None:
        """Answer D1 raw queries; ``FAIL`` statements fail like SQLite errors."""
        parts = self._parts()
        payload = json.loads(self.rfile.read(int(self.headers.get("Content-Length", "0"))))
        self.d1_requests.append((parts[2], payload))
        if payload["sql"] == "FAIL":
            self._json(500, {"success": False, "errors": [{"code": 10001, "message": "no such table: t"}]})
            return
        if payload["sql"] == "EMPTY":
            self._ok([])
            return
        rows = [[payload["sql"], value] for value in payload.get("params", [])]
        self._ok([{"success": True, "results": {"columns": ["sql", "value"], "rows": rows}, "meta": {}}])

    def _parts(self) -> list[str]:
        self.raw_paths.append(self.path)
        path = self.path.removeprefix(LOCAL_EXPLORER_PATH)
        return [urllib.parse.unquote(part) for part in path.strip("/").split("/")]

    def _ok(self, result: Any) -> None:
        self._json(200, {"success": True, "errors": [], "messages": [], "result": result})

    def _raw(self, value: bytes | None) -> None:
        if value is None:
            self._json(404, {"success": False, "errors": [{"code": 10009, "message": "Not Found"}], "result": None})
            return
        self.send_response(200)
        self.send_header("Content-Length", str(len(value)))
        self.end_headers()
        self.wfile.write(value)

    def _json(self, status: int, payload: dict[str, Any]) -> None:
        body = json.dumps(payload).encode()
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)


@pytest.fixture
def explorer() -> Generator[tuple[str, int], None, None]:
    """Run a fake Local Explorer API with empty state that binds ``default`` resources.

    Yields:
        The server host and port.
    """
    FakeExplorer.kv = {}
    FakeExplorer.r2 = {}
    FakeExplorer.d1_requests = []
    FakeExplorer.raw_paths = []
    FakeExplorer.bound = {"kv": ["default"], "r2": ["default"], "d1": ["default"]}
    FakeExplorer.ready = True
    server = http.server.ThreadingHTTPServer(("127.0.0.1", 0), FakeExplorer)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield "127.0.0.1", int(server.server_address[1])
    finally:
        server.shutdown()
        server.server_close()


@pytest.fixture
def closed_port() -> int:
    """Return a local TCP port with no listener."""
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.bind(("127.0.0.1", 0))
        return int(sock.getsockname()[1])


def _service(host: str, port: int, **overrides: Any) -> CloudflareService:
    values: dict[str, Any] = {
        "container": MagicMock(),
        "host": host,
        "port": port,
        "access_key_id": "key",
        "secret_access_key": "secret",
        "kv_namespaces": ("default",),
        "r2_buckets": ("default",),
        "d1_databases": ("default",),
    }
    return CloudflareService(**(values | overrides))


def _container_service(host: str, port: int) -> MagicMock:
    """Return a container service mock whose ``run`` yields a service at ``host:port``."""

    @contextlib.contextmanager
    def run(**_kwargs: Any) -> Generator[ServiceContainer, None, None]:
        yield ServiceContainer(container=MagicMock(), host=host, port=port)

    container_service = MagicMock()
    container_service.run.side_effect = run
    return container_service


def _provide(container_service: ContainerService, isolation: str = "database", **overrides: Any) -> Any:
    arguments: dict[str, Any] = {
        "container_service": container_service,
        "cloudflare_image": DEFAULT_CLOUDFLARE_IMAGE,
        "cloudflare_miniflare_version": DEFAULT_MINIFLARE_VERSION,
        "cloudflare_kv_namespaces": ("default", "cache"),
        "cloudflare_r2_buckets": ("default",),
        "cloudflare_d1_databases": ("default",),
        "cloudflare_access_key_id": "key",
        "cloudflare_secret_access_key": "secret",
        "xdist_cloudflare_isolation_level": isolation,
    }
    return provide_cloudflare_service(**(arguments | overrides))


def test_plugin_imports_without_cloudflare_clients(pytester: pytest.Pytester) -> None:
    """Ensure the Cloudflare module imports cleanly when Cloudflare and AWS client packages are absent."""
    pytester.makepyfile("""
    import builtins
    import importlib

    def test_import() -> None:
        original_import = builtins.__import__
        blocked = {"boto3", "botocore", "cloudflare", "miniflare"}

        def blocked_import(name, globals=None, locals=None, fromlist=(), level=0):
            if name.partition(".")[0] in blocked:
                raise ModuleNotFoundError(name)
            return original_import(name, globals, locals, fromlist, level)

        builtins.__import__ = blocked_import
        try:
            module = importlib.import_module("pytest_databases.docker.cloudflare")
            assert module.CloudflareService
        finally:
            builtins.__import__ = original_import
    """)

    result = pytester.runpytest_subprocess("-p", "pytest_databases", "-vv")
    result.assert_outcomes(passed=1)


@pytest.mark.parametrize(
    ("method", "path", "data", "expected_status"),
    [
        ("GET", "/storage/kv/namespaces/default/values/missing", None, 404),
        ("PUT", "/storage/kv/namespaces/default/values/k", b"v", 200),
        ("GET", "/no/such/route", None, 404),
    ],
)
def test_http_request_returns_error_statuses(
    explorer: tuple[str, int], method: str, path: str, data: bytes | None, expected_status: int
) -> None:
    """``http_request`` returns HTTP error statuses and their body instead of raising."""
    host, port = explorer
    status, body = helpers.http_request(f"http://{host}:{port}{LOCAL_EXPLORER_PATH}{path}", method=method, data=data)
    assert status == expected_status
    assert json.loads(body)["success"] is (expected_status == 200)


def test_http_request_ignores_proxy_environment(explorer: tuple[str, int], monkeypatch: pytest.MonkeyPatch) -> None:
    """Container endpoints are contacted directly even when ``HTTP_PROXY`` points at an unreachable proxy."""
    host, port = explorer
    monkeypatch.setenv("HTTP_PROXY", "http://127.0.0.1:9")
    monkeypatch.setenv("http_proxy", "http://127.0.0.1:9")
    status, _ = helpers.http_request(f"http://{host}:{port}{LOCAL_EXPLORER_PATH}/r2/buckets")
    assert status == 200


def test_http_request_raises_on_connection_failure(closed_port: int) -> None:
    """Connection failures raise ``OSError`` so callers can tell them apart from HTTP statuses."""
    with pytest.raises(OSError, match="refused"):
        helpers.http_request(f"http://127.0.0.1:{closed_port}/", timeout=1.0)


@pytest.mark.parametrize("url", ["file:///etc/passwd", "ftp://example.test/file"])
def test_http_request_rejects_non_http_urls(url: str) -> None:
    """Only http(s) URLs are requested."""
    with pytest.raises(ValueError, match="Only http"):
        helpers.http_request(url)


def test_kv_round_trip_encodes_keys(explorer: tuple[str, int]) -> None:
    """KV values round-trip as bytes, keys are sent as one encoded path segment, and missing keys read as None."""
    service = _service(*explorer)
    service.kv_put("default", "a/b c?", "\u65e5\u672c")
    service.kv_put("default", "binary", bytes(range(256)))
    assert service.kv_get("default", "a/b c?") == "\u65e5\u672c".encode()
    assert service.kv_get("default", "binary") == bytes(range(256))
    assert service.kv_get("default", "missing") is None
    assert f"{LOCAL_EXPLORER_PATH}/storage/kv/namespaces/default/values/a%2Fb%20c%3F" in FakeExplorer.raw_paths


def test_r2_round_trip_keeps_slashes_in_keys(explorer: tuple[str, int]) -> None:
    """R2 object keys containing ``/`` are stored under the full key, not as nested routes."""
    service = _service(*explorer)
    service.r2_put("default", "dir/file.txt", b"body")
    assert FakeExplorer.r2 == {("default", "dir/file.txt"): b"body"}
    assert service.r2_get("default", "dir/file.txt") == b"body"
    assert service.r2_get("default", "dir/other.txt") is None


def test_d1_query_sends_string_params_and_maps_rows(explorer: tuple[str, int]) -> None:
    """``d1_query`` posts ``sql`` and string ``params`` and returns one dict per row."""
    service = _service(*explorer)
    rows = service.d1_query("default", "SELECT ?", ["it's", "2"])
    assert rows == [{"sql": "SELECT ?", "value": "it's"}, {"sql": "SELECT ?", "value": "2"}]
    assert service.d1_query("default", "SELECT 1") == []
    assert FakeExplorer.d1_requests == [
        ("default", {"sql": "SELECT ?", "params": ["it's", "2"]}),
        ("default", {"sql": "SELECT 1"}),
    ]


@pytest.mark.parametrize(
    ("sql", "message"), [("FAIL", "HTTP 500 no such table: t"), ("EMPTY", "returned no result set")]
)
def test_d1_query_reports_failures(explorer: tuple[str, int], sql: str, message: str) -> None:
    """Failed statements raise with the emulator's error message."""
    with pytest.raises(RuntimeError, match=message):
        _service(*explorer).d1_query("default", sql)


@pytest.mark.parametrize(
    ("call", "kind"),
    [
        (lambda s: s.kv_put("other", "k", "v"), "KV namespace"),
        (lambda s: s.kv_get("other", "k"), "KV namespace"),
        (lambda s: s.r2_put("other", "k", "v"), "R2 bucket"),
        (lambda s: s.r2_get("other", "k"), "R2 bucket"),
        (lambda s: s.d1_query("other", "SELECT 1"), "D1 database"),
    ],
)
def test_helpers_reject_unconfigured_resources(explorer: tuple[str, int], call: Any, kind: str) -> None:
    """Helpers refuse resource names the service does not own, before any request is sent."""
    with pytest.raises(ValueError, match=f"{kind} 'other' is not configured"):
        call(_service(*explorer))
    assert FakeExplorer.raw_paths == []


def test_service_endpoints() -> None:
    """The Local Explorer and R2 S3 endpoint URLs are derived from the mapped host and port."""
    service = _service("10.0.0.5", 49152)
    assert service.endpoint_url == "http://10.0.0.5:49152"
    assert service.api_base_url == "http://10.0.0.5:49152/cdn-cgi/local/explorer/api"
    assert service.r2_s3_endpoint_url == "http://10.0.0.5:49152/cdn-cgi/local/r2/s3"


@pytest.mark.parametrize(("ready", "expected"), [(True, True), (False, False)])
def test_readiness_requires_successful_kv_listing(explorer: tuple[str, int], ready: bool, expected: bool) -> None:
    """The emulator is ready once the KV namespace listing answers ``success: true``."""
    FakeExplorer.ready = ready
    host, port = explorer
    assert cloudflare._is_cloudflare_ready(ServiceContainer(container=MagicMock(), host=host, port=port)) is expected


def test_readiness_is_false_without_listener(closed_port: int) -> None:
    """A port without a listener is not ready."""
    service = ServiceContainer(container=MagicMock(), host="127.0.0.1", port=closed_port)
    assert cloudflare._is_cloudflare_ready(service) is False


def test_build_bucket_request_keeps_endpoint_path() -> None:
    """SigV4 bucket requests against a path-prefixed endpoint sign and target ``<path>/<bucket>``."""
    timestamp = datetime(2026, 1, 2, 3, 4, 5, tzinfo=UTC)
    request = build_bucket_request(
        "GET",
        "http://127.0.0.1:8787/cdn-cgi/local/r2/s3/",
        "default_0",
        access_key="key",
        secret_key="secret",
        region=R2_S3_REGION,
        timestamp=timestamp,
    )
    assert request.full_url == "http://127.0.0.1:8787/cdn-cgi/local/r2/s3/default_0"
    canonical_request = (
        "GET\n/cdn-cgi/local/r2/s3/default_0\n\n"
        f"host:127.0.0.1:8787\nx-amz-content-sha256:{EMPTY_PAYLOAD_SHA256}\nx-amz-date:20260102T030405Z\n\n"
        f"host;x-amz-content-sha256;x-amz-date\n{EMPTY_PAYLOAD_SHA256}"
    )
    string_to_sign = (
        "AWS4-HMAC-SHA256\n20260102T030405Z\n20260102/auto/s3/aws4_request\n"
        f"{hashlib.sha256(canonical_request.encode()).hexdigest()}"
    )
    key = derive_signing_key("secret", date_stamp="20260102", region="auto", service="s3")
    signature = hmac.new(key, string_to_sign.encode(), hashlib.sha256).hexdigest()
    assert str(request.get_header("Authorization")).endswith(f"Signature={signature}")


@pytest.mark.parametrize(
    ("worker", "worker_count", "isolation", "name", "transient", "bound_kv", "bound_default", "service_kv"),
    [
        (None, None, "database", "cloudflare", False, ["default", "cache"], ["default"], ("default", "cache")),
        (None, None, "server", "cloudflare", False, ["default", "cache"], ["default"], ("default", "cache")),
        (
            "gw1",
            "2",
            "database",
            "cloudflare",
            False,
            ["default_0", "cache_0", "default_1", "cache_1"],
            ["default_0", "default_1"],
            ("default_1", "cache_1"),
        ),
        ("gw1", "2", "server", "cloudflare_1", True, ["default", "cache"], ["default"], ("default", "cache")),
    ],
)
def test_provide_cloudflare_service_isolation(
    explorer: tuple[str, int],
    monkeypatch: pytest.MonkeyPatch,
    worker: str | None,
    worker_count: str | None,
    isolation: str,
    name: str,
    transient: bool,
    bound_kv: list[str],
    bound_default: list[str],
    service_kv: tuple[str, ...],
) -> None:
    """Database isolation binds every worker's suffixed names in one container; server isolation starts one each."""
    for var, value in (("PYTEST_XDIST_WORKER", worker), ("PYTEST_XDIST_WORKER_COUNT", worker_count)):
        if value is None:
            monkeypatch.delenv(var, raising=False)
        else:
            monkeypatch.setenv(var, value)
    FakeExplorer.bound = {"kv": bound_kv, "r2": bound_default, "d1": bound_default}
    container_service = _container_service(*explorer)

    with _provide(container_service, isolation) as service:
        assert service.kv_namespaces == service_kv
        assert service.r2_buckets == service_kv[:1]
        assert service.d1_databases == service_kv[:1]

    kwargs = container_service.run.call_args.kwargs
    assert kwargs["name"] == name
    assert kwargs["transient"] is transient
    assert kwargs["container_port"] == CLOUDFLARE_PORT
    assert kwargs["image"] == DEFAULT_CLOUDFLARE_IMAGE
    assert kwargs["timeout"] == 300
    config = json.loads(kwargs["env"]["PYTEST_DATABASES_CLOUDFLARE_CONFIG"])
    assert config["kv_namespaces"] == bound_kv
    assert config["r2_buckets"] == config["d1_databases"] == bound_default


def test_provide_cloudflare_service_rejects_container_without_worker_resources(
    explorer: tuple[str, int], monkeypatch: pytest.MonkeyPatch
) -> None:
    """A reused container that lacks this worker's bindings fails with an actionable error."""
    monkeypatch.setenv("PYTEST_XDIST_WORKER", "gw1")
    monkeypatch.setenv("PYTEST_XDIST_WORKER_COUNT", "2")
    FakeExplorer.bound = {"kv": ["default_0", "cache_0"], "r2": ["default_0"], "d1": ["default_0"]}

    with (
        pytest.raises(RuntimeError, match=r"does not bind KV namespace 'default_1'.*remove the container"),
        _provide(_container_service(*explorer)),
    ):
        pytest.fail("the service must not be yielded")


def test_container_configuration_is_passed_as_json_not_code(
    explorer: tuple[str, int], monkeypatch: pytest.MonkeyPatch
) -> None:
    """Names and credentials reach the container only as ASCII JSON in the environment, never inside the script."""
    monkeypatch.delenv("PYTEST_XDIST_WORKER", raising=False)
    FakeExplorer.bound = {"kv": list(_TRICKY_NAMES), "r2": ["default"], "d1": ["default"]}
    container_service = _container_service(*explorer)

    with _provide(
        container_service,
        cloudflare_kv_namespaces=_TRICKY_NAMES,
        cloudflare_access_key_id='k"ey',
        cloudflare_secret_access_key="secret\\key",
        cloudflare_miniflare_version="5.0.0-test",
    ):
        pass

    kwargs = container_service.run.call_args.kwargs
    env = kwargs["env"]
    raw_config = env["PYTEST_DATABASES_CLOUDFLARE_CONFIG"]
    assert raw_config.isascii()
    config = json.loads(raw_config)
    assert config["kv_namespaces"] == list(_TRICKY_NAMES)
    assert (config["access_key_id"], config["secret_access_key"]) == ('k"ey', "secret\\key")
    assert env["PYTEST_DATABASES_MINIFLARE_VERSION"] == "5.0.0-test"
    script = env["PYTEST_DATABASES_CLOUDFLARE_SERVER"]
    assert "JSON.parse(process.env.PYTEST_DATABASES_CLOUDFLARE_CONFIG)" in script
    assert not any(name in script for name in (*_TRICKY_NAMES, 'k"ey', "secret\\key"))
    assert kwargs["entrypoint"] == ["/bin/sh", "-c"]
    assert kwargs["command"] == [cloudflare._BOOTSTRAP]


@pytest.mark.skipif(shutil.which("sh") is None, reason="needs a POSIX shell")
def test_bootstrap_is_valid_shell_and_skips_installed_dependencies() -> None:
    """The bootstrap parses as POSIX shell and guards both installs so prebuilt images skip them."""
    sh = shutil.which("sh")
    assert sh is not None
    subprocess.run([sh, "-n", "-c", cloudflare._BOOTSTRAP], check=True)
    lines = cloudflare._BOOTSTRAP.splitlines()
    apt_guard = lines.index("if [ ! -s /etc/ssl/certs/ca-certificates.crt ]; then")
    npm_guard = next(i for i, line in enumerate(lines) if "import.meta.resolve('miniflare')" in line)
    assert "apt-get install" in lines[apt_guard + 2]
    assert re.search(r'npm install .*"miniflare@\$PYTEST_DATABASES_MINIFLARE_VERSION"', lines[npm_guard + 1])
    assert lines[-1] == "exec node server.mjs"


def test_cloudflare_contract_fixtures(pytester: pytest.Pytester, monkeypatch: pytest.MonkeyPatch) -> None:
    """Verify the default image, Miniflare version, resources, credentials, timeout, and isolation level."""
    for var in (
        "CLOUDFLARE_IMAGE",
        "CLOUDFLARE_MINIFLARE_VERSION",
        "CLOUDFLARE_ACCESS_KEY_ID",
        "CLOUDFLARE_SECRET_ACCESS_KEY",
        "CLOUDFLARE_STARTUP_TIMEOUT",
    ):
        monkeypatch.delenv(var, raising=False)
    pytester.makepyfile(f"""
    pytest_plugins = ["pytest_databases.docker.cloudflare"]

    def test_contract(
        cloudflare_image,
        cloudflare_miniflare_version,
        cloudflare_kv_namespaces,
        cloudflare_r2_buckets,
        cloudflare_d1_databases,
        cloudflare_access_key_id,
        cloudflare_secret_access_key,
        cloudflare_startup_timeout,
        xdist_cloudflare_isolation_level,
    ) -> None:
        assert cloudflare_image == {DEFAULT_CLOUDFLARE_IMAGE!r} == "node:22-slim"
        assert cloudflare_miniflare_version == {DEFAULT_MINIFLARE_VERSION!r}
        assert cloudflare_miniflare_version.startswith("5.")
        assert cloudflare_kv_namespaces == cloudflare_r2_buckets == cloudflare_d1_databases == ("default",)
        assert cloudflare_access_key_id == "pytest-databases"
        assert cloudflare_secret_access_key == "pytest-databases-secret"
        assert cloudflare_startup_timeout == 300
        assert xdist_cloudflare_isolation_level == "database"
    """)

    result = pytester.runpytest_subprocess("-p", "pytest_databases", "-vv")
    result.assert_outcomes(passed=1)


def _s3_status(service: CloudflareService, method: str, bucket: str, *, secret: str | None = None) -> tuple[int, str]:
    """Send a SigV4-signed bucket request to the R2 S3 endpoint and return its status and body."""
    request = build_bucket_request(
        method,
        service.r2_s3_endpoint_url,
        bucket,
        access_key=service.access_key_id,
        secret_key=secret or service.secret_access_key,
        region=R2_S3_REGION,
    )
    status, body = helpers.http_request(request.full_url, method=method, headers=dict(request.header_items()))
    return status, body.decode("utf-8", errors="replace")


def test_cloudflare_service_live_round_trips(container_service: ContainerService) -> None:
    """KV, R2 (Local Explorer and S3 SigV4), and D1 work against a real Miniflare container."""
    with provide_cloudflare_service(
        container_service=container_service,
        cloudflare_image=os.getenv("CLOUDFLARE_IMAGE", DEFAULT_CLOUDFLARE_IMAGE),
        cloudflare_miniflare_version=DEFAULT_MINIFLARE_VERSION,
        cloudflare_kv_namespaces=("default", "cache"),
        cloudflare_r2_buckets=("default",),
        cloudflare_d1_databases=("default",),
        cloudflare_access_key_id="pytest-databases",
        cloudflare_secret_access_key="pytest-databases-secret",
        xdist_cloudflare_isolation_level="server",
    ) as service:
        namespace, cache = service.kv_namespaces
        service.kv_put(namespace, "dir/key", "\u65e5\u672c")
        service.kv_put(namespace, "binary", bytes(range(256)))
        service.kv_put(cache, "dir/key", "other namespace")
        assert service.kv_get(namespace, "dir/key") == "\u65e5\u672c".encode()
        assert service.kv_get(namespace, "binary") == bytes(range(256))
        assert service.kv_get(cache, "dir/key") == b"other namespace"
        assert service.kv_get(namespace, "missing") is None

        bucket = service.r2_buckets[0]
        service.r2_put(bucket, "reports/2026.txt", b"r2 body")
        assert service.r2_get(bucket, "reports/2026.txt") == b"r2 body"
        assert service.r2_get(bucket, "reports/missing.txt") is None

        status, listing = _s3_status(service, "GET", bucket)
        assert status == 200
        assert "<Key>reports/2026.txt</Key>" in listing
        assert _s3_status(service, "HEAD", bucket)[0] == 200
        assert _s3_status(service, "HEAD", "unbound")[0] == 404
        assert _s3_status(service, "GET", bucket, secret="wrong-secret")[0] == 403

        database = service.d1_databases[0]
        service.d1_query(database, "CREATE TABLE IF NOT EXISTS items (id INTEGER PRIMARY KEY, name TEXT)")
        service.d1_query(database, "INSERT INTO items (id, name) VALUES (?, ?)", ["1", "it's"])
        service.d1_query(database, "INSERT INTO items (id, name) VALUES (?, ?)", ["2", "second"])
        rows = service.d1_query(database, "SELECT id, name FROM items WHERE id >= ? ORDER BY id", ["1"])
        assert rows == [{"id": 1, "name": "it's"}, {"id": 2, "name": "second"}]
        with pytest.raises(RuntimeError, match="no such table"):
            service.d1_query(database, "SELECT * FROM missing")


@pytest.mark.xdist_group(name="cloudflare_nested_xdist")
def test_cloudflare_service_live_xdist_database_isolation(
    pytester: pytest.Pytester, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Under xdist with ``database`` isolation, workers share one container and own ``default_<worker>`` resources."""
    for var in ("PYTEST_XDIST_WORKER", "PYTEST_XDIST_TESTRUNUID", "PYTEST_XDIST_WORKER_COUNT"):
        monkeypatch.delenv(var, raising=False)
    monkeypatch.setenv("CLOUDFLARE_RECORD_DIR", str(pytester.path))
    pytester.makepyfile("""
    import json
    import os
    from pathlib import Path

    import pytest

    pytest_plugins = ["pytest_databases.docker.cloudflare"]

    @pytest.mark.parametrize("case", [0, 1])
    def test_isolation(cloudflare_service, case) -> None:
        worker_id = os.environ["PYTEST_XDIST_WORKER"]
        suffix = f"_{int(worker_id.removeprefix('gw'))}"
        names = (cloudflare_service.kv_namespaces, cloudflare_service.r2_buckets, cloudflare_service.d1_databases)
        assert names == ((f"default{suffix}",),) * 3
        namespace, bucket, database = (group[0] for group in names)
        cloudflare_service.kv_put(namespace, f"owner-{case}", worker_id)
        cloudflare_service.r2_put(bucket, f"owner-{case}", worker_id)
        cloudflare_service.d1_query(database, f"CREATE TABLE IF NOT EXISTS owner_{case} (worker TEXT)")
        cloudflare_service.d1_query(database, f"INSERT INTO owner_{case} VALUES (?)", [worker_id])
        assert cloudflare_service.kv_get(namespace, f"owner-{case}") == worker_id.encode()
        assert cloudflare_service.r2_get(bucket, f"owner-{case}") == worker_id.encode()
        assert cloudflare_service.d1_query(database, f"SELECT worker FROM owner_{case}") == [{"worker": worker_id}]
        record = {"container_id": cloudflare_service.container.id, "namespace": namespace}
        path = Path(os.environ["CLOUDFLARE_RECORD_DIR"]) / f"cloudflare-{worker_id}.json"
        path.write_text(json.dumps(record), encoding="utf-8")
    """)

    result = pytester.runpytest_subprocess("-p", "pytest_databases", "-n", "2", "--dist=load", "-vv")
    result.assert_outcomes(passed=2)
    records = [json.loads(path.read_text(encoding="utf-8")) for path in pytester.path.glob("cloudflare-gw*.json")]
    assert len(records) == 2
    assert {record["namespace"] for record in records} == {"default_0", "default_1"}
    assert len({record["container_id"] for record in records}) == 1


def test_cloudflare_all_fixtures_inprocess(pytester: pytest.Pytester) -> None:
    """Verify Cloudflare config and service fixtures execute in-process with mocked provider."""
    pytester.makepyfile("""
    from contextlib import contextmanager
    from unittest.mock import MagicMock, patch
    import pytest

    pytest_plugins = ["pytest_databases.docker.cloudflare"]

    @pytest.fixture(scope="session")
    def container_service() -> MagicMock:
        return MagicMock()

    def test_fixtures(request: pytest.FixtureRequest) -> None:
        mock_svc = MagicMock()

        @contextmanager
        def fake_svc(*args, **kwargs):
            yield mock_svc

        with patch("pytest_databases.docker.cloudflare.provide_cloudflare_service", side_effect=fake_svc):
            assert request.getfixturevalue("xdist_cloudflare_isolation_level") == "database"
            assert request.getfixturevalue("cloudflare_image")
            assert request.getfixturevalue("cloudflare_miniflare_version")
            assert request.getfixturevalue("cloudflare_kv_namespaces") == ("default",)
            assert request.getfixturevalue("cloudflare_r2_buckets") == ("default",)
            assert request.getfixturevalue("cloudflare_d1_databases") == ("default",)
            assert request.getfixturevalue("cloudflare_access_key_id") == "pytest-databases"
            assert request.getfixturevalue("cloudflare_secret_access_key") == "pytest-databases-secret"
            assert request.getfixturevalue("cloudflare_startup_timeout") == 300
            assert request.getfixturevalue("cloudflare_service") is mock_svc
    """)
    result = pytester.runpytest("-p", "no:sugar", "-p", "pytest_databases")
    result.assert_outcomes(passed=1)
