"""Tests for LocalStack AWS emulator fixtures and in-container CLI helpers."""

from __future__ import annotations

import email.message
import http.server
import io
import socket
import threading
import urllib.error
from typing import TYPE_CHECKING, Any
from unittest.mock import MagicMock

import pytest

from pytest_databases import helpers
from pytest_databases.docker import localstack
from pytest_databases.docker.localstack import LocalStackService
from pytest_databases.types import ServiceContainer
from tests.conftest import unwrap_fixture

if TYPE_CHECKING:
    from collections.abc import Generator
    from pathlib import Path


_PROBE_RESPONSES: dict[str, tuple[int, bytes]] = {
    "/_ministack/health": (200, b'{"services": {"sqs": "running"}}'),
    "/text": (200, b"ok"),
    "/missing": (404, b'{"error": "not found"}'),
    "/created": (201, b"{}"),
}


class _ProbeHandler(http.server.BaseHTTPRequestHandler):
    """Serve fixed responses for the HTTP probe tests."""

    def do_GET(self) -> None:
        """Answer with the configured status and body for the request path."""
        status, body = _PROBE_RESPONSES.get(self.path, (404, b""))
        self.send_response(status)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)


@pytest.fixture(scope="module")
def probe_server() -> Generator[tuple[str, int], None, None]:
    """Run a local HTTP server that answers like an emulator gateway.

    Yields:
        The server host and port.
    """
    server = http.server.ThreadingHTTPServer(("127.0.0.1", 0), _ProbeHandler)
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


def test_plugin_imports_without_aws_clients(pytester: pytest.Pytester) -> None:
    """Ensure the LocalStack module imports cleanly when AWS client packages are absent."""
    pytester.makepyfile("""
    import builtins
    import importlib

    def test_import() -> None:
        original_import = builtins.__import__
        blocked = {"awscli", "boto3", "botocore", "localstack_client"}

        def blocked_import(name, globals=None, locals=None, fromlist=(), level=0):
            if name.partition(".")[0] in blocked:
                raise ModuleNotFoundError(name)
            return original_import(name, globals, locals, fromlist, level)

        builtins.__import__ = blocked_import
        try:
            module = importlib.import_module("pytest_databases.docker.localstack")
            assert module.LocalStackService
        finally:
            builtins.__import__ = original_import
    """)

    result = pytester.runpytest_subprocess("-p", "pytest_databases", "-vv")
    result.assert_outcomes(passed=1)


@pytest.mark.parametrize(
    ("path", "expected_ok", "expected_json"),
    [
        ("/_ministack/health", True, {"services": {"sqs": "running"}}),
        ("/text", True, None),
        ("/missing", False, None),
        ("/created", False, None),
    ],
)
def test_http_probes_against_live_server(
    probe_server: tuple[str, int], path: str, expected_ok: bool, expected_json: dict[str, Any] | None
) -> None:
    """Verify only a 200 answer counts as ready and only a JSON 200 body is decoded."""
    host, port = probe_server
    url = f"http://{host}:{port}{path}"
    assert helpers.http_get_ok(url, timeout=2.0) is expected_ok
    assert helpers.http_get_json(url, timeout=2.0) == expected_json


def test_http_probes_report_connection_failure(closed_port: int) -> None:
    """Verify a refused connection is reported as not ready instead of raising."""
    url = f"http://127.0.0.1:{closed_port}/health"
    assert helpers.http_get_ok(url, timeout=1.0) is False
    assert helpers.http_get_json(url, timeout=1.0) is None


def test_http_error_response_is_closed(monkeypatch: pytest.MonkeyPatch) -> None:
    """Verify the body of an HTTP error response is closed so polling does not leak sockets."""
    body = io.BytesIO(b"unavailable")
    error = urllib.error.HTTPError("http://emulator/health", 503, "Service Unavailable", email.message.Message(), body)

    def raise_error(*_args: object, **_kwargs: object) -> object:
        raise error

    monkeypatch.setattr(helpers._DIRECT_OPENER, "open", raise_error)
    assert helpers.http_get_ok("http://emulator/health") is False
    assert body.closed


