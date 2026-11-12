"""Tests for Floci multi-cloud (GCP, OCI, AWS, Azure) emulator container fixtures and HTTP helpers."""

from __future__ import annotations

import hashlib
import http.client
import json
import os
import socket
import threading
import urllib.error
from contextlib import contextmanager
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import TYPE_CHECKING, Any
from unittest.mock import MagicMock

import pytest

from pytest_databases.docker import floci
from pytest_databases.docker.floci import (
    DEFAULT_FLOCI_AWS_IMAGE,
    DEFAULT_FLOCI_AZ_IMAGE,
    DEFAULT_FLOCI_GCP_IMAGE,
    DEFAULT_FLOCI_OCI_COMPARTMENT_ID,
    DEFAULT_FLOCI_OCI_IMAGE,
    DEFAULT_FLOCI_OCI_NAMESPACE,
    FLOCI_CONTAINER_PORTS,
    FLOCI_HEALTH_PATHS,
    FlociAWSService,
    FlociAzureService,
    FlociGCPService,
    FlociOCIService,
    check_floci_health,
    ensure_gcs_bucket,
    ensure_oci_bucket,
    floci_gcp_compat_proxy,
    provide_floci_container,
    provide_floci_gcp_service,
)
from pytest_databases.helpers import http_request, send_http_request
from pytest_databases.types import ServiceContainer
from tests.conftest import unwrap_fixture

if TYPE_CHECKING:
    from collections.abc import Generator

    from pytest import MonkeyPatch

    from pytest_databases.docker.floci import FlociCloud


@contextmanager
def _floci_loopback_server(handler_fn: Any) -> Generator[int, None, None]:
    """Run a loopback HTTP server dispatching requests to handler_fn under poisoned proxy env vars.

    Yields:
        Bound TCP port on 127.0.0.1.
    """

    class _Handler(BaseHTTPRequestHandler):
        def _dispatch(self, method: str) -> None:
            length = int(self.headers.get("Content-Length", "0"))
            body = self.rfile.read(length) if length > 0 else b""
            headers = {k.lower(): v for k, v in self.headers.items()}
            status, resp_headers, resp_body = handler_fn(method, self.path, headers, body)
            self.send_response(status)
            for key, value in resp_headers.items():
                self.send_header(key, value)
            if "Content-Length" not in resp_headers and "content-length" not in resp_headers:
                self.send_header("Content-Length", str(len(resp_body)))
            self.end_headers()
            if method != "HEAD":
                self.wfile.write(resp_body)

        def do_GET(self) -> None:
            self._dispatch("GET")

        def do_POST(self) -> None:
            self._dispatch("POST")

        def do_PUT(self) -> None:
            self._dispatch("PUT")

        def do_HEAD(self) -> None:
            self._dispatch("HEAD")

        def do_DELETE(self) -> None:
            self._dispatch("DELETE")

        def log_request(self, code: int | str = "-", size: int | str = "-") -> None:
            return

    saved_proxies = {
        var: os.environ.get(var)
        for var in ("HTTP_PROXY", "HTTPS_PROXY", "ALL_PROXY", "http_proxy", "https_proxy", "all_proxy")
    }
    for var in saved_proxies:
        os.environ[var] = "http://127.0.0.1:1"
    server = ThreadingHTTPServer(("127.0.0.1", 0), _Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield server.server_address[1]
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=2)
        for var, prev in saved_proxies.items():
            if prev is None:
                os.environ.pop(var, None)
            else:
                os.environ[var] = prev


