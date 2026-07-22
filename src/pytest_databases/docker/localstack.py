from __future__ import annotations

import os
from dataclasses import dataclass
from typing import TYPE_CHECKING

import pytest

from pytest_databases.helpers import get_xdist_worker_num
from pytest_databases.types import ServiceContainer, XdistIsolationLevel

if TYPE_CHECKING:
    from collections.abc import Generator, Sequence

    from docker.models.containers import Container

    from pytest_databases._service import ContainerService


_LOCALSTACK_GATEWAY_PORT = 4566
_LOCALSTACK_CLI = """\
if command -v awslocal >/dev/null 2>&1; then
    exec awslocal --region "$AWS_DEFAULT_REGION" "$@"
fi
if command -v aws >/dev/null 2>&1; then
    exec aws --endpoint-url=http://localhost:4566 --region "$AWS_DEFAULT_REGION" "$@"
fi
exit 127
"""


def _exec_aws_cli(container: Container, arguments: Sequence[str]) -> tuple[int, str]:
    result = container.exec_run(["sh", "-c", _LOCALSTACK_CLI, "pytest-databases", *arguments])
    output_bytes = result.output if isinstance(result.output, bytes) else b"".join(result.output)
    output = output_bytes.decode("utf-8", errors="replace")
    exit_code = result.exit_code
    if exit_code is None:
        msg = "LocalStack AWS CLI command did not return an exit code"
        raise RuntimeError(msg)
    if exit_code == 127:
        msg = "LocalStack image must provide the awslocal or aws CLI"
        raise RuntimeError(msg)
    return exit_code, output


def _health_is_ready(container: Container) -> bool:
    result = container.exec_run([
        "curl",
        "--silent",
        "--show-error",
        "--fail",
        "--dump-header",
        "-",
        "--output",
        "/dev/null",
        "http://localhost:4566/_localstack/health",
    ])
    exit_code = result.exit_code
    if exit_code is None:
        return False
    if exit_code == 127:
        msg = "LocalStack image must provide curl for its in-container health check"
        raise RuntimeError(msg)
    output = result.output if isinstance(result.output, bytes) else b"".join(result.output)
    return exit_code == 0 and b"x-localstack:" in output.lower()


@dataclass
class LocalStackService(ServiceContainer):
    endpoint_url: str
    region: str
    access_key: str
    secret_key: str
    services: tuple[str, ...] | None
    resource_prefix: str

    def exec_aws_cli(self, *arguments: str) -> str:
        """Run an AWS command inside LocalStack without a host-side AWS client."""
        exit_code, output = _exec_aws_cli(self.container, arguments)
        if exit_code != 0:
            command = " ".join(arguments)
            msg = f"LocalStack AWS CLI command failed ({command}): {output.strip()}"
            raise RuntimeError(msg)
        return output


@pytest.fixture(scope="session")
def localstack_image() -> str:
    # 4.14.0 is the final tokenless Community release. Newer images require a
    # LocalStack account token and therefore cannot satisfy this fixture's
    # offline-by-default contract.
    return os.getenv("LOCALSTACK_IMAGE", "localstack/localstack:4.14.0")


@pytest.fixture(scope="session")
def localstack_auth_token() -> str | None:
    """Return an optional token for users who explicitly select a newer image."""
    return os.getenv("LOCALSTACK_AUTH_TOKEN")


@pytest.fixture(scope="session")
def localstack_region() -> str:
    return os.getenv("LOCALSTACK_REGION", "us-east-1")


@pytest.fixture(scope="session")
def localstack_access_key() -> str:
    return os.getenv("LOCALSTACK_ACCESS_KEY", "test")


@pytest.fixture(scope="session")
def localstack_secret_key() -> str:
    return os.getenv("LOCALSTACK_SECRET_KEY", "test")


@pytest.fixture(scope="session")
def localstack_services() -> tuple[str, ...] | None:
    value = os.getenv("LOCALSTACK_SERVICES")
    if value is None:
        return None
    services = tuple(service.strip() for service in value.split(",") if service.strip())
    return services or None


@pytest.fixture(scope="session")
def xdist_localstack_isolation_level() -> XdistIsolationLevel:
    return "database"


@pytest.fixture(scope="session")
def localstack_resource_prefix() -> str:
    if value := os.getenv("LOCALSTACK_RESOURCE_PREFIX"):
        return value
    worker_num = get_xdist_worker_num()
    if worker_num is None:
        return "pytest-databases-"
    return f"pytest-databases-{worker_num}-"


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
        if not _health_is_ready(service.container):
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