@pytest.mark.parametrize("url", ["file:///etc/passwd", "ftp://example.test/file"])
def test_http_probes_reject_non_http_urls(url: str) -> None:
    """Verify non-HTTP schemes are rejected before any request is made."""
    with pytest.raises(ValueError, match="Only http:// and https:// URLs"):
        helpers.http_get_ok(url)


def test_gateway_health_probe(probe_server: tuple[str, int], closed_port: int) -> None:
    """Verify the gateway is ready when one of the emulator health paths answers 200."""
    host, port = probe_server
    assert localstack._health_is_ready(host, port) is True
    assert localstack._health_is_ready("127.0.0.1", closed_port, timeout=1.0) is False


def test_exec_aws_cli_reports_failures() -> None:
    """Verify missing CLI binaries and failing commands raise with context."""
    container = MagicMock()
    container.exec_run.return_value = MagicMock(exit_code=127, output=b"")
    with pytest.raises(RuntimeError, match="must provide the awslocal or aws CLI"):
        localstack._exec_aws_cli(container, ("sqs", "list-queues"))

    container.exec_run.return_value = MagicMock(exit_code=0, output=b'{"QueueUrls": []}')
    service = LocalStackService(
        container=container,
        host="127.0.0.1",
        port=4566,
        endpoint_url="http://127.0.0.1:4566",
        region="us-east-1",
        access_key="test",
        secret_key="test",
        services=None,
        resource_prefix="pytest-databases-",
    )
    assert service.exec_aws_cli("sqs", "list-queues") == '{"QueueUrls": []}'
    assert container.exec_run.call_args.args[0][-2:] == ["sqs", "list-queues"]

    container.exec_run.return_value = MagicMock(exit_code=2, output=b"boom")
    with pytest.raises(RuntimeError, match="LocalStack AWS CLI command failed"):
        service.exec_aws_cli("sqs", "list-queues")


def test_one_public_fixture_set() -> None:
    """Verify the module exposes one fixture set, with MiniStack as the default image."""
    assert not [name for name in localstack.__all__ if "ministack" in name.lower()]
    assert not hasattr(localstack, "MiniStackService")
    assert unwrap_fixture(localstack.localstack_image)() == "ministackorg/ministack:latest"


def test_sqs_lifecycle_uses_the_container_cli(pytester: pytest.Pytester) -> None:
    """Verify SQS create, send, receive, and delete operations via exec_aws_cli."""
    pytester.makepyfile("""
    import json

    from pytest_databases.docker.localstack import LocalStackService

    pytest_plugins = ["pytest_databases.docker.localstack"]

    def test(localstack_service: LocalStackService) -> None:
        assert localstack_service.endpoint_url == f"http://{localstack_service.host}:{localstack_service.port}"
        assert localstack_service.region == "us-east-1"
        assert localstack_service.access_key == "test"
        assert localstack_service.secret_key == "test"
        assert localstack_service.services is None
        assert localstack_service.resource_prefix.startswith("pytest-databases-")

        queue_name = f"{localstack_service.resource_prefix}sqs-lifecycle"
        created = json.loads(localstack_service.exec_aws_cli(
            "sqs", "create-queue", "--queue-name", queue_name, "--output", "json"
        ))
        queue_url = created["QueueUrl"]
        sent = json.loads(localstack_service.exec_aws_cli(
            "sqs", "send-message", "--queue-url", queue_url,
            "--message-body", "clientless", "--output", "json"
        ))
        assert sent["MessageId"]

        received = json.loads(localstack_service.exec_aws_cli(
            "sqs", "receive-message", "--queue-url", queue_url,
            "--wait-time-seconds", "1", "--max-number-of-messages", "1", "--output", "json"
        ))
        message = received["Messages"][0]
        assert message["Body"] == "clientless"
        localstack_service.exec_aws_cli(
            "sqs", "delete-message", "--queue-url", queue_url,
            "--receipt-handle", message["ReceiptHandle"]
        )
        localstack_service.exec_aws_cli("sqs", "delete-queue", "--queue-url", queue_url)
    """)

    result = pytester.runpytest_subprocess("-p", "pytest_databases", "-vv")
    result.assert_outcomes(passed=1)