FLOCI_LIVE_CASES = {
    "aws": """
    from pytest_databases.helpers import build_bucket_request, send_http_request

    def test_cloud(floci_aws_service) -> None:
        service = floci_aws_service
        assert check_floci_health(service.host, service.port, "/_floci/health")["services"]["s3"] == "running"
        bucket = f"{service.resource_prefix}bucket"
        service.ensure_bucket(bucket)
        request = build_bucket_request(
            "HEAD", service.endpoint_url, bucket, access_key=service.access_key, secret_key=service.secret_key
        )
        status, _headers, _body = send_http_request(request, timeout=5)
        assert status == 200
    """,
    "azure": """
    from pytest_databases.docker.azure_blob import azurite_container_exists, ensure_azurite_container

    def test_cloud(floci_az_service) -> None:
        service = floci_az_service
        assert check_floci_health(service.host, service.port, "/_floci/health")["status"] == "UP"
        options = {
            "account_url": service.blob_endpoint,
            "account_name": service.account_name,
            "account_key": service.account_key,
            "container_name": f"{service.resource_prefix}container",
        }
        assert ensure_azurite_container(**options)
        assert azurite_container_exists(**options)
    """,
    "gcp": """
    from pytest_databases.helpers import http_request

    def test_cloud(floci_gcp_service) -> None:
        service = floci_gcp_service
        assert check_floci_health(service.host, service.port, "/_floci-gcp/health")["services"]["gcs"] == "running"
        bucket = f"{service.resource_prefix}bucket"
        assert service.ensure_bucket(bucket)["name"] == bucket
        assert service.ensure_bucket(bucket) == {"name": bucket, "project": service.project}
        status, body = http_request(f"{service.endpoint_url}/storage/v1/b/{bucket}", timeout=5)
        assert status == 200
        assert json.loads(body.decode("utf-8"))["name"] == bucket
    """,
    "oci": """
    from pytest_databases.helpers import http_request

    def test_cloud(floci_oci_service) -> None:
        service = floci_oci_service
        assert check_floci_health(service.host, service.port, "/_floci-oci/health")["services"]["objectstorage"] == "running"
        bucket = f"{service.resource_prefix}bucket"
        created = service.ensure_bucket(bucket)
        assert created["name"] == bucket
        assert created["namespace"] == service.namespace
        assert service.ensure_bucket(bucket) == {"name": bucket, "namespace": service.namespace}
        url = f"{service.endpoint_url}/n/{service.namespace}/b/{bucket}"
        status, body = http_request(url, timeout=5)
        assert status == 200
        assert json.loads(body.decode("utf-8"))["compartmentId"] == service.compartment_id
    """,
}


def test_plugin_imports_without_cloud_sdks(pytester: pytest.Pytester) -> None:
    """Ensure the Floci module imports cleanly when cloud SDK packages are absent."""
    pytester.makepyfile("""
    import builtins
    import importlib

    def test_import() -> None:
        original_import = builtins.__import__
        blocked = {"azure", "boto3", "botocore", "google", "oci"}

        def blocked_import(name, globals=None, locals=None, fromlist=(), level=0):
            if name.partition(".")[0] in blocked:
                raise ModuleNotFoundError(name)
            return original_import(name, globals, locals, fromlist, level)

        builtins.__import__ = blocked_import
        try:
            module = importlib.import_module("pytest_databases.docker.floci")
            assert module.FlociGCPService
            assert module.FlociOCIService
            assert module.FlociAWSService
            assert module.FlociAzureService
        finally:
            builtins.__import__ = original_import
    """)

    result = pytester.runpytest_subprocess("-p", "pytest_databases", "-vv")
    result.assert_outcomes(passed=1)


def test_floci_cloud_ports_and_health_paths() -> None:
    """Each Floci image listens on its own gateway port and serves its own health path."""
    assert FLOCI_CONTAINER_PORTS == {"aws": 4566, "azure": 4577, "gcp": 4588, "oci": 4599}
    assert FLOCI_HEALTH_PATHS == {
        "aws": "/_floci/health",
        "azure": "/_floci/health",
        "gcp": "/_floci-gcp/health",
        "oci": "/_floci-oci/health",
    }


