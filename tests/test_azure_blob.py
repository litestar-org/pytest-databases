"""Tests for Azure Blob Storage (Azurite) container service fixtures."""

from __future__ import annotations

import asyncio
import http.server
import socket
import threading
from contextlib import contextmanager
from types import SimpleNamespace
from typing import Any
from unittest.mock import AsyncMock, MagicMock

import pytest

from pytest_databases.docker import azure_blob as azure_blob_mod
from pytest_databases.docker.azure_blob import (
    AZURE_API_VERSION,
    DEFAULT_ACCOUNT_KEY,
    DEFAULT_ACCOUNT_NAME,
    AzureBlobService,
    azurite_container_exists,
    build_shared_key_authorization,
    ensure_azurite_container,
    provide_azure_blob_async_container_client,
    provide_azure_blob_container_client,
    provide_azure_blob_service,
)
from pytest_databases.types import ServiceContainer


def test_plugin_imports_without_azure_storage_blob(pytester: pytest.Pytester) -> None:
    """Verify ``pytest_databases.docker.azure_blob`` imports cleanly when ``azure.storage.blob`` is absent."""
    pytester.makepyfile("""
    import builtins

    def test_import() -> None:
        original_import = builtins.__import__

        def blocked_import(name, globals=None, locals=None, fromlist=(), level=0):
            if name == "azure.storage.blob" or name.startswith("azure.storage.blob."):
                raise ModuleNotFoundError(name)
            return original_import(name, globals, locals, fromlist, level)

        builtins.__import__ = blocked_import
        try:
            import pytest_databases.docker.azure_blob
        finally:
            builtins.__import__ = original_import
    """)

    result = pytester.runpytest_subprocess("-p", "pytest_databases", "-vv")
    result.assert_outcomes(passed=1)


def test_build_shared_key_authorization() -> None:
    """Verify deterministic SharedKey HMAC-SHA256 header generation for Azurite requests."""
    header = build_shared_key_authorization(
        method="PUT",
        account_name=DEFAULT_ACCOUNT_NAME,
        account_key=DEFAULT_ACCOUNT_KEY,
        container_name="pytest-databases",
        ms_date="Wed, 21 Oct 2026 12:00:00 GMT",
    )
    assert header.startswith(f"SharedKey {DEFAULT_ACCOUNT_NAME}:")
    signature = header.split(":", 1)[1]
    assert len(signature) > 20


def _start_azurite_loopback(
    responses: list[tuple[int, dict[str, str], bytes]],
) -> tuple[http.server.ThreadingHTTPServer, list[tuple[str, str, dict[str, str]]]]:
    recorded: list[tuple[str, str, dict[str, str]]] = []
    remaining = list(responses)

    class _Handler(http.server.BaseHTTPRequestHandler):
        def _handle(self) -> None:
            length = int(self.headers.get("Content-Length", "0"))
            if length:
                self.rfile.read(length)
            recorded.append((self.command, self.path, dict(self.headers.items())))
            status, headers, body = remaining.pop(0) if remaining else (200, {}, b"")
            self.send_response(status)
            for key, value in headers.items():
                self.send_header(key, value)
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
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    return server, recorded


def test_ensure_and_exists_azurite_container_unit(monkeypatch: pytest.MonkeyPatch) -> None:
    """Verify ``ensure_azurite_container`` and ``azurite_container_exists`` handle status codes and proxy bypass."""
    monkeypatch.setenv("HTTP_PROXY", "http://127.0.0.1:1")
    monkeypatch.setenv("HTTPS_PROXY", "http://127.0.0.1:1")
    server, recorded = _start_azurite_loopback([
        (201, {}, b""),
        (200, {}, b""),
        (404, {}, b""),
    ])
    account_url = f"http://127.0.0.1:{server.server_address[1]}/{DEFAULT_ACCOUNT_NAME}"
    try:
        assert ensure_azurite_container(
            account_url=account_url,
            account_name=DEFAULT_ACCOUNT_NAME,
            account_key=DEFAULT_ACCOUNT_KEY,
            container_name="pytest-databases",
        )
        assert azurite_container_exists(
            account_url=account_url,
            account_name=DEFAULT_ACCOUNT_NAME,
            account_key=DEFAULT_ACCOUNT_KEY,
            container_name="pytest-databases",
        )
        assert not azurite_container_exists(
            account_url=account_url,
            account_name=DEFAULT_ACCOUNT_NAME,
            account_key=DEFAULT_ACCOUNT_KEY,
            container_name="pytest-databases",
        )
    finally:
        server.shutdown()
        server.server_close()

    method, path, wire_headers = recorded[0]
    lower_headers = {k.lower(): v for k, v in wire_headers.items()}
    assert (method, path) == ("PUT", f"/{DEFAULT_ACCOUNT_NAME}/pytest-databases?restype=container")
    assert lower_headers.get("content-length") == "0"
    assert "content-type" not in lower_headers
    assert lower_headers.get("x-ms-version") == AZURE_API_VERSION
    assert str(lower_headers.get("authorization")).startswith(f"SharedKey {DEFAULT_ACCOUNT_NAME}:")


