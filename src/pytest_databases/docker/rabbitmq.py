from __future__ import annotations

import dataclasses
from typing import TYPE_CHECKING
from urllib.parse import quote

import pytest
from docker.errors import APIError

from pytest_databases.helpers import get_xdist_worker_num
from pytest_databases.types import ServiceContainer, XdistIsolationLevel

_RABBITMQ_COMMAND = (
    "mkdir -p /run/pytest-databases-rabbitmq && "
    "chown rabbitmq:rabbitmq /run/pytest-databases-rabbitmq && exec gosu rabbitmq rabbitmq-server"
)

if TYPE_CHECKING:
    from collections.abc import Generator, Iterator

    from docker.models.containers import Container

    from pytest_databases._service import ContainerService


def _output_to_bytes(output: bytes | str | Iterator[bytes]) -> bytes:
    if isinstance(output, bytes):
        return output
    if isinstance(output, str):
        return output.encode()
    return b"".join(output)


def _exec(container: Container, *args: str) -> tuple[int, bytes]:
    result = container.exec_run(list(args))
    return result.exit_code if result.exit_code is not None else -1, _output_to_bytes(result.output)


def _rabbitmq_responsive(service: ServiceContainer) -> bool:
    try:
        running_code, _ = _exec(service.container, "rabbitmq-diagnostics", "-q", "check_running")
        listener_code, _ = _exec(service.container, "rabbitmq-diagnostics", "-q", "check_port_listener", "5672")
    except APIError:
        return False
    return running_code == 0 and listener_code == 0


def _ensure_vhost(container: Container, *, username: str, vhost: str) -> None:
    list_code, output = _exec(container, "rabbitmqctl", "-q", "list_vhosts", "name", "--no-table-headers")
    if list_code != 0:
        message = output.decode(errors="replace")
        raise RuntimeError(message)
    if vhost not in output.decode().splitlines():
        add_code, add_output = _exec(container, "rabbitmqctl", "-q", "add_vhost", vhost)
        if add_code != 0:
            message = add_output.decode(errors="replace")
            raise RuntimeError(message)
    permission_code, permission_output = _exec(
        container,
        "rabbitmqctl",
        "-q",
        "set_permissions",
        "-p",
        vhost,
        username,
        ".*",
        ".*",
        ".*",
    )
    if permission_code != 0:
        message = permission_output.decode(errors="replace")
        raise RuntimeError(message)


@dataclasses.dataclass
class RabbitMQService(ServiceContainer):
    """Connection metadata for a RabbitMQ AMQP service."""

    username: str
    password: str
    vhost: str

    @property
    def amqp_url(self) -> str:
        """Return an AMQP URL with escaped credentials and virtual host."""
        username = quote(self.username, safe="")
        password = quote(self.password, safe="")
        vhost = quote(self.vhost, safe="")
        return f"amqp://{username}:{password}@{self.host}:{self.port}/{vhost}"


@pytest.fixture(scope="session")
def xdist_rabbitmq_isolation_level() -> XdistIsolationLevel:
    return "database"


@pytest.fixture(scope="session")
def rabbitmq_image() -> str:
    return "rabbitmq:4.3-management"


@pytest.fixture(scope="session")
def rabbitmq_username() -> str:
    return "pytest-databases"


@pytest.fixture(scope="session")
def rabbitmq_password() -> str:
    return "pytest-databases-secret"


@pytest.fixture(scope="session")
def rabbitmq_vhost(xdist_rabbitmq_isolation_level: XdistIsolationLevel) -> str:
    worker_num = get_xdist_worker_num()
    if worker_num is not None and xdist_rabbitmq_isolation_level == "database":
        return f"pytest_databases_{worker_num}"
    return "pytest_databases"


@pytest.fixture(scope="session")
def rabbitmq_host(rabbitmq_service: RabbitMQService) -> str:
    return rabbitmq_service.host


@pytest.fixture(scope="session")
def rabbitmq_port(rabbitmq_service: RabbitMQService) -> int:
    return rabbitmq_service.port


@pytest.fixture(scope="session")
def rabbitmq_service(
    container_service: ContainerService,
    rabbitmq_image: str,
    rabbitmq_username: str,
    rabbitmq_password: str,
    rabbitmq_vhost: str,
    xdist_rabbitmq_isolation_level: XdistIsolationLevel,
) -> Generator[RabbitMQService, None, None]:
    worker_num = get_xdist_worker_num()
    name = "rabbitmq"
    if worker_num is not None and xdist_rabbitmq_isolation_level == "server":
        name = f"rabbitmq_{worker_num + 1}"

    with container_service.run(
        rabbitmq_image,
        container_port=5672,
        name=name,
        command=["bash", "-c", _RABBITMQ_COMMAND],
        check=_rabbitmq_responsive,
        wait_for_log="Server startup complete",
        env={
            "RABBITMQ_DEFAULT_USER": rabbitmq_username,
            "RABBITMQ_DEFAULT_PASS": rabbitmq_password,
            "RABBITMQ_DEFAULT_VHOST": "pytest_databases",
            "RABBITMQ_ERLANG_COOKIE": "pytest-databases-erlang-cookie",
            "RABBITMQ_MNESIA_BASE": "/run/pytest-databases-rabbitmq/mnesia",
            "HOME": "/run/pytest-databases-rabbitmq",
        },
        timeout=60,
        transient=xdist_rabbitmq_isolation_level == "server",
    ) as service:
        _ensure_vhost(service.container, username=rabbitmq_username, vhost=rabbitmq_vhost)
        yield RabbitMQService(
            container=service.container,
            host=service.host,
            port=service.port,
            username=rabbitmq_username,
            password=rabbitmq_password,
            vhost=rabbitmq_vhost,
        )