@pytest.mark.parametrize(
    ("fixture_name", "cloud", "fixture_args"),
    [
        (
            "floci_aws_service",
            "aws",
            {"floci_aws_image": "a", "floci_aws_region": "r", "floci_aws_access_key": "k", "floci_aws_secret_key": "s"},
        ),
        (
            "floci_az_service",
            "azure",
            {"floci_az_image": "a", "floci_az_account_name": "n", "floci_az_account_key": "k"},
        ),
        (
            "floci_gcp_service",
            "gcp",
            {"floci_gcp_image": "a", "floci_gcp_project": "p", "floci_gcp_compat_proxy": False},
        ),
        (
            "floci_oci_service",
            "oci",
            {
                "floci_oci_image": "a",
                "floci_oci_namespace": "n",
                "floci_oci_region": "r",
                "floci_oci_compartment_id": "c",
            },
        ),
    ],
)
def test_floci_fixtures_pass_cloud_port_and_health_path(
    monkeypatch: MonkeyPatch, fixture_name: str, cloud: FlociCloud, fixture_args: dict[str, Any]
) -> None:
    """Every service fixture starts its image on the cloud-specific port and probes the cloud-specific health path."""
    monkeypatch.delenv("PYTEST_XDIST_WORKER", raising=False)
    container_service = MagicMock()
    container_service.run.return_value.__enter__.return_value = MagicMock(host="127.0.0.1", port=40000)
    generator = unwrap_fixture(getattr(floci, fixture_name))(
        container_service=container_service,
        floci_resource_prefix="pytest-databases-",
        xdist_floci_isolation_level="database",
        **fixture_args,
    )
    service = next(generator)

    kwargs = container_service.run.call_args.kwargs
    assert kwargs["image"] == "a"
    assert kwargs["container_port"] == FLOCI_CONTAINER_PORTS[cloud]
    assert kwargs["name"] == f"floci_{fixture_name.split('_')[1]}"
    assert kwargs["transient"] is False
    assert kwargs["check"].keywords == {"health_path": FLOCI_HEALTH_PATHS[cloud]}
    assert service.endpoint_url == "http://127.0.0.1:40000"


@pytest.mark.parametrize(
    ("worker", "isolation_level", "expected_name", "expected_transient"),
    [
        (None, "server", "floci_gcp", False),
        ("gw1", "database", "floci_gcp", False),
        ("gw1", "server", "floci_gcp_1", True),
    ],
)
def test_provide_floci_container_naming_and_transient_rule(
    monkeypatch: MonkeyPatch,
    worker: str | None,
    isolation_level: str,
    expected_name: str,
    expected_transient: bool,
) -> None:
    """Containers get a ``_<worker number>`` suffix and are transient only under xdist with server isolation."""
    if worker is None:
        monkeypatch.delenv("PYTEST_XDIST_WORKER", raising=False)
    else:
        monkeypatch.setenv("PYTEST_XDIST_WORKER", worker)
    container_service = MagicMock()

    with provide_floci_container(
        container_service,
        image="floci/floci-gcp:test",
        name="floci_gcp",
        container_port=4588,
        health_path="/_floci-gcp/health",
        isolation_level=isolation_level,  # type: ignore[arg-type]
    ):
        pass

    kwargs = container_service.run.call_args.kwargs
    assert kwargs["name"] == expected_name
    assert kwargs["transient"] is expected_transient


def test_check_floci_health_uses_requested_path(monkeypatch: MonkeyPatch) -> None:
    """check_floci_health requests the given path and accepts only a JSON object."""
    visited: list[str] = []
    responses: dict[str, Any] = {
        "http://127.0.0.1:4588/_floci-gcp/health": {"services": {"storage": "running"}},
        "http://127.0.0.1:4588/_floci/health": None,
        "http://127.0.0.1:4588/list": ["not", "an", "object"],
    }

    def fake_http_get_json(url: str, *, timeout: float) -> Any:
        visited.append(url)
        return responses[url]

    monkeypatch.setattr(floci, "http_get_json", fake_http_get_json)

    assert check_floci_health("127.0.0.1", 4588, "/_floci-gcp/health") == {"services": {"storage": "running"}}
    assert check_floci_health("127.0.0.1", 4588) is None
    assert check_floci_health("127.0.0.1", 4588, "/list") is None
    assert visited == list(responses)