@pytest.mark.parametrize(
    ("resp_headers", "expected"),
    [
        ({"X-Ms-Error-Code": "ContainerAlreadyExists"}, True),
        ({"x-ms-error-code": "ContainerAlreadyExists"}, True),
        ({"x-ms-error-code": "ContainerBeingDeleted"}, False),
        ({}, False),
    ],
)
def test_ensure_azurite_container_409_error_code_matrix(
    monkeypatch: pytest.MonkeyPatch,
    resp_headers: dict[str, str],
    expected: bool,
) -> None:
    """Verify HTTP 409 succeeds only when case-insensitive x-ms-error-code is ContainerAlreadyExists."""
    monkeypatch.setenv("HTTP_PROXY", "http://127.0.0.1:1")
    server, _recorded = _start_azurite_loopback([(409, resp_headers, b"<Error/>")])
    account_url = f"http://127.0.0.1:{server.server_address[1]}/{DEFAULT_ACCOUNT_NAME}"
    try:
        assert (
            ensure_azurite_container(
                account_url=account_url,
                account_name=DEFAULT_ACCOUNT_NAME,
                account_key=DEFAULT_ACCOUNT_KEY,
                container_name="c1",
            )
            is expected
        )
    finally:
        server.shutdown()
        server.server_close()


def test_ensure_azurite_container_network_error(monkeypatch: pytest.MonkeyPatch) -> None:
    """Verify unreachable loopback ports return ``False`` during readiness checks."""
    monkeypatch.setenv("HTTP_PROXY", "http://127.0.0.1:1")
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.bind(("127.0.0.1", 0))
        closed_port = int(sock.getsockname()[1])
    account_url = f"http://127.0.0.1:{closed_port}/{DEFAULT_ACCOUNT_NAME}"
    assert not ensure_azurite_container(
        account_url=account_url,
        account_name=DEFAULT_ACCOUNT_NAME,
        account_key=DEFAULT_ACCOUNT_KEY,
        container_name="pytest-databases",
        timeout=1.0,
    )
    assert not azurite_container_exists(
        account_url=account_url,
        account_name=DEFAULT_ACCOUNT_NAME,
        account_key=DEFAULT_ACCOUNT_KEY,
        container_name="pytest-databases",
        timeout=1.0,
    )


def test_deprecated_azure_blob_container_client_warns(monkeypatch: pytest.MonkeyPatch) -> None:
    """Verify ``provide_azure_blob_container_client`` emits ``DeprecationWarning`` and lazily imports."""
    fake_client = MagicMock()
    fake_ctx = MagicMock()
    fake_ctx.__enter__.return_value = fake_client
    fake_ctx.__exit__.return_value = False
    fake_cls = SimpleNamespace(from_connection_string=MagicMock(return_value=fake_ctx))
    fake_mod = SimpleNamespace(ContainerClient=fake_cls)

    monkeypatch.setattr(azure_blob_mod.importlib, "import_module", lambda _name: fake_mod)

    service = AzureBlobService(
        host="127.0.0.1",
        port=10000,
        container=MagicMock(),
        connection_string="DefaultEndpointsProtocol=http;AccountName=devstoreaccount1;",
        account_url="http://127.0.0.1:10000/devstoreaccount1",
        account_key=DEFAULT_ACCOUNT_KEY,
        account_name=DEFAULT_ACCOUNT_NAME,
    )

    with (
        pytest.warns(DeprecationWarning, match=r"azure_blob_container_client.*v1\.0\.0") as record,
        provide_azure_blob_container_client(service, "pytest-databases") as client,
    ):
        assert client is fake_client

    assert len(record) == 1
    assert record[0].filename == __file__
    fake_cls.from_connection_string.assert_called_once_with(
        service.connection_string,
        container_name="pytest-databases",
    )


