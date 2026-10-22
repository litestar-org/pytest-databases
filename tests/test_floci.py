"""Tests for Floci multi-cloud (GCP, OCI, AWS, Azure) emulator container fixtures and HTTP helpers."""

from __future__ import annotations

import email.message
import io
import json
import urllib.error
import urllib.request
from typing import TYPE_CHECKING, Any
from unittest.mock import MagicMock

from pytest_databases.docker import floci
from pytest_databases.docker.floci import (
    DEFAULT_FLOCI_AWS_IMAGE,
    DEFAULT_FLOCI_AZ_IMAGE,
    DEFAULT_FLOCI_GCP_IMAGE,
    DEFAULT_FLOCI_OCI_IMAGE,
    FlociAWSService,
    FlociAzureService,
    FlociGCPService,
    FlociOCIService,
    check_floci_health,
    ensure_gcs_bucket,
    ensure_oci_bucket,
)

if TYPE_CHECKING:
    import pytest
    from pytest import MonkeyPatch


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


def test_check_floci_health_probes_floci_and_fallback(monkeypatch: MonkeyPatch) -> None:
    """Verify check_floci_health probes /_floci/health and falls back to /_localstack/health."""
    visited_urls: list[str] = []

    def fake_urlopen(request: Any, **_kwargs: Any) -> Any:
        visited_urls.append(request.full_url)
        if request.full_url.endswith("/_floci/health"):
            raise urllib.error.HTTPError(
                request.full_url,
                404,
                "Not Found",
                email.message.Message(),
                io.BytesIO(b""),
            )
        resp = MagicMock()
        resp.status = 200
        resp.read.return_value = b'{"services": {"gcs": "running"}}'
        resp.__enter__.return_value = resp
        resp.__exit__.return_value = False
        return resp

    monkeypatch.setattr(urllib.request, "urlopen", fake_urlopen)
    payload = check_floci_health("127.0.0.1", 4566)
    assert payload == {"services": {"gcs": "running"}}
    assert visited_urls == [
        "http://127.0.0.1:4566/_floci/health",
        "http://127.0.0.1:4566/_localstack/health",
    ]


def test_ensure_gcs_and_oci_buckets_handle_created_and_conflict(monkeypatch: MonkeyPatch) -> None:
    """Verify ensure_gcs_bucket and ensure_oci_bucket issue stdlib HTTP POSTs and tolerate HTTP 409."""
    captured: list[tuple[str, bytes]] = []

    def fake_urlopen(request: Any, **_kwargs: Any) -> Any:
        captured.append((request.full_url, request.data or b""))
        resp = MagicMock()
        resp.status = 200
        resp.read.return_value = json.dumps({"name": "my-bucket"}).encode("utf-8")
        resp.__enter__.return_value = resp
        resp.__exit__.return_value = False
        return resp

    monkeypatch.setattr(urllib.request, "urlopen", fake_urlopen)
    gcs_res = ensure_gcs_bucket("127.0.0.1", 4566, "my-bucket", project="test-proj")
    assert gcs_res["name"] == "my-bucket"
    assert captured[-1][0] == "http://127.0.0.1:4566/storage/v1/b?project=test-proj"

    oci_res = ensure_oci_bucket("127.0.0.1", 4566, "testns", "my-bucket", compartment_id="ocid1.test")
    assert oci_res["name"] == "my-bucket"
    assert captured[-1][0] == "http://127.0.0.1:4566/n/testns/b/"

    def conflict_urlopen(request: Any, **_kwargs: Any) -> Any:
        raise urllib.error.HTTPError(
            request.full_url,
            409,
            "Conflict",
            email.message.Message(),
            io.BytesIO(b""),
        )

    monkeypatch.setattr(urllib.request, "urlopen", conflict_urlopen)
    assert ensure_gcs_bucket("127.0.0.1", 4566, "my-bucket", project="test-proj") == {
        "name": "my-bucket",
        "project": "test-proj",
    }
    assert ensure_oci_bucket("127.0.0.1", 4566, "testns", "my-bucket") == {
        "name": "my-bucket",
        "namespace": "testns",
    }


def test_floci_service_dataclasses(monkeypatch: MonkeyPatch) -> None:
    """Verify FlociGCPService, FlociOCIService, FlociAWSService, and FlociAzureService properties."""
    gcp = FlociGCPService(
        container=MagicMock(),
        host="127.0.0.1",
        port=4566,
        endpoint_url="http://127.0.0.1:4566",
        resource_prefix="pytest-databases-",
        project="pytest-databases",
    )
    assert gcp.storage_emulator_host == "http://127.0.0.1:4566"
    assert gcp.pubsub_emulator_host == "127.0.0.1:4566"

    monkeypatch.setattr(floci, "ensure_gcs_bucket", lambda _h, _p, name, **_kw: {"name": name})
    assert gcp.ensure_bucket("events") == {"name": "events"}

    oci = FlociOCIService(
        container=MagicMock(),
        host="127.0.0.1",
        port=4566,
        endpoint_url="http://127.0.0.1:4566",
        resource_prefix="pytest-databases-",
        namespace="pytestns",
        region="us-ashburn-1",
        compartment_id="ocid1.compartment.oc1..pytest",
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
        port=4566,
        endpoint_url="http://127.0.0.1:4566",
        resource_prefix="pytest-databases-",
        account_name="devstoreaccount1",
        account_key="secret",
    )
    assert az.blob_endpoint == "http://127.0.0.1:4566/devstoreaccount1"


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
        floci_oci_namespace,
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
        assert floci_oci_namespace == "pytestns"
        assert floci_oci_region == "us-ashburn-1"
        assert floci_aws_region == "us-east-1"
        assert floci_az_account_name == "devstoreaccount1"
        assert xdist_floci_isolation_level == "database"
    """)

    result = pytester.runpytest_subprocess("-p", "pytest_databases", "-vv")
    result.assert_outcomes(passed=1)