def test_ensure_gcs_and_oci_buckets_handle_created_and_conflict() -> None:
    """Verify ensure_gcs_bucket and ensure_oci_bucket issue stdlib HTTP POSTs and tolerate HTTP 409."""
    captured: list[tuple[str, str, dict[str, Any]]] = []
    status_to_return = 200

    def handle_req(method: str, path: str, _headers: dict[str, str], body: bytes) -> tuple[int, dict[str, str], bytes]:
        captured.append((method, path, json.loads(body.decode("utf-8"))))
        if status_to_return == 409:
            return 409, {"Content-Type": "application/json"}, b'{"error": "conflict"}'
        return status_to_return, {"Content-Type": "application/json"}, json.dumps({"name": "my-bucket"}).encode("utf-8")

    with _floci_loopback_server(handle_req) as port:
        assert ensure_gcs_bucket("127.0.0.1", port, "my-bucket", project="test-proj") == {"name": "my-bucket"}
        assert captured[-1] == ("POST", "/storage/v1/b?project=test-proj", {"name": "my-bucket"})

        assert ensure_oci_bucket("127.0.0.1", port, "floci-local", "my-bucket") == {"name": "my-bucket"}
        assert captured[-1] == (
            "POST",
            "/n/floci-local/b/",
            {"name": "my-bucket", "compartmentId": DEFAULT_FLOCI_OCI_COMPARTMENT_ID},
        )

        status_to_return = 409
        assert ensure_gcs_bucket("127.0.0.1", port, "my-bucket", project="test-proj") == {
            "name": "my-bucket",
            "project": "test-proj",
        }
        assert ensure_oci_bucket("127.0.0.1", port, "floci-local", "my-bucket") == {
            "name": "my-bucket",
            "namespace": "floci-local",
        }


def test_ensure_bucket_raises_on_other_http_errors() -> None:
    """HTTP errors other than 409 propagate."""

    def handle_req(
        _method: str, _path: str, _headers: dict[str, str], _body: bytes
    ) -> tuple[int, dict[str, str], bytes]:
        return 400, {"Content-Type": "application/json"}, b'{"error": "bad request"}'

    with _floci_loopback_server(handle_req) as port, pytest.raises(urllib.error.HTTPError) as exc_info:
        ensure_oci_bucket("127.0.0.1", port, "floci-local", "my-bucket", compartment_id="ocid1.compartment.oc1..x")
    assert exc_info.value.code == 400


def test_floci_aws_service_ensure_bucket_loopback() -> None:
    """Verify FlociAWSService.ensure_bucket issues a SigV4 PUT bucket request and treats 409 as idempotent."""
    recorded: list[tuple[str, str, dict[str, str]]] = []
    status_code = 200

    def handle_req(method: str, path: str, headers: dict[str, str], _body: bytes) -> tuple[int, dict[str, str], bytes]:
        recorded.append((method, path, headers))
        body = b"<Error><Code>BucketAlreadyOwnedByYou</Code></Error>" if status_code == 409 else b""
        return status_code, {}, body

    with _floci_loopback_server(handle_req) as port:
        service = FlociAWSService(
            host="127.0.0.1",
            port=port,
            container=MagicMock(),
            endpoint_url=f"http://127.0.0.1:{port}",
            region="us-east-1",
            access_key="ak",
            secret_key="sk",
            resource_prefix="pfx-",
        )
        service.ensure_bucket("my-bucket")
        status_code = 409
        service.ensure_bucket("my-bucket")

    assert len(recorded) == 2
    assert recorded[0][0] == "PUT"
    assert recorded[0][1] == "/my-bucket"
    assert recorded[0][2]["authorization"].startswith("AWS4-HMAC-SHA256 ")


