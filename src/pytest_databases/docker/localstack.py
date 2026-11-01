"""LocalStack and MiniStack AWS service emulator fixtures and in-container CLI helpers."""

from __future__ import annotations

import contextlib
import os
import urllib.error
import urllib.request
from dataclasses import dataclass
from typing import TYPE_CHECKING

import pytest

from pytest_databases.helpers import exec_output_to_bytes, get_xdist_worker_num
from pytest_databases.types import ServiceContainer, XdistIsolationLevel

if TYPE_CHECKING:
    from collections.abc import Generator, Sequence

    from docker.models.containers import Container

    from pytest_databases._service import ContainerService

__all__ = [
    "LocalStackService",
    "MiniStackService",
    "localstack_access_key",
    "localstack_auth_token",
    "localstack_image",
    "localstack_region",
    "localstack_resource_prefix",
    "localstack_secret_key",
    "localstack_service",
    "localstack_services",
    "ministack_access_key",
    "ministack_auth_token",
    "ministack_image",
    "ministack_region",
    "ministack_resource_prefix",
    "ministack_secret_key",
    "ministack_service",
    "ministack_services",
    "provide_localstack_service",
    "provide_ministack_service",
    "xdist_localstack_isolation_level",
    "xdist_ministack_isolation_level",
]

_LOCALSTACK_GATEWAY_PORT = 4566
_DEFAULT_EMULATOR_IMAGE = "ministackorg/ministack:latest"

_LOCALSTACK_CLI = """\
if command -v awslocal >/dev/null 2>&1; then
    exec awslocal --region "$AWS_DEFAULT_REGION" "$@"
fi
if command -v aws >/dev/null 2>&1; then
    exec aws --endpoint-url=http://localhost:4566 --region "$AWS_DEFAULT_REGION" "$@"
fi
exit 127
"""
_HEALTH_PATHS: tuple[str, ...] = ("/_ministack/health", "/_localstack/health", "/health")


@dataclass
class MiniStackService(ServiceContainer):
    """Metadata and CLI helper for a running MiniStack or LocalStack container service."""

    endpoint_url: str
    region: str
    access_key: str
    secret_key: str
    services: tuple[str, ...] | None
    resource_prefix: str

    def exec_aws_cli(self, *arguments: str) -> str:
        """Run an AWS command inside the emulator container without a host-side AWS client.

        Returns:
            Decoded stdout/stderr from the AWS CLI command.

        Raises:
            RuntimeError: If the AWS CLI command exits with a non-zero status.
        """
        exit_code, output = _exec_aws_cli(self.container, arguments)
        if exit_code != 0:
            command = " ".join(arguments)
            msg = f"LocalStack AWS CLI command failed ({command}): {output.strip()}"
            raise RuntimeError(msg)
        return output


LocalStackService = MiniStackService


@contextlib.contextmanager
def provide_localstack_service(
    container_service: ContainerService,
    localstack_image: str,
    localstack_region: str,
    localstack_access_key: str,
    localstack_secret_key: str,
    localstack_auth_token: str | None,
    localstack_services: tuple[str, ...] | None,
    localstack_resource_prefix: str,
    xdist_localstack_isolation_level: XdistIsolationLevel,
) -> Generator[LocalStackService, None, None]:
    """Start and yield a ready MiniStack or LocalStack service container.

    Yields:
        A configured LocalStackService instance.
    """
    worker_num = get_xdist_worker_num()
    name = "localstack"
    transient = False
    if worker_num is not None and xdist_localstack_isolation_level == "server":
        name = f"{name}_{worker_num}"
        transient = True

    environment = {
        "AWS_ACCESS_KEY_ID": localstack_access_key,
        "AWS_DEFAULT_REGION": localstack_region,
        "AWS_SECRET_ACCESS_KEY": localstack_secret_key,
    }
    if localstack_services is not None:
        environment["SERVICES"] = ",".join(localstack_services)
    if localstack_auth_token is not None:
        environment["LOCALSTACK_AUTH_TOKEN"] = localstack_auth_token

    def check(service: ServiceContainer) -> bool:
        if not _health_is_ready(service.host, service.port):
            return False
        if localstack_services is not None and "sqs" not in localstack_services:
            return True
        exit_code, _ = _exec_aws_cli(service.container, ("sqs", "list-queues", "--output", "json"))
        return exit_code == 0

    with container_service.run(
        image=localstack_image,
        name=name,
        container_port=_LOCALSTACK_GATEWAY_PORT,
        env=environment,
        check=check,
        timeout=60,
        pause=0.5,
        transient=transient,
    ) as service:
        yield LocalStackService(
            host=service.host,
            port=service.port,
            container=service.container,
            endpoint_url=f"http://{service.host}:{service.port}",
            region=localstack_region,
            access_key=localstack_access_key,
            secret_key=localstack_secret_key,
            services=localstack_services,
            resource_prefix=localstack_resource_prefix,
        )


provide_ministack_service = provide_localstack_service


@pytest.fixture(scope="session")
def ministack_image() -> str:
    """Provide the MiniStack or LocalStack container image."""
    return os.getenv("MINISTACK_IMAGE", os.getenv("LOCALSTACK_IMAGE", _DEFAULT_EMULATOR_IMAGE))


localstack_image = ministack_image


@pytest.fixture(scope="session")
def ministack_auth_token() -> str | None:
    """Provide an optional auth token for commercial LocalStack image opt-in."""
    return os.getenv("MINISTACK_AUTH_TOKEN", os.getenv("LOCALSTACK_AUTH_TOKEN"))


localstack_auth_token = ministack_auth_token