def test_deprecated_azure_blob_async_container_client_warns(monkeypatch: pytest.MonkeyPatch) -> None:
    """Verify ``provide_azure_blob_async_container_client`` warns once at the caller and lazily imports."""
    fake_client = MagicMock()
    fake_ctx = MagicMock()
    fake_ctx.__aenter__ = AsyncMock(return_value=fake_client)
    fake_ctx.__aexit__ = AsyncMock(return_value=False)
    fake_cls = SimpleNamespace(from_connection_string=MagicMock(return_value=fake_ctx))
    fake_mod = SimpleNamespace(ContainerClient=fake_cls)

    monkeypatch.setattr(azure_blob_mod.importlib, "import_module", lambda _name: fake_mod)

    service = AzureBlobService(
        host="127.0.0.1",
        port=10000,
        container=MagicMock(),
        connection_string="DefaultEndpointsProtocol=http;AccountName=devstoreaccount1;",
        account_url="http://127.0.0.1:10000/devstoreaccount1",
        account_key=DEFAULT_ACCOUNT_KEY,
        account_name=DEFAULT_ACCOUNT_NAME,
    )

    async def open_client() -> object:
        async with provide_azure_blob_async_container_client(service, "pytest-databases") as client:
            return client

    with pytest.warns(DeprecationWarning, match=r"azure_blob_async_container_client.*v1\.0\.0") as record:
        assert asyncio.run(open_client()) is fake_client

    assert len(record) == 1
    assert record[0].filename == __file__


def test_default_no_xdist(pytester: pytest.Pytester) -> None:
    """Verify default Azurite container initialization without sidecar containers."""
    pytester.makepyfile("""
from pytest_databases.docker.azure_blob import AzureBlobService, azurite_container_exists

pytest_plugins = [
    "pytest_databases.docker.azure_blob",
]


def test_one(
    azure_blob_service: AzureBlobService,
    azure_blob_default_container_name: str,
) -> None:
    assert azurite_container_exists(
        account_url=azure_blob_service.account_url,
        account_name=azure_blob_service.account_name,
        account_key=azure_blob_service.account_key,
        container_name=azure_blob_default_container_name,
    )


def test_two(
    azure_blob_service: AzureBlobService,
    azure_blob_default_container_name: str,
) -> None:
    assert azurite_container_exists(
        account_url=azure_blob_service.account_url,
        account_name=azure_blob_service.account_name,
        account_key=azure_blob_service.account_key,
        container_name=azure_blob_default_container_name,
    )
""")
    result = pytester.runpytest_subprocess("-p", "pytest_databases")
    result.assert_outcomes(passed=2)


def test_xdist_isolate_server(pytester: pytest.Pytester) -> None:
    """Verify ``server`` isolation starts separate Azurite containers per worker."""
    pytester.makepyfile("""
import pytest
from pytest_databases.docker.azure_blob import AzureBlobService, azurite_container_exists

pytest_plugins = [
    "pytest_databases.docker.azure_blob",
]


@pytest.fixture(scope="session")
def azure_blob_xdist_isolation_level():
    return "server"


def test_one(
    azure_blob_service: AzureBlobService,
    azure_blob_default_container_name: str,
) -> None:
    assert azurite_container_exists(
        account_url=azure_blob_service.account_url,
        account_name=azure_blob_service.account_name,
        account_key=azure_blob_service.account_key,
        container_name=azure_blob_default_container_name,
    )


def test_two(
    azure_blob_service: AzureBlobService,
    azure_blob_default_container_name: str,
) -> None:
    assert azurite_container_exists(
        account_url=azure_blob_service.account_url,
        account_name=azure_blob_service.account_name,
        account_key=azure_blob_service.account_key,
        container_name=azure_blob_default_container_name,
    )
""")
    result = pytester.runpytest_subprocess("-p", "pytest_databases", "-n", "2")
    result.assert_outcomes(passed=2)


def test_xdist_isolate_database(pytester: pytest.Pytester) -> None:
    """Verify ``database`` isolation creates per-worker Azurite accounts and default containers."""
    pytester.makepyfile("""
from pytest_databases.docker.azure_blob import AzureBlobService, azurite_container_exists
from pytest_databases.helpers import get_xdist_worker_num

pytest_plugins = [
    "pytest_databases.docker.azure_blob",
]


def test_one(
    azure_blob_service: AzureBlobService,
    azure_blob_default_container_name: str,
) -> None:
    assert azurite_container_exists(
        account_url=azure_blob_service.account_url,
        account_name=azure_blob_service.account_name,
        account_key=azure_blob_service.account_key,
        container_name=azure_blob_default_container_name,
    )
    assert azure_blob_service.account_name == f"test_account_{get_xdist_worker_num()}"


def test_two(
    azure_blob_service: AzureBlobService,
    azure_blob_default_container_name: str,
) -> None:
    assert azurite_container_exists(
        account_url=azure_blob_service.account_url,
        account_name=azure_blob_service.account_name,
        account_key=azure_blob_service.account_key,
        container_name=azure_blob_default_container_name,
    )
    assert azure_blob_service.account_name == f"test_account_{get_xdist_worker_num()}"
""")
    result = pytester.runpytest_subprocess("-p", "pytest_databases", "-n", "2")
    result.assert_outcomes(passed=2)