def _make_fake_gcs_upstream(captured_upstream: list[tuple[str, str, dict[str, str], bytes]], unicode_key: str) -> Any:
    """Return a fake upstream GCS HTTP handler recording requests and serving XML/JSON payloads."""

    def handle_upstream(
        method: str, path: str, headers: dict[str, str], body: bytes
    ) -> tuple[int, dict[str, str], bytes]:
        captured_upstream.append((method, path, headers, body))
        if method == "GET" and "list-type=2" in path:
            xml_body = (
                '<?xml version="1.0" encoding="UTF-8"?>'
                "<ListBucketResult><Name>bkt</Name>"
                f"<Contents><Key>{unicode_key}</Key><Size>12</Size></Contents>"
                '<Contents><Key>already.txt</Key><ETag>"kept-etag"</ETag>'
                "<LastModified>2026-01-02T00:00:00Z</LastModified></Contents>"
                "</ListBucketResult>"
            ).encode()
            return 200, {"Content-Type": "application/xml"}, xml_body
        if method == "POST" and "/copyTo/" in path:
            return (
                200,
                {"Content-Type": "application/json"},
                json.dumps({"etag": "copied-etag", "updated": "2026-02-03T04:05:06.000Z"}).encode("utf-8"),
            )
        if method == "GET" and path == "/bkt/obj.txt":
            return 200, {"Content-Type": "text/plain", "ETag": '"obj-etag"'}, b"payload-bytes"
        return 200, {"Content-Type": "application/json"}, json.dumps({"ok": True}).encode("utf-8")

    return handle_upstream


def test_floci_gcp_compat_proxy_rewrites_xml_copy_and_head(monkeypatch: pytest.MonkeyPatch) -> None:
    """Verify the Floci GCP compatibility proxy augments XML ListObjects, rewrites copy/HEAD, and closes cleanly."""
    captured_upstream: list[tuple[str, str, dict[str, str], bytes]] = []
    unicode_key = "folder/café-obj.txt"
    expected_etag = hashlib.md5(unicode_key.encode("utf-8"), usedforsecurity=False).hexdigest()

    monkeypatch.delenv("PYTEST_XDIST_WORKER", raising=False)
    with _floci_loopback_server(_make_fake_gcs_upstream(captured_upstream, unicode_key)) as upstream_port:
        mock_docker = MagicMock()
        mock_docker.run.return_value.__enter__.return_value = ServiceContainer(
            host="127.0.0.1",
            port=upstream_port,
            container=MagicMock(),
        )
        mock_docker.run.return_value.__exit__.return_value = False

        with provide_floci_gcp_service(
            mock_docker,
            image=DEFAULT_FLOCI_GCP_IMAGE,
            project="proj",
            resource_prefix="pfx-",
            isolation_level="database",
            compat_proxy=True,
        ) as service:
            assert service.host == "127.0.0.1"
            assert service.port != upstream_port

            status_code, _, raw_body = send_http_request(f"{service.endpoint_url}/bkt?list-type=2", timeout=5)
            assert status_code == 200
            list_text = raw_body.decode("utf-8")
            assert f"<ETag>&quot;{expected_etag}&quot;</ETag>" in list_text
            assert f"<Key>{unicode_key}</Key>" in list_text
            assert list_text.count("<LastModified>") == 2
            assert '<ETag>"kept-etag"</ETag>' in list_text
            assert "<LastModified>2026-01-02T00:00:00Z</LastModified>" in list_text

            status_code, _, raw_body = send_http_request(
                f"{service.endpoint_url}/dst-bkt/dir/dest%20key.txt",
                method="PUT",
                headers={"x-goog-copy-source": "/src-bkt/dir/src%20key.txt"},
                timeout=5,
            )
            assert status_code == 200
            assert "<CopyObjectResult>" in raw_body.decode("utf-8")
            assert "<ETag>&quot;copied-etag&quot;</ETag>" in raw_body.decode("utf-8")

            status_code, head_hdrs, raw_body = send_http_request(
                f"{service.endpoint_url}/bkt/obj.txt", method="HEAD", timeout=5
            )
            assert (status_code, raw_body) == (200, b"")
            assert {k.lower(): v for k, v in head_hdrs.items()}.get("content-length") == "13"

            status_code, raw_body = http_request(
                f"{service.endpoint_url}/storage/v1/b?project=proj", method="POST", data=b"{}", timeout=5
            )
            assert status_code == 200
            assert json.loads(raw_body.decode("utf-8")) == {"ok": True}

        proxy_port = service.port

    assert any(
        method == "POST"
        and path == "/storage/v1/b/src-bkt/o/dir%2Fsrc%20key.txt/copyTo/b/dst-bkt/o/dir%2Fdest%20key.txt"
        for method, path, _, _ in captured_upstream
    )
    assert any(method == "GET" and path == "/bkt/obj.txt" for method, path, _, _ in captured_upstream)

    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as probe:
        assert probe.connect_ex(("127.0.0.1", proxy_port)) != 0