def test_fixture_overrides_are_visible(pytester: pytest.Pytester) -> None:
    """Verify session fixture overrides propagate to LocalStackService and container env."""
    pytester.makepyfile("""
    import pytest

    pytest_plugins = ["pytest_databases.docker.localstack"]

    @pytest.fixture(scope="session")
    def localstack_region():
        return "eu-west-1"

    @pytest.fixture(scope="session")
    def localstack_access_key():
        return "override-access"

    @pytest.fixture(scope="session")
    def localstack_secret_key():
        return "override-secret"

    @pytest.fixture(scope="session")
    def localstack_services():
        return ("s3",)

    @pytest.fixture(scope="session")
    def localstack_resource_prefix():
        return "custom-prefix-"

    def test(localstack_service) -> None:
        assert localstack_service.region == "eu-west-1"
        assert localstack_service.access_key == "override-access"
        assert localstack_service.secret_key == "override-secret"
        assert localstack_service.services == ("s3",)
        assert localstack_service.resource_prefix == "custom-prefix-"
        environment = localstack_service.container.attrs["Config"]["Env"]
        assert "SERVICES=s3" in environment
    """)

    result = pytester.runpytest_subprocess("-p", "pytest_databases", "-vv")
    result.assert_outcomes(passed=1)


def test_xdist_database_isolation(
    pytester: pytest.Pytester,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    """Verify database xdist isolation shares a container with distinct worker prefixes."""
    monkeypatch.setenv("LOCALSTACK_TEST_STATE", str(tmp_path))
    pytester.makepyfile("""
    import os
    from pathlib import Path

    pytest_plugins = ["pytest_databases.docker.localstack"]

    def record(localstack_service) -> None:
        worker = os.environ["PYTEST_XDIST_WORKER"]
        value = f"{localstack_service.container.id}|{localstack_service.resource_prefix}"
        Path(os.environ["LOCALSTACK_TEST_STATE"], f"{worker}.txt").write_text(value, encoding="utf-8")

    def test_one(localstack_service) -> None:
        record(localstack_service)

    def test_two(localstack_service) -> None:
        record(localstack_service)
    """)

    result = pytester.runpytest_subprocess("-p", "pytest_databases", "-n", "2", "-vv")
    result.assert_outcomes(passed=2)
    records = [path.read_text(encoding="utf-8").split("|") for path in sorted(tmp_path.glob("gw*.txt"))]
    assert len(records) == 2
    assert len({container_id for container_id, _ in records}) == 1
    assert len({prefix for _, prefix in records}) == 2


def test_xdist_server_isolation(
    pytester: pytest.Pytester,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    """Verify server xdist isolation launches separate containers per worker."""
    monkeypatch.setenv("LOCALSTACK_TEST_STATE", str(tmp_path))
    pytester.makepyfile("""
    import os
    from pathlib import Path

    import pytest

    pytest_plugins = ["pytest_databases.docker.localstack"]

    @pytest.fixture(scope="session")
    def xdist_localstack_isolation_level():
        return "server"

    def record(localstack_service) -> None:
        worker = os.environ["PYTEST_XDIST_WORKER"]
        Path(os.environ["LOCALSTACK_TEST_STATE"], f"{worker}.txt").write_text(
            localstack_service.container.id, encoding="utf-8"
        )

    def test_one(localstack_service) -> None:
        record(localstack_service)

    def test_two(localstack_service) -> None:
        record(localstack_service)
    """)

    result = pytester.runpytest_subprocess("-p", "pytest_databases", "-n", "2", "-vv")
    result.assert_outcomes(passed=2)
    container_ids = {path.read_text(encoding="utf-8") for path in tmp_path.glob("gw*.txt")}
    assert len(container_ids) == 2


@pytest.mark.parametrize(
    ("worker_num", "isolation_level", "services", "auth_token", "expected_name"),
    [
        (None, "database", None, None, "localstack"),
        (1, "database", ("s3",), "tok-123", "localstack"),
        (2, "server", ("sqs",), None, "localstack_2"),
    ],
)
def test_provide_localstack_service_and_cli_errors(
    monkeypatch: pytest.MonkeyPatch,
    worker_num: int | None,
    isolation_level: str,
    services: tuple[str, ...] | None,
    auth_token: str | None,
    expected_name: str,
) -> None:
    """Verify provide_localstack_service xdist modes, service filtering, auth token, and CLI errors."""
    monkeypatch.setattr(localstack, "get_xdist_worker_num", lambda: worker_num)
    monkeypatch.setattr(localstack, "_health_is_ready", lambda *_a, **_kw: True)
    mock_docker = MagicMock()
    mock_container = MagicMock()
    mock_container.exec_run.return_value = MagicMock(exit_code=0, output=b"{}")
    svc_container = ServiceContainer(host="127.0.0.1", port=4566, container=mock_container)
    mock_docker.run.return_value.__enter__.return_value = svc_container

    with localstack.provide_localstack_service(
        container_service=mock_docker,
        localstack_image="nahuelnucera/ministack:latest",
        localstack_region="us-east-1",
        localstack_access_key="test",
        localstack_secret_key="test",
        localstack_auth_token=auth_token,
        localstack_services=services,
        localstack_resource_prefix="pfx-",
        xdist_localstack_isolation_level=isolation_level,  # type: ignore[arg-type]
    ) as svc:
        assert svc.endpoint_url == "http://127.0.0.1:4566"

    check = mock_docker.run.call_args.kwargs["check"]
    assert mock_docker.run.call_args.kwargs["name"] == expected_name
    assert check(svc_container) is True
    monkeypatch.setattr(localstack, "_health_is_ready", lambda *_a, **_kw: False)
    assert check(svc_container) is False

    mock_container.exec_run.return_value = MagicMock(exit_code=None, output=b"")
    with pytest.raises(RuntimeError, match="did not return an exit code"):
        localstack._exec_aws_cli(mock_container, ("sqs", "list-queues"))

    mock_container.exec_run.return_value = MagicMock(exit_code=127, output=b"not found")
    with pytest.raises(RuntimeError, match="must provide the awslocal or aws CLI"):
        localstack._exec_aws_cli(mock_container, ("sqs", "list-queues"))


def test_localstack_all_fixtures_inprocess(pytester: pytest.Pytester, monkeypatch: pytest.MonkeyPatch) -> None:
    """Exercise all LocalStack session fixtures in-process with a mocked provide_localstack_service."""
    monkeypatch.setenv("LOCALSTACK_SERVICES", "s3, sqs")
    pytester.makepyfile("""
    from contextlib import contextmanager
    from unittest.mock import MagicMock, patch
    import pytest
    from pytest_databases.docker import localstack as ls_mod
    from pytest_databases.docker.localstack import LocalStackService

    pytest_plugins = ["pytest_databases.docker.localstack"]

    @pytest.fixture(scope="session")
    def container_service():
        return MagicMock()

    @contextmanager
    def _fake_provide(**kwargs):
        yield LocalStackService(
            host="127.0.0.1",
            port=4566,
            container=MagicMock(),
            endpoint_url="http://127.0.0.1:4566",
            region=kwargs["localstack_region"],
            access_key=kwargs["localstack_access_key"],
            secret_key=kwargs["localstack_secret_key"],
            services=kwargs["localstack_services"],
            resource_prefix=kwargs["localstack_resource_prefix"],
        )

    def test_all(request, monkeypatch):
        with patch.object(ls_mod, "provide_localstack_service", _fake_provide):
            for name in ls_mod.__all__:
                if name in {"LocalStackService", "provide_localstack_service"}:
                    continue
                val = request.getfixturevalue(name)
                if name != "localstack_auth_token":
                    assert val is not None
        monkeypatch.setenv("PYTEST_XDIST_WORKER", "gw3")
        monkeypatch.delenv("LOCALSTACK_RESOURCE_PREFIX", raising=False)
        assert ls_mod.localstack_resource_prefix.__wrapped__() == "pytest-databases-3-"
        monkeypatch.setenv("LOCALSTACK_RESOURCE_PREFIX", "custom-")
        assert ls_mod.localstack_resource_prefix.__wrapped__() == "custom-"
        monkeypatch.delenv("LOCALSTACK_SERVICES", raising=False)
        assert ls_mod.localstack_services.__wrapped__() is None
    """)
    result = pytester.runpytest("-p", "no:sugar", "-p", "pytest_databases")
    result.assert_outcomes(passed=1)
