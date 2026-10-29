"""Tests for Azure Blob Storage (Azurite) container service fixtures."""

from __future__ import annotations

import urllib.error
from types import SimpleNamespace
from typing import Any
from unittest.mock import MagicMock

import pytest

from pytest_databases.docker import azure_blob as azure_blob_mod
from pytest_databases.docker.azure_blob import (
    DEFAULT_ACCOUNT_KEY,
    DEFAULT_ACCOUNT_NAME,
    AzureBlobService,
    azurite_container_exists,
    build_shared_key_authorization,
    ensure_azurite_container,
    provide_azure_blob_container_client,
)


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


def test_ensure_and_exists_azurite_container_unit(monkeypatch: pytest.MonkeyPatch) -> None:
    """Verify ``ensure_azurite_container`` and ``azurite_container_exists`` handle HTTP status codes."""
    resp_201 = MagicMock()
    resp_201.__enter__.return_value = SimpleNamespace(status=201)
    resp_201.__exit__.return_value = False
    resp_200 = MagicMock()
    resp_200.__enter__.return_value = SimpleNamespace(status=200)
    resp_200.__exit__.return_value = False
    responses: list[Any] = [
        resp_201,
        urllib.error.HTTPError(
            url="http://127.0.0.1:10000/devstoreaccount1/pytest-databases?restype=container",
            code=409,
            msg="Conflict",
            hdrs=MagicMock(),
            fp=None,
        ),
        resp_200,
    ]

    def fake_urlopen(_request: Any, timeout: float = 5.0) -> Any:
        assert timeout > 0
        assert _request.data is None
        assert "Content-type" not in _request.headers
        item = responses.pop(0)
        if isinstance(item, Exception):
            raise item
        return item

    monkeypatch.setattr(azure_blob_mod.urllib.request, "urlopen", fake_urlopen)

    assert ensure_azurite_container(
        account_url="http://127.0.0.1:10000/devstoreaccount1",
        account_name=DEFAULT_ACCOUNT_NAME,
        account_key=DEFAULT_ACCOUNT_KEY,
        container_name="pytest-databases",
    )
    assert ensure_azurite_container(
        account_url="http://127.0.0.1:10000/devstoreaccount1",
        account_name=DEFAULT_ACCOUNT_NAME,
        account_key=DEFAULT_ACCOUNT_KEY,
        container_name="pytest-databases",
    )
    assert azurite_container_exists(
        account_url="http://127.0.0.1:10000/devstoreaccount1",
        account_name=DEFAULT_ACCOUNT_NAME,
        account_key=DEFAULT_ACCOUNT_KEY,
        container_name="pytest-databases",
    )


def test_ensure_azurite_container_network_error(monkeypatch: pytest.MonkeyPatch) -> None:
    """Verify network errors return ``False`` during readiness checks."""

    def raise_url_error(_request: Any, timeout: float = 5.0) -> Any:
        msg = f"connection refused (timeout={timeout})"
        raise urllib.error.URLError(msg)

    monkeypatch.setattr(azure_blob_mod.urllib.request, "urlopen", raise_url_error)
    assert not ensure_azurite_container(
        account_url="http://127.0.0.1:10000/devstoreaccount1",
        account_name=DEFAULT_ACCOUNT_NAME,
        account_key=DEFAULT_ACCOUNT_KEY,
        container_name="pytest-databases",
    )
    assert not azurite_container_exists(
        account_url="http://127.0.0.1:10000/devstoreaccount1",
        account_name=DEFAULT_ACCOUNT_NAME,
        account_key=DEFAULT_ACCOUNT_KEY,
        container_name="pytest-databases",
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
        pytest.deprecated_call(match="azure_blob_container_client"),
        provide_azure_blob_container_client(service, "pytest-databases") as client,
    ):
        assert client is fake_client

    fake_cls.from_connection_string.assert_called_once_with(
        service.connection_string,
        container_name="pytest-databases",
    )


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