def test_provide_floci_gcp_service_compat_proxy_disabled_and_fixture_env(monkeypatch: pytest.MonkeyPatch) -> None:
    """Verify compat_proxy=False returns upstream endpoint directly and floci_gcp_compat_proxy parses env."""
    monkeypatch.delenv("PYTEST_XDIST_WORKER", raising=False)
    mock_docker = MagicMock()
    mock_docker.run.return_value.__enter__.return_value = ServiceContainer(
        host="127.0.0.1",
        port=4588,
        container=MagicMock(),
    )
    mock_docker.run.return_value.__exit__.return_value = False

    with provide_floci_gcp_service(
        mock_docker,
        image=DEFAULT_FLOCI_GCP_IMAGE,
        project="proj",
        resource_prefix="pfx-",
        isolation_level="database",
        compat_proxy=False,
    ) as service:
        assert service.endpoint_url == "http://127.0.0.1:4588"

    monkeypatch.delenv("FLOCI_GCP_COMPAT_PROXY", raising=False)
    assert unwrap_fixture(floci_gcp_compat_proxy)() is True
    monkeypatch.setenv("FLOCI_GCP_COMPAT_PROXY", "0")
    assert unwrap_fixture(floci_gcp_compat_proxy)() is False


def test_floci_service_dataclasses(monkeypatch: MonkeyPatch) -> None:
    """Verify FlociGCPService, FlociOCIService, FlociAWSService, and FlociAzureService properties."""
    gcp = FlociGCPService(
        container=MagicMock(),
        host="127.0.0.1",
        port=4588,
        endpoint_url="http://127.0.0.1:4588",
        resource_prefix="pytest-databases-",
        project="pytest-databases",
    )
    assert gcp.storage_emulator_host == "http://127.0.0.1:4588"
    assert gcp.pubsub_emulator_host == "127.0.0.1:4588"

    monkeypatch.setattr(floci, "ensure_gcs_bucket", lambda _h, _p, name, **_kw: {"name": name})
    assert gcp.ensure_bucket("events") == {"name": "events"}

    oci = FlociOCIService(
        container=MagicMock(),
        host="127.0.0.1",
        port=4599,
        endpoint_url="http://127.0.0.1:4599",
        resource_prefix="pytest-databases-",
        namespace=DEFAULT_FLOCI_OCI_NAMESPACE,
        region="us-ashburn-1",
        compartment_id=DEFAULT_FLOCI_OCI_COMPARTMENT_ID,
    )
    monkeypatch.setattr(floci, "ensure_oci_bucket", lambda _h, _p, _ns, name, **_kw: {"name": name})
    assert oci.ensure_bucket("archive") == {"name": "archive"}

    aws = FlociAWSService(
        container=MagicMock(),
        host="127.0.0.1",
        port=4566,
        endpoint_url="http://127.0.0.1:4566",
        resource_prefix="pytest-databases-",
        region="us-east-1",
        access_key="test",
        secret_key="test",
    )
    assert aws.region == "us-east-1"

    az = FlociAzureService(
        container=MagicMock(),
        host="127.0.0.1",
        port=4577,
        endpoint_url="http://127.0.0.1:4577",
        resource_prefix="pytest-databases-",
        account_name="devstoreaccount1",
        account_key="secret",
    )
    assert az.blob_endpoint == "http://127.0.0.1:4577/devstoreaccount1"


