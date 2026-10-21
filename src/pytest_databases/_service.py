"""Container lifecycle and service orchestration for test databases."""

from __future__ import annotations

import contextlib
import time
from contextlib import AbstractContextManager, contextmanager
from typing import TYPE_CHECKING, Any, Callable

import filelock
import pytest
from docker.errors import APIError, ImageNotFound
from typing_extensions import Self

from pytest_databases.helpers import get_xdist_worker_id
from pytest_databases.runtime import (
    ContainerRuntimeConfig,
    default_host_from_base_url,
    resolve_container_runtime,
)
from pytest_databases.types import ServiceContainer

if TYPE_CHECKING:
    import pathlib
    from collections.abc import Generator
    from types import TracebackType

    from docker import DockerClient
    from docker.models.containers import Container
    from docker.types import Ulimit

__all__ = [
    "ContainerService",
    "DockerService",
    "container_client",
    "container_runtime",
    "container_service",
    "docker_client",
    "docker_service",
    "get_docker_client",
    "get_docker_host",
    "pytest_addoption",
    "pytest_sessionfinish",
]


def pytest_addoption(parser: pytest.Parser) -> None:
    """Register CLI options and ini parameters for pytest-databases.

    Args:
        parser: The pytest CLI and configuration parser.
    """
    parser.addoption(
        "--container-runtime",
        action="store",
        choices=("auto", "docker", "podman"),
        default=None,
        help="Container runtime to use for database containers (auto, docker, podman).",
    )
    parser.addini(
        "container_runtime",
        help="Default container runtime (auto, docker, podman).",
        default=None,
    )


def get_docker_host() -> str:
    """Return the resolved container runtime host endpoint.

    Returns:
        The host endpoint string for the resolved container runtime.
    """
    return resolve_container_runtime().endpoint


def get_docker_client() -> DockerClient:
    """Return a DockerClient connected to the resolved container runtime.

    Returns:
        A DockerClient instance connected to the resolved runtime.
    """
    return resolve_container_runtime().create_client()


def _stop_single_container(container: Container) -> None:
    """Stop or remove a single container based on its state.

    Args:
        container: The container to terminate.
    """
    status = container.status
    if status == "running":
        container.kill()
    elif status in {"created", "stopped", "dead"}:
        container.remove()
    elif status != "removing":
        msg = f"Cannot handle container in state {status}"
        raise RuntimeError(msg)


def _stop_all_containers(client: DockerClient) -> None:
    """Stop all containers managed by pytest_databases.

    Args:
        client: The Docker client to issue stop and remove calls against.
    """
    containers: list[Container] = client.containers.list(
        all=True,
        filters={"label": "pytest_databases"},
        ignore_removed=True,
    )
    for container in containers:
        try:
            _stop_single_container(container)
        except APIError as exc:
            if exc.status_code not in {404, 409}:
                raise