@pytest.mark.parametrize(
    ("isolation_level", "worker_num", "expected_account", "expected_name"),
    [
        ("database", None, DEFAULT_ACCOUNT_NAME, "azurite-blob"),
        ("database", 1, "test_account_1", "azurite-blob"),
        ("server", 1, DEFAULT_ACCOUNT_NAME, "azurite-blob_1"),
    ],
)
def test_provide_azure_blob_service_xdist_and_readiness(
    monkeypatch: pytest.MonkeyPatch,
    isolation_level: str,
    worker_num: int | None,
    expected_account: str,
    expected_name: str,
) -> None:
    """Verify provide_azure_blob_service readiness checks and xdist container naming."""
    monkeypatch.setattr("pytest_databases.docker.azure_blob.get_xdist_worker_num", lambda: worker_num)
    monkeypatch.setattr("pytest_databases.docker.azure_blob.get_xdist_worker_count", lambda: 2)
    ensured_containers: list[str] = []

    def fake_ensure_container(**kwargs: Any) -> bool:
        ensured_containers.append(kwargs["container_name"])
        return True

    monkeypatch.setattr("pytest_databases.docker.azure_blob.ensure_azurite_container", fake_ensure_container)
    docker_service = MagicMock()
    captured_name: list[str] = []

    def fake_run(image: str, **kwargs: Any) -> Any:
        @contextmanager
        def _ctx() -> Any:
            captured_name.append(kwargs["name"])
            svc = ServiceContainer(host="127.0.0.1", port=10000, container=MagicMock())
            assert kwargs["check"](svc) is True
            yield svc

        return _ctx()

    docker_service.run.side_effect = fake_run

    with provide_azure_blob_service(
        docker_service,
        azurite_in_memory=True,
        azure_blob_xdist_isolation_level=isolation_level,  # type: ignore[arg-type]
        azure_blob_default_container_name="pytest-databases",
    ) as service:
        assert service.account_name == expected_account
        assert captured_name == [expected_name]
        assert "pytest-databases" in ensured_containers


def test_azure_blob_all_fixtures_inprocess(pytester: pytest.Pytester) -> None:
    """Verify Azure Blob fixtures execute in-process with mocked docker_service and SDK."""
    pytester.makepyfile("""
    import asyncio
    from contextlib import contextmanager
    import sys
    from unittest.mock import AsyncMock, MagicMock
    import pytest
    import pytest_databases.docker.azure_blob as ab_mod
    from pytest_databases.types import ServiceContainer

    pytest_plugins = ["pytest_databases.docker.azure_blob"]

    @pytest.fixture(autouse=True, scope="session")
    def mock_ensure():
        orig = ab_mod.ensure_azurite_container
        ab_mod.ensure_azurite_container = lambda **kw: True
        fake_sync = MagicMock()
        fake_async = MagicMock()
        fake_client = AsyncMock()
        fake_async.ContainerClient.from_connection_string.return_value = fake_client
        sys.modules["azure"] = MagicMock()
        sys.modules["azure.storage"] = MagicMock()
        sys.modules["azure.storage.blob"] = fake_sync
        sys.modules["azure.storage.blob.aio"] = fake_async
        yield
        ab_mod.ensure_azurite_container = orig

    @pytest.fixture(scope="session")
    def docker_service():
        mock_ds = MagicMock()
        @contextmanager
        def _run(image, **kwargs):
            yield ServiceContainer(host="127.0.0.1", port=10000, container=MagicMock())
        mock_ds.run.side_effect = _run
        return mock_ds

    def test_fixtures(
        azurite_in_memory,
        azure_blob_xdist_isolation_level,
        azure_blob_default_container_name,
        azure_blob_service,
        azure_blob_container_client,
    ):
        assert azurite_in_memory is True
        assert azure_blob_xdist_isolation_level == "database"
        assert azure_blob_default_container_name == "pytest-databases"
        assert azure_blob_service.port == 10000
        assert azure_blob_container_client is not None

        async def _run_async_fixture() -> None:
            agen = ab_mod.azure_blob_async_container_client.__wrapped__(
                azure_blob_service,
                azure_blob_default_container_name,
            )
            client = await agen.__anext__()
            assert client is not None
            try:
                await agen.__anext__()
            except StopAsyncIteration:
                pass

        asyncio.run(_run_async_fixture())
    """)
    result = pytester.runpytest("-p", "no:sugar", "-p", "pytest_databases", "-W", "ignore::DeprecationWarning")
    result.assert_outcomes(passed=1)