@pytest.fixture(scope="session")
def ministack_region() -> str:
    """Provide the default AWS region for the emulator."""
    return os.getenv("MINISTACK_REGION", os.getenv("LOCALSTACK_REGION", "us-east-1"))


localstack_region = ministack_region


@pytest.fixture(scope="session")
def ministack_access_key() -> str:
    """Provide the test AWS access key ID for the emulator."""
    return os.getenv("MINISTACK_ACCESS_KEY", os.getenv("LOCALSTACK_ACCESS_KEY", "test"))


localstack_access_key = ministack_access_key


@pytest.fixture(scope="session")
def ministack_secret_key() -> str:
    """Provide the test AWS secret access key for the emulator."""
    return os.getenv("MINISTACK_SECRET_KEY", os.getenv("LOCALSTACK_SECRET_KEY", "test"))


localstack_secret_key = ministack_secret_key


@pytest.fixture(scope="session")
def ministack_services() -> tuple[str, ...] | None:
    """Provide an optional allowlist of AWS service names to enable."""
    value = os.getenv("MINISTACK_SERVICES", os.getenv("LOCALSTACK_SERVICES"))
    if value is None:
        return None
    services = tuple(service.strip() for service in value.split(",") if service.strip())
    return services or None


localstack_services = ministack_services


@pytest.fixture(scope="session")
def xdist_ministack_isolation_level() -> XdistIsolationLevel:
    """Provide the pytest-xdist isolation level for MiniStack and LocalStack."""
    return "database"


xdist_localstack_isolation_level = xdist_ministack_isolation_level


@pytest.fixture(scope="session")
def ministack_resource_prefix() -> str:
    """Provide a worker-scoped resource name prefix for emulator tests."""
    if value := (os.getenv("MINISTACK_RESOURCE_PREFIX") or os.getenv("LOCALSTACK_RESOURCE_PREFIX")):
        return value
    worker_num = get_xdist_worker_num()
    if worker_num is None:
        return "pytest-databases-"
    return f"pytest-databases-{worker_num}-"


localstack_resource_prefix = ministack_resource_prefix


@pytest.fixture(scope="session")
def localstack_service(
    container_service: ContainerService,
    localstack_image: str,
    localstack_region: str,
    localstack_access_key: str,
    localstack_secret_key: str,
    localstack_auth_token: str | None,
    localstack_services: tuple[str, ...] | None,
    localstack_resource_prefix: str,
    xdist_localstack_isolation_level: XdistIsolationLevel,
) -> Generator[LocalStackService, None, None]:
    """Start and yield a ready LocalStack service container.

    Yields:
        A configured LocalStackService instance.
    """
    with provide_localstack_service(
        container_service=container_service,
        localstack_image=localstack_image,
        localstack_region=localstack_region,
        localstack_access_key=localstack_access_key,
        localstack_secret_key=localstack_secret_key,
        localstack_auth_token=localstack_auth_token,
        localstack_services=localstack_services,
        localstack_resource_prefix=localstack_resource_prefix,
        xdist_localstack_isolation_level=xdist_localstack_isolation_level,
    ) as service:
        yield service


@pytest.fixture(scope="session")
def ministack_service(
    container_service: ContainerService,
    ministack_image: str,
    ministack_region: str,
    ministack_access_key: str,
    ministack_secret_key: str,
    ministack_auth_token: str | None,
    ministack_services: tuple[str, ...] | None,
    ministack_resource_prefix: str,
    xdist_ministack_isolation_level: XdistIsolationLevel,
) -> Generator[MiniStackService, None, None]:
    """Start and yield a ready MiniStack service container.

    Yields:
        A configured MiniStackService instance.
    """
    with provide_ministack_service(
        container_service=container_service,
        localstack_image=ministack_image,
        localstack_region=ministack_region,
        localstack_access_key=ministack_access_key,
        localstack_secret_key=ministack_secret_key,
        localstack_auth_token=ministack_auth_token,
        localstack_services=ministack_services,
        localstack_resource_prefix=ministack_resource_prefix,
        xdist_localstack_isolation_level=xdist_ministack_isolation_level,
    ) as service:
        yield service


def _exec_aws_cli(container: Container, arguments: Sequence[str]) -> tuple[int, str]:
    """Execute an AWS CLI command inside the emulator container.

    Args:
        container: Running emulator container instance.
        arguments: AWS CLI subcommand and arguments.

    Returns:
        Tuple of ``(exit_code, decoded_output)``.

    Raises:
        RuntimeError: If no exit code is returned or the CLI binary is missing.
    """
    result = container.exec_run(["sh", "-c", _LOCALSTACK_CLI, "pytest-databases", *arguments])
    output = exec_output_to_bytes(result.output).decode("utf-8", errors="replace")
    exit_code = result.exit_code
    if exit_code is None:
        msg = "LocalStack AWS CLI command did not return an exit code"
        raise RuntimeError(msg)
    if exit_code == 127:
        msg = "LocalStack or MiniStack image must provide the awslocal or aws CLI"
        raise RuntimeError(msg)
    return exit_code, output


def _health_is_ready(host: str, port: int, *, timeout: float = 2.0) -> bool:
    """Verify the MiniStack or LocalStack HTTP gateway health endpoint responds.

    Returns:
        True when any gateway health endpoint responds with HTTP 200.
    """
    for path in _HEALTH_PATHS:
        url = f"http://{host}:{port}{path}"
        try:
            with urllib.request.urlopen(url, timeout=timeout) as response:
                if response.status == 200:
                    return True
        except (OSError, urllib.error.URLError):
            continue
    return False
