"""Tests for Floci multi-cloud (GCP, OCI, AWS, Azure) emulator container fixtures and HTTP helpers."""

from __future__ import annotations

import email.message
import io
import json
import urllib.error
import urllib.request
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
    provide_floci_container,
)
from tests.conftest import unwrap_fixture

if TYPE_CHECKING:
    from pytest import MonkeyPatch

    from pytest_databases.docker.floci import FlociCloud

FLOCI_LIVE_CASES = {
    "aws": """
    from pytest_databases._s3 import build_bucket_request, create_s3_bucket

    def test_cloud(floci_aws_service) -> None:
        service = floci_aws_service
        assert check_floci_health(service.host, service.port, "/_floci/health")["services"]["s3"] == "running"
        bucket = f"{service.resource_prefix}bucket"
        create_s3_bucket(
            service.endpoint_url, bucket, access_key=service.access_key, secret_key=service.secret_key
        )
        request = build_bucket_request(
            "HEAD", service.endpoint_url, bucket, access_key=service.access_key, secret_key=service.secret_key
        )
        with urllib.request.urlopen(request, timeout=5) as response:
            assert response.status == 200
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
    def test_cloud(floci_gcp_service) -> None:
        service = floci_gcp_service
        assert check_floci_health(service.host, service.port, "/_floci-gcp/health")["services"]["gcs"] == "running"
        bucket = f"{service.resource_prefix}bucket"
        assert service.ensure_bucket(bucket)["name"] == bucket
        assert service.ensure_bucket(bucket) == {"name": bucket, "project": service.project}
        with urllib.request.urlopen(f"{service.endpoint_url}/storage/v1/b/{bucket}", timeout=5) as response:
            assert json.loads(response.read())["name"] == bucket
    """,
    "oci": """
    def test_cloud(floci_oci_service) -> None:
        service = floci_oci_service
        assert check_floci_health(service.host, service.port, "/_floci-oci/health")["services"]["objectstorage"] == "running"
        bucket = f"{service.resource_prefix}bucket"
        created = service.ensure_bucket(bucket)
        assert created["name"] == bucket
        assert created["namespace"] == service.namespace
        assert service.ensure_bucket(bucket) == {"name": bucket, "namespace": service.namespace}
        url = f"{service.endpoint_url}/n/{service.namespace}/b/{bucket}"
        with urllib.request.urlopen(url, timeout=5) as response:
            assert json.loads(response.read())["compartmentId"] == service.compartment_id
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
        ("floci_gcp_service", "gcp", {"floci_gcp_image": "a", "floci_gcp_project": "p"}),
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
    monkeypatch: MonkeyPatch, fixture_name: str, cloud: FlociCloud, fixture_args: dict[str, str]
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


def test_ensure_gcs_and_oci_buckets_handle_created_and_conflict(monkeypatch: MonkeyPatch) -> None:
    """Verify ensure_gcs_bucket and ensure_oci_bucket issue stdlib HTTP POSTs and tolerate HTTP 409."""
    captured: list[tuple[str, dict[str, Any]]] = []

    def fake_urlopen(request: Any, **_kwargs: Any) -> Any:
        captured.append((request.full_url, json.loads(request.data)))
        resp = MagicMock()
        resp.read.return_value = json.dumps({"name": "my-bucket"}).encode("utf-8")
        resp.__enter__.return_value = resp
        resp.__exit__.return_value = False
        return resp

    monkeypatch.setattr(urllib.request, "urlopen", fake_urlopen)
    assert ensure_gcs_bucket("127.0.0.1", 4588, "my-bucket", project="test-proj") == {"name": "my-bucket"}
    assert captured[-1] == ("http://127.0.0.1:4588/storage/v1/b?project=test-proj", {"name": "my-bucket"})

    assert ensure_oci_bucket("127.0.0.1", 4599, "floci-local", "my-bucket") == {"name": "my-bucket"}
    assert captured[-1] == (
        "http://127.0.0.1:4599/n/floci-local/b/",
        {"name": "my-bucket", "compartmentId": DEFAULT_FLOCI_OCI_COMPARTMENT_ID},
    )

    def conflict_urlopen(request: Any, **_kwargs: Any) -> Any:
        raise urllib.error.HTTPError(request.full_url, 409, "Conflict", email.message.Message(), io.BytesIO(b""))

    monkeypatch.setattr(urllib.request, "urlopen", conflict_urlopen)
    assert ensure_gcs_bucket("127.0.0.1", 4588, "my-bucket", project="test-proj") == {
        "name": "my-bucket",
        "project": "test-proj",
    }
    assert ensure_oci_bucket("127.0.0.1", 4599, "floci-local", "my-bucket") == {
        "name": "my-bucket",
        "namespace": "floci-local",
    }


def test_ensure_bucket_raises_on_other_http_errors(monkeypatch: MonkeyPatch) -> None:
    """HTTP errors other than 409 propagate."""

    def rejecting_urlopen(request: Any, **_kwargs: Any) -> Any:
        raise urllib.error.HTTPError(request.full_url, 400, "Bad Request", email.message.Message(), io.BytesIO(b""))

    monkeypatch.setattr(urllib.request, "urlopen", rejecting_urlopen)
    with pytest.raises(urllib.error.HTTPError):
        ensure_oci_bucket("127.0.0.1", 4599, "floci-local", "my-bucket", compartment_id="ocid1.compartment.oc1..x")


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
    import urllib.request

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
            assert request.getfixturevalue("floci_gcp_service").host == "127.0.0.1"
            assert request.getfixturevalue("floci_oci_service").host == "127.0.0.1"
            assert request.getfixturevalue("floci_aws_service").host == "127.0.0.1"
            assert request.getfixturevalue("floci_az_service").host == "127.0.0.1"
    """)
    result = pytester.runpytest("-p", "no:sugar", "-p", "pytest_databases")
    result.assert_outcomes(passed=1)