def test_floci_contract_fixtures(pytester: pytest.Pytester, monkeypatch: MonkeyPatch) -> None:
    """Verify default values of Floci image, project, namespace, and isolation fixtures."""
    for var in (
        "PYTEST_XDIST_WORKER",
        "FLOCI_GCP_IMAGE",
        "FLOCI_OCI_IMAGE",
        "FLOCI_AWS_IMAGE",
        "FLOCI_AZ_IMAGE",
        "FLOCI_GCP_PROJECT",
        "FLOCI_OCI_NAMESPACE",
        "FLOCI_OCI_COMPARTMENT_ID",
    ):
        monkeypatch.delenv(var, raising=False)

    pytester.makepyfile(f"""
    pytest_plugins = ["pytest_databases.docker.floci"]

    def test_contract(
        floci_gcp_image,
        floci_oci_image,
        floci_aws_image,
        floci_az_image,
        floci_gcp_project,
        floci_gcp_compat_proxy,
        floci_oci_namespace,
        floci_oci_compartment_id,
        floci_oci_region,
        floci_aws_region,
        floci_az_account_name,
        xdist_floci_isolation_level,
    ) -> None:
        assert floci_gcp_image == {DEFAULT_FLOCI_GCP_IMAGE!r}
        assert floci_oci_image == {DEFAULT_FLOCI_OCI_IMAGE!r}
        assert floci_aws_image == {DEFAULT_FLOCI_AWS_IMAGE!r}
        assert floci_az_image == {DEFAULT_FLOCI_AZ_IMAGE!r}
        assert floci_gcp_project == "pytest-databases"
        assert floci_gcp_compat_proxy is True
        assert floci_oci_namespace == "floci-local"
        assert floci_oci_compartment_id == {DEFAULT_FLOCI_OCI_COMPARTMENT_ID!r}
        assert floci_oci_region == "us-ashburn-1"
        assert floci_aws_region == "us-east-1"
        assert floci_az_account_name == "devstoreaccount1"
        assert xdist_floci_isolation_level == "database"
    """)

    result = pytester.runpytest_subprocess("-p", "pytest_databases", "-vv")
    result.assert_outcomes(passed=1)


def test_floci_gcp_project_is_worker_scoped(pytester: pytest.Pytester, monkeypatch: MonkeyPatch) -> None:
    """Under xdist the GCP project and resource prefix carry the worker number."""
    monkeypatch.delenv("FLOCI_GCP_PROJECT", raising=False)
    monkeypatch.delenv("FLOCI_RESOURCE_PREFIX", raising=False)
    monkeypatch.setenv("PYTEST_XDIST_WORKER", "gw3")
    pytester.makepyfile("""
    pytest_plugins = ["pytest_databases.docker.floci"]

    def test_project(floci_gcp_project, floci_resource_prefix) -> None:
        assert floci_gcp_project == "pytest-databases-3"
        assert floci_resource_prefix == "pytest-databases-3-"
    """)

    result = pytester.runpytest_subprocess("-p", "pytest_databases", "-vv")
    result.assert_outcomes(passed=1)


@pytest.mark.parametrize("cloud", sorted(FLOCI_LIVE_CASES))
def test_floci_service_live(pytester: pytest.Pytester, monkeypatch: MonkeyPatch, cloud: str) -> None:
    """Each Floci service fixture starts its image, reports healthy, and creates a storage bucket or container."""
    for variable in ("PYTEST_XDIST_WORKER", "FLOCI_RESOURCE_PREFIX", "FLOCI_OCI_NAMESPACE", "FLOCI_OCI_COMPARTMENT_ID"):
        monkeypatch.delenv(variable, raising=False)
    pytester.makepyfile(
        """
    import json

    from pytest_databases.docker.floci import check_floci_health

    pytest_plugins = ["pytest_databases.docker.floci"]
    """
        + FLOCI_LIVE_CASES[cloud]
    )

    result = pytester.runpytest_subprocess("-p", "pytest_databases", "-vv")
    result.assert_outcomes(passed=1)


