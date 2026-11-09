"""RabbitMQ AMQP broker container service fixtures and in-container CLI helpers."""

from __future__ import annotations

import contextlib
import dataclasses
import shlex
from typing import TYPE_CHECKING
from urllib.parse import quote

import pytest
from docker.errors import APIError

from pytest_databases.helpers import exec_output_to_bytes, get_xdist_worker_num
from pytest_databases.types import ServiceContainer, XdistIsolationLevel

if TYPE_CHECKING:
    from collections.abc import Generator

    from docker.models.containers import Container

    from pytest_databases._service import ContainerService

__all__ = [
    "RabbitMQService",
    "provide_rabbitmq_service",
    "rabbitmq_image",
    "rabbitmq_password",
    "rabbitmq_service",
    "rabbitmq_username",
    "rabbitmq_vhost",
    "xdist_rabbitmq_isolation_level",
]

_RABBITMQ_HOME = "/run/pytest-databases-rabbitmq"
_RABBITMQ_COMMAND = (
    f"mkdir -p {_RABBITMQ_HOME} && "
    f"if [ ! -f {_RABBITMQ_HOME}/.erlang.cookie ]; then "
    f"tr -dc A-Z < /dev/urandom | head -c 32 > {_RABBITMQ_HOME}/.erlang.cookie; fi && "
    f"chmod 400 {_RABBITMQ_HOME}/.erlang.cookie && "
    f"chown -R rabbitmq:rabbitmq {_RABBITMQ_HOME} && exec gosu rabbitmq env HOME={_RABBITMQ_HOME} rabbitmq-server"
)
"""Prepare the broker home and a random Erlang cookie before the server starts.

The cookie is written before ``rabbitmq-server`` starts so the server and the in-container CLI tools (run as root
with the same ``HOME``) read the same file instead of racing to create it. ``gosu`` resets ``HOME`` to the
``rabbitmq`` user's home, so the server command sets it again.
"""


@dataclasses.dataclass
class RabbitMQService(ServiceContainer):
    """Connection metadata for a RabbitMQ AMQP service."""

    username: str
    password: str
    vhost: str
    management_port: int = 15672

    @property
    def amqp_url(self) -> str:
        """The AMQP connection URL with escaped credentials and virtual host."""
        username = quote(self.username, safe="")
        password = quote(self.password, safe="")
        vhost = quote(self.vhost, safe="")
        return f"amqp://{username}:{password}@{self.host}:{self.port}/{vhost}"

    @property
    def management_url(self) -> str:
        """The HTTP management API base URL."""
        return f"http://{self.host}:{self.management_port}"


@contextlib.contextmanager
def provide_rabbitmq_service(
    container_service: ContainerService,
    rabbitmq_image: str,
    rabbitmq_username: str,
    rabbitmq_password: str,
    rabbitmq_vhost: str,
    xdist_rabbitmq_isolation_level: XdistIsolationLevel,
) -> Generator[RabbitMQService, None, None]:
    """Start and yield a ready RabbitMQ AMQP service container.

    Yields:
        A configured RabbitMQService instance.
    """
    worker_num = get_xdist_worker_num()
    name = "rabbitmq"
    transient = False
    if worker_num is not None and xdist_rabbitmq_isolation_level == "server":
        name = f"rabbitmq_{worker_num}"
        transient = True

    with container_service.run(
        rabbitmq_image,
        container_port=5672,
        extra_ports={15672: None},
        name=name,
        command=shlex.join(["bash", "-c", _RABBITMQ_COMMAND]),
        check=_rabbitmq_responsive,
        wait_for_log="Server startup complete",
        env={
            "RABBITMQ_DEFAULT_USER": rabbitmq_username,
            "RABBITMQ_DEFAULT_PASS": rabbitmq_password,
            "RABBITMQ_DEFAULT_VHOST": "pytest_databases",
            "RABBITMQ_MNESIA_BASE": f"{_RABBITMQ_HOME}/mnesia",
            "HOME": _RABBITMQ_HOME,
        },
        timeout=60,
        transient=transient,
    ) as service:
        _ensure_vhost(service.container, username=rabbitmq_username, vhost=rabbitmq_vhost)
        management_port = container_service.resolve_port(service.container, 15672)
        yield RabbitMQService(
            container=service.container,
            host=service.host,
            port=service.port,
            username=rabbitmq_username,
            password=rabbitmq_password,
            vhost=rabbitmq_vhost,
            management_port=management_port,
        )


@pytest.fixture(scope="session")
def xdist_rabbitmq_isolation_level() -> XdistIsolationLevel:
    """Provide the pytest-xdist isolation level for RabbitMQ."""
    return "database"


@pytest.fixture(scope="session")
def rabbitmq_image() -> str:
    """Provide the RabbitMQ container image."""
    return "rabbitmq:4.3-management"


@pytest.fixture(scope="session")
def rabbitmq_username() -> str:
    """Provide the default RabbitMQ username."""
    return "pytest-databases"


@pytest.fixture(scope="session")
def rabbitmq_password() -> str:
    """Provide the default RabbitMQ password."""
    return "pytest-databases-secret"


@pytest.fixture(scope="session")
def rabbitmq_vhost(xdist_rabbitmq_isolation_level: XdistIsolationLevel) -> str:
    """Provide a worker-scoped RabbitMQ virtual host name."""
    worker_num = get_xdist_worker_num()
    if worker_num is not None and xdist_rabbitmq_isolation_level == "database":
        return f"pytest_databases_{worker_num}"
    return "pytest_databases"


@pytest.fixture(scope="session")
def rabbitmq_service(
    container_service: ContainerService,
    rabbitmq_image: str,
    rabbitmq_username: str,
    rabbitmq_password: str,
    rabbitmq_vhost: str,
    xdist_rabbitmq_isolation_level: XdistIsolationLevel,
) -> Generator[RabbitMQService, None, None]:
    """Start and yield a ready RabbitMQ AMQP service container.

    Yields:
        A configured RabbitMQService instance.
    """
    with provide_rabbitmq_service(
        container_service=container_service,
        rabbitmq_image=rabbitmq_image,
        rabbitmq_username=rabbitmq_username,
        rabbitmq_password=rabbitmq_password,
        rabbitmq_vhost=rabbitmq_vhost,
        xdist_rabbitmq_isolation_level=xdist_rabbitmq_isolation_level,
    ) as service:
        yield service


def _exec(container: Container, *args: str) -> tuple[int, bytes]:
    """Execute a command inside the RabbitMQ container and return exit code and output.

    Returns:
        Tuple of ``(exit_code, output_bytes)``.
    """
    result = container.exec_run(list(args))
    return result.exit_code if result.exit_code is not None else -1, exec_output_to_bytes(result.output)


def _rabbitmq_responsive(service: ServiceContainer) -> bool:
    """Verify RabbitMQ is running and listening on the internal AMQP port 5672.

    Returns:
        True when RabbitMQ is running and listening on port 5672.
    """
    try:
        running_code, _ = _exec(service.container, "rabbitmq-diagnostics", "-q", "check_running")
        listener_code, _ = _exec(service.container, "rabbitmq-diagnostics", "-q", "check_port_listener", "5672")
    except APIError:
        return False
    return running_code == 0 and listener_code == 0


def _ensure_vhost(container: Container, *, username: str, vhost: str) -> None:
    """Create the requested virtual host if absent and grant permissions to the user.

    Raises:
        RuntimeError: If listing, creating, or granting permissions on the virtual host fails.
    """
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