class ContainerService(AbstractContextManager):
    """Manager for ephemeral test database containers."""

    def __init__(
        self,
        client: DockerClient,
        tmp_path: pathlib.Path,
        session: pytest.Session,
        runtime_config: ContainerRuntimeConfig | None = None,
    ) -> None:
        self._client = client
        self._tmp_path = tmp_path
        self._session = session
        self._is_xdist = get_xdist_worker_id() is not None
        self._runtime_config = runtime_config

    def __enter__(self) -> Self:
        if self._is_xdist:
            ctrl_file = _get_ctrl_file(self._session)
            with filelock.FileLock(ctrl_file.with_suffix(".lock")):
                if not ctrl_file.exists():
                    ctrl_file.touch()
                    self._stop_all_containers()
        else:
            self._stop_all_containers()
        return self

    def __exit__(
        self,
        /,
        __exc_type: type[BaseException] | None,
        __exc_value: BaseException | None,
        __traceback: TracebackType | None,
    ) -> None:
        if not self._is_xdist:
            self._stop_all_containers()

    def _get_container(self, name: str) -> Container | None:
        containers = self._client.containers.list(
            filters={"name": name},
        )
        if len(containers) > 1:
            msg = "More than one running container found"
            raise ValueError(msg)
        if containers:
            return containers[0]
        return None

    def _stop_all_containers(self) -> None:
        _stop_all_containers(self._client)

    def resolve_service_host(
        self,
        container: Container,
        container_host: str = "127.0.0.1",
    ) -> str:
        """Resolve the reachable host for container port communication.

        Args:
            container: The running container instance.
            container_host: The requested container host default.

        Returns:
            The resolved reachable host string.
        """
        if container_host != "127.0.0.1":
            return container_host
        if self._runtime_config is not None:
            return default_host_from_base_url(self._runtime_config.endpoint)
        return "127.0.0.1"

    @staticmethod
    def get_internal_network_ip(
        container: Container,
        network_name: str | None = None,
    ) -> str:
        """Extract the internal network IP address of the container.

        Args:
            container: The container to inspect.
            network_name: Optional network name to read IP address from.

        Returns:
            The internal IP address string.
        """
        container.reload()
        networks = container.attrs.get("NetworkSettings", {}).get("Networks", {})
        if not networks:
            msg = f"Container {container.name!r} has no network settings"
            raise RuntimeError(msg)
        if network_name and network_name in networks:
            ip = networks[network_name].get("IPAddress")
            if ip:
                return str(ip)
        for net_info in networks.values():
            ip = net_info.get("IPAddress")
            if ip:
                return str(ip)
        msg = f"Container {container.name!r} has no assigned IP address"
        raise RuntimeError(msg)

    @contextmanager
    def run(
        self,
        image: str,
        container_port: int,
        name: str,
        container_host: str = "127.0.0.1",
        command: str | None = None,
        env: dict[str, Any] | None = None,
        exec_after_start: str | list[str] | None = None,
        check: Callable[[ServiceContainer], bool] | None = None,
        wait_for_log: str | bytes | None = None,
        timeout: int = 10,
        pause: float = 0.1,
        transient: bool = False,
        ulimits: list[Ulimit] | None = None,
        shm_size: int | None = None,
        mem_limit: str | None = None,
        platform: str | None = None,
        protocol: str = "tcp",
        host_port: int | None = None,
    ) -> Generator[ServiceContainer, None, None]:
        """Start and manage an ephemeral container service lifecycle.

        Args:
            image: The container image to run.
            container_port: The internal container port to expose.
            name: The service name identifier.
            container_host: The host address to expose.
            command: The command to run in the container.
            env: Environment variables to pass into the container.
            exec_after_start: Command to execute after container start.
            check: Readiness check function receiving ServiceContainer.
            wait_for_log: Log substring to wait for during startup.
            timeout: Maximum wait time in seconds.
            pause: Sleep interval between polling attempts.
            transient: Whether to remove container on context exit.
            ulimits: Custom ulimits for the container.
            shm_size: Shared memory size in bytes.
            mem_limit: Memory limit string.
            platform: Target container platform.
            protocol: Port protocol (tcp, udp, or both).
            host_port: Optional fixed host port binding.

        Yields:
            A ServiceContainer handle with host and port bindings.
        """
        if check is None and wait_for_log is None:
            msg = "Must set at least check or wait_for_log"
            raise ValueError(msg)

        platform_kwarg: dict[str, Any] = {}
        if platform is not None:
            platform_kwarg["platform"] = platform

        service_name = f"pytest_databases_{name}"
        lock = filelock.FileLock(self._tmp_path / service_name) if self._is_xdist else contextlib.nullcontext()
        with lock:
            container = self._get_container(service_name)
            try:
                self._client.images.get(image)
            except ImageNotFound:
                for attempt in range(3):
                    try:
                        image_name, *tag = image.rsplit(":", maxsplit=1)
                        image_tag = tag[0] if tag else None
                        self._client.images.pull(image_name, tag=image_tag, **platform_kwarg)
                        break
                    except (APIError, ImageNotFound):
                        if attempt == 2:
                            raise
                        time.sleep(2**attempt)

            if container is None:
                ports_dict: dict[Any, Any] = {container_port: host_port}
                container = self._client.containers.run(
                    image,
                    command,
                    detach=True,
                    remove=True,
                    ports=ports_dict,
                    labels=["pytest_databases"],
                    name=service_name,
                    environment=env,
                    ulimits=ulimits,
                    mem_limit=mem_limit,
                    **platform_kwarg,
                )

                for i in range(10):
                    container.reload()
                    if any(v for v in container.ports.values()):
                        break
                    time.sleep(0.1 + (i / 10))
                else:
                    msg = f"Service {service_name!r} failed to create container"
                    raise ValueError(msg)
            else:
                container.reload()

        binding = None
        if protocol == "both":
            binding = container.ports.get(f"{container_port}/tcp") or container.ports.get(f"{container_port}/udp")
        elif protocol in {"tcp", "udp"}:
            binding = container.ports.get(f"{container_port}/{protocol}")
        else:
            msg = f"Invalid protocol '{protocol}'. Must be 'tcp', 'udp', or 'both'."
            raise ValueError(msg)

        if not binding:
            msg = (
                f"Container port {container_port}/{protocol} not found in exposed ports. "
                f"Available ports: {list(container.ports.keys())}"
            )
            raise RuntimeError(msg)

        resolved_host_port = int(binding[0]["HostPort"])
        resolved_host = self.resolve_service_host(container, container_host)
        service = ServiceContainer(
            container=container,
            host=resolved_host,
            port=resolved_host_port,
        )

        started = time.time()
        if wait_for_log:
            log_bytes = wait_for_log.encode() if isinstance(wait_for_log, str) else wait_for_log
            while time.time() - started < timeout:
                if log_bytes in container.logs():
                    break
                time.sleep(pause)
            else:
                msg = f"Service {service_name!r} failed to come online"
                raise ValueError(msg)

        if check:
            while time.time() - started < timeout:
                if check(service) is True:
                    break
                time.sleep(pause)
            else:
                msg = f"Service {service_name!r} failed to come online"
                raise ValueError(msg)

        if exec_after_start:
            container.exec_run(exec_after_start)

        try:
            yield service
        finally:
            if transient:
                try:
                    container.stop()
                    container.remove(force=True)
                except APIError as exc:
                    if exc.status_code not in {409, 404}:
                        raise