def test_floci_all_fixtures_inprocess(pytester: pytest.Pytester) -> None:
    """Verify all Floci GCP, OCI, AWS, and Azure fixtures execute in-process with mocked container provider."""
    pytester.makepyfile("""
    from contextlib import contextmanager
    from unittest.mock import MagicMock, patch
    import pytest
    from pytest_databases.types import ServiceContainer

    pytest_plugins = ["pytest_databases.docker.floci"]

    @pytest.fixture(scope="session")
    def container_service() -> MagicMock:
        return MagicMock()

    def test_fixtures(request: pytest.FixtureRequest) -> None:
        mock_sc = ServiceContainer(host="127.0.0.1", port=4566, container=MagicMock())

        @contextmanager
        def fake_container(*args, **kwargs):
            yield mock_sc

        with patch("pytest_databases.docker.floci.provide_floci_container", side_effect=fake_container):
            assert request.getfixturevalue("xdist_floci_isolation_level") == "database"
            assert request.getfixturevalue("floci_resource_prefix") == "pytest-databases-"
            assert request.getfixturevalue("floci_gcp_compat_proxy") is True
            assert request.getfixturevalue("floci_gcp_service").host == "127.0.0.1"
            assert request.getfixturevalue("floci_oci_service").host == "127.0.0.1"
            assert request.getfixturevalue("floci_aws_service").host == "127.0.0.1"
            assert request.getfixturevalue("floci_az_service").host == "127.0.0.1"
    """)
    result = pytester.runpytest("-p", "no:sugar", "-p", "pytest_databases")
    result.assert_outcomes(passed=1)


def test_floci_gcp_proxy_preserves_xml_objects_strips_accept_encoding_and_handles_chunked() -> None:
    """Verify GCP proxy preserves XML object downloads, strips Accept-Encoding, and decodes chunked PUTs."""
    seen_headers: list[dict[str, str]] = []
    seen_bodies: list[bytes] = []
    stored_xml = b'<?xml version="1.0"?><ListBucketResult><Contents><Key>raw.txt</Key></Contents></ListBucketResult>'

    class _UpstreamHandler(BaseHTTPRequestHandler):
        def do_GET(self) -> None:
            seen_headers.append({k.lower(): v for k, v in self.headers.items()})
            self.send_response(200)
            self.send_header("Content-Type", "application/xml")
            self.send_header("Content-Length", str(len(stored_xml)))
            self.end_headers()
            self.wfile.write(stored_xml)

        def do_PUT(self) -> None:
            length = int(self.headers.get("Content-Length", "0"))
            seen_bodies.append(self.rfile.read(length))
            self.send_response(200)
            self.send_header("Content-Length", "0")
            self.end_headers()

        def log_request(self, code: int | str = "-", size: int | str = "-") -> None:
            _ = (code, size)

    upstream = ThreadingHTTPServer(("127.0.0.1", 0), _UpstreamHandler)
    up_thread = threading.Thread(target=upstream.serve_forever, daemon=True)
    up_thread.start()
    try:
        with floci._start_floci_gcp_compat_proxy("127.0.0.1", int(upstream.server_address[1])) as (host, port):
            status, _headers, body = send_http_request(
                f"http://{host}:{port}/my-bucket/nested/report.xml",
                headers={"Accept-Encoding": "gzip, deflate"},
            )
            assert status == 200
            assert body == stored_xml
            assert seen_headers[-1].get("accept-encoding") == "identity"

            conn = http.client.HTTPConnection(host, port, timeout=5.0)
            try:
                conn.putrequest("PUT", "/my-bucket/chunked.bin")
                conn.putheader("Transfer-Encoding", "chunked")
                conn.endheaders()
                conn.send(b"4\r\ndata\r\n0\r\n\r\n")
                resp = conn.getresponse()
                resp.read()
                assert resp.status == 200
            finally:
                conn.close()
            assert seen_bodies == [b"data"]
    finally:
        upstream.shutdown()
        upstream.server_close()
        up_thread.join(timeout=5.0)