DockerService = ContainerService


@pytest.fixture(scope="session")
def container_runtime(request: pytest.FixtureRequest) -> ContainerRuntimeConfig:
    """Session-scoped container runtime configuration.

    Args:
        request: The pytest fixture request.

    Returns:
        The resolved container runtime configuration.
    """
    cli_choice = request.config.getoption("--container-runtime", default=None)
    ini_choice = request.config.getini("container_runtime") or None
    requested = cli_choice or ini_choice
    return resolve_container_runtime(requested)


@pytest.fixture(scope="session")
def container_client(container_runtime: ContainerRuntimeConfig) -> Generator[DockerClient, None, None]:
    """Session-scoped DockerClient connected to the resolved container runtime.

    Args:
        container_runtime: The resolved runtime configuration.

    Yields:
        A connected DockerClient instance.
    """
    client = container_runtime.create_client()
    try:
        yield client
    finally:
        client.close()


@pytest.fixture(scope="session")
def docker_client(container_client: DockerClient) -> Generator[DockerClient, None, None]:
    """Backward-compatible alias for container_client.

    Args:
        container_client: The active container client.

    Yields:
        The active DockerClient instance.
    """
    yield container_client


@pytest.fixture(scope="session")
def container_service(
    container_client: DockerClient,
    container_runtime: ContainerRuntimeConfig,
    tmp_path_factory: pytest.TempPathFactory,
    request: pytest.FixtureRequest,
) -> Generator[ContainerService, None, None]:
    """Session-scoped container lifecycle and execution manager.

    Args:
        container_client: The active container client.
        container_runtime: The resolved runtime configuration.
        tmp_path_factory: The pytest temporary directory factory.
        request: The pytest fixture request.

    Yields:
        A ContainerService manager instance.
    """
    tmp_path = _get_base_tmp_path(tmp_path_factory)
    with ContainerService(
        client=container_client,
        tmp_path=tmp_path,
        session=request.session,
        runtime_config=container_runtime,
    ) as service:
        yield service


@pytest.fixture(scope="session")
def docker_service(container_service: ContainerService) -> Generator[ContainerService, None, None]:
    """Backward-compatible alias for container_service.

    Args:
        container_service: The active container service.

    Yields:
        The active ContainerService manager instance.
    """
    yield container_service


def _get_base_tmp_path(tmp_path_factory: pytest.TempPathFactory) -> pathlib.Path:
    tmp_path = tmp_path_factory.getbasetemp()
    if get_xdist_worker_id() is not None:
        tmp_path = tmp_path.parent
    return tmp_path


def _get_ctrl_file(session: pytest.Session) -> pathlib.Path:
    tmp_path_factory: pytest.TempPathFactory = session.config._tmp_path_factory
    tmp_path = _get_base_tmp_path(tmp_path_factory)
    return tmp_path / "ctrl"


@pytest.hookimpl(wrapper=True)
def pytest_sessionfinish(session: pytest.Session, exitstatus: int) -> Generator[Any, Any, Any]:
    """Tear down all managed containers on root process completion.

    Args:
        session: The completing pytest session.
        exitstatus: The process exit status code.

    Yields:
        Control to the wrapped hook implementations.
    """
    try:
        return (yield)
    finally:
        if not hasattr(session.config, "workerinput") and _get_ctrl_file(session).exists():
            _stop_all_containers(get_docker_client())
