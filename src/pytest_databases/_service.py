"""Container lifecycle and service orchestration for test databases."""

from __future__ import annotations

import atexit
import contextlib
import hashlib
import os
import re
import time
from contextlib import AbstractContextManager, contextmanager
from pathlib import Path
from typing import TYPE_CHECKING, Any

import filelock
import pytest
from docker.errors import APIError, DockerException, ImageNotFound
from typing_extensions import Self

from pytest_databases.helpers import get_xdist_worker_id
from pytest_databases.runtime import (
    ContainerRuntimeConfig,
    default_host_from_base_url,
    resolve_container_runtime,
)
from pytest_databases.types import ServiceContainer

if TYPE_CHECKING:
    from collections.abc import Callable, Generator
    from types import TracebackType

    from docker import DockerClient
    from docker.models.containers import Container
    from docker.types import Ulimit

__all__ = (
    "MANAGED_LABEL",
    "OWNER_LABEL",
    "SERVICE_LABEL",
    "ContainerService",
    "DockerService",
    "container_client",
    "container_runtime",
    "container_service",
    "derive_session_owner_id",
    "docker_client",
    "docker_service",
    "get_docker_client",
    "get_docker_host",
    "pytest_addoption",
    "pytest_sessionfinish",
    "should_keep_containers",
    "stop_all_containers",
    "stop_owned_containers",
    "wait_for_container_health",
)

OWNER_LABEL = "pytest_databases.owner"
SERVICE_LABEL = "pytest_databases.service"
MANAGED_LABEL = "pytest_databases"
_REGISTERED_ATEXIT_OWNERS: set[str] = set()
_COMPLETED_SESSION_OWNERS: set[str] = set()


class ContainerService(AbstractContextManager):
    """Manager for ephemeral test database containers."""

    def __init__(
        self,
        client: DockerClient,
        tmp_path: Path,
        session: pytest.Session,
        runtime_config: ContainerRuntimeConfig | None = None,
        owner_id: str | None = None,
    ) -> None:
        self._client = client
        self._tmp_path = tmp_path
        self._session = session
        self._is_xdist = get_xdist_worker_id() is not None
        self._runtime_config = runtime_config
        rootpath: Path = getattr(session.config, "rootpath", Path.cwd())
        self._owner_id = owner_id if owner_id is not None else derive_session_owner_id(rootpath)

    @property
    def owner_id(self) -> str:
        """Deterministic session owner identifier."""
        return self._owner_id

    def container_name(self, service_name: str) -> str:
        """Generate a session-scoped container name.

        Args:
            service_name: The logical service identifier.

        Returns:
            A unique container name scoped by owner.
        """
        logical_name = service_name.removeprefix("pytest_databases_")
        return f"pytest_databases_{logical_name}_{self._owner_id}"

    def container_labels(self, service_name: str) -> dict[str, str]:
        """Generate metadata labels including ownership for container tracking.

        Args:
            service_name: The logical service identifier.

        Returns:
            Dictionary of container metadata labels.
        """
        logical_name = service_name.removeprefix("pytest_databases_")
        return {
            MANAGED_LABEL: "true",
            OWNER_LABEL: self._owner_id,
            SERVICE_LABEL: logical_name,
        }

    def __enter__(self) -> Self:
        _COMPLETED_SESSION_OWNERS.discard(self._owner_id)
        ctrl_file = _get_ctrl_file(self._session)
        keep = should_keep_containers(getattr(self._session, "config", None))
        if self._is_xdist:
            with filelock.FileLock(ctrl_file.with_suffix(".lock")):
                if not ctrl_file.exists():
                    ctrl_file.touch()
                    if not keep:
                        self._stop_owned_containers()
        else:
            ctrl_file.touch()
            if not keep:
                self._stop_owned_containers()
            _register_atexit_cleanup(
                self._owner_id,
                self._runtime_config,
                getattr(self._session, "config", None),
            )
        return self

    def __exit__(
        self,
        /,
        __exc_type: type[BaseException] | None,
        __exc_value: BaseException | None,
        __traceback: TracebackType | None,
    ) -> None:
        if not self._is_xdist and not should_keep_containers(getattr(self._session, "config", None)):
            self._stop_owned_containers()
            _COMPLETED_SESSION_OWNERS.add(self._owner_id)

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
    def resolve_port(
        container: Container,
        container_port: int,
        protocol: str = "tcp",
    ) -> int:
        """Extract the bound host port for a given container port and protocol.

        Args:
            container: The container instance.
            container_port: Internal container port number.
            protocol: Communication protocol (tcp, udp, or both).

        Returns:
            The host port integer.
        """
        container.reload()
        return _resolve_binding(container, container_port, protocol)

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

    def run_container(
        self,
        image: str,
        *args: Any,
        service_name: str,
        **kwargs: Any,
    ) -> Any:
        """Create a managed container with session ownership labels.

        Args:
            image: The container image to run.
            *args: Positional arguments forwarded to containers.run.
            service_name: The logical service identifier.
            **kwargs: Keyword arguments forwarded to containers.run.

        Returns:
            The created container instance.
        """
        kwargs["labels"] = self.container_labels(service_name)
        if "name" not in kwargs or not kwargs["name"]:
            kwargs["name"] = self.container_name(service_name)

        ports = kwargs.get("ports")
        has_dynamic_port = False
        if isinstance(ports, dict):
            has_dynamic_port = any(v is None for v in ports.values())

        if not has_dynamic_port:
            return self._client.containers.run(image, *args, **kwargs)

        container_name = kwargs["name"]
        for attempt in range(3):
            try:
                return self._client.containers.run(image, *args, **kwargs)
            except APIError as exc:
                err_msg = str(exc).lower()
                is_port_in_use = "address already in use" in err_msg or "portmanager.addport" in err_msg
                if not is_port_in_use or attempt == 2:
                    raise
                try:
                    failed_c = self._client.containers.get(container_name)
                    failed_c.remove(force=True)
                except APIError:
                    pass
                time.sleep(0.05 * (attempt + 1))

        msg = f"Failed to run container for service {service_name!r} after retries"
        raise RuntimeError(msg)

    @contextmanager
    def run(
        self,
        image: str,
        container_port: int,
        name: str,
        container_host: str = "127.0.0.1",
        command: str | list[str] | None = None,
        env: dict[str, Any] | None = None,
        exec_after_start: str | list[str] | None = None,
        check: Callable[[ServiceContainer], bool] | None = None,
        wait_for_log: str | bytes | None = None,
        timeout: int = 10,
        pause: float = 0.1,
        transient: bool = False,
        ulimits: list[Ulimit] | None = None,
        shm_size: int | str | None = None,
        mem_limit: str | None = None,
        platform: str | None = None,
        protocol: str = "tcp",
        host_port: int | None = None,
        extra_ports: dict[int, int | None] | None = None,
        *,
        wait_for_health: bool = False,
        entrypoint: str | list[str] | None = None,
        privileged: bool = False,
        ipc_mode: str | None = None,
        cap_add: list[str] | None = None,
        devices: list[str] | None = None,
        hostname: str | None = None,
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
            shm_size: Shared memory size in bytes or size string.
            mem_limit: Memory limit string.
            platform: Target container platform.
            protocol: Port protocol (tcp, udp, or both).
            host_port: Optional fixed host port binding.
            extra_ports: Additional internal-to-host port mappings to expose.
            wait_for_health: Whether to poll native container health status until healthy.
            entrypoint: Optional container entrypoint override.
            privileged: Whether to run the container in privileged mode.
            ipc_mode: Optional IPC namespace mode (for example ``"host"``).
            cap_add: Optional list of Linux capabilities to add (for example ``["SYS_ADMIN"]``).
            devices: Optional list of host device mappings (for example ``["/dev/fuse"]``).
            hostname: Optional container hostname override.

        Yields:
            A ServiceContainer handle with host and port bindings.
        """
        if check is None and wait_for_log is None and not wait_for_health:
            msg = "Must set at least check, wait_for_log, or wait_for_health"
            raise ValueError(msg)

        platform_kwarg: dict[str, Any] = {}
        if platform is not None:
            platform_kwarg["platform"] = platform

        extra_run_kwargs: dict[str, Any] = {}
        if shm_size is not None:
            extra_run_kwargs["shm_size"] = shm_size
        if entrypoint is not None:
            extra_run_kwargs["entrypoint"] = entrypoint
        if privileged:
            extra_run_kwargs["privileged"] = True
        if ipc_mode is not None:
            extra_run_kwargs["ipc_mode"] = ipc_mode
        if cap_add is not None:
            extra_run_kwargs["cap_add"] = cap_add
        if devices is not None:
            extra_run_kwargs["devices"] = devices
        if hostname is not None:
            extra_run_kwargs["hostname"] = hostname

        service_name = f"pytest_databases_{name}"
        scoped_container_name = self.container_name(service_name)
        labels = self.container_labels(service_name)
        lock = (
            filelock.FileLock(self._tmp_path / f"{service_name}.lock") if self._is_xdist else contextlib.nullcontext()
        )
        with lock:
            container = self._get_container(service_name)
            _ensure_image(self._client, image, platform_kwarg)

            if container is None:
                ports_dict: dict[Any, Any] = {container_port: host_port}
                if extra_ports:
                    ports_dict.update(extra_ports)
                for attempt in range(3):
                    try:
                        container = self._client.containers.run(
                            image,
                            command,
                            detach=True,
                            remove=True,
                            ports=ports_dict,
                            labels=labels,
                            name=scoped_container_name,
                            environment=env,
                            ulimits=ulimits,
                            mem_limit=mem_limit,
                            **platform_kwarg,
                            **extra_run_kwargs,
                        )
                        break
                    except APIError as exc:
                        err_msg = str(exc).lower()
                        is_port_in_use = "address already in use" in err_msg or "portmanager.addport" in err_msg
                        if host_port is not None or not is_port_in_use or attempt == 2:
                            raise
                        try:
                            failed_c = self._client.containers.get(scoped_container_name)
                            failed_c.remove(force=True)
                        except APIError:
                            pass
                        time.sleep(0.05 * (attempt + 1))

                if container is None:
                    msg = f"Service {service_name!r} failed to create container"
                    raise ValueError(msg)

                for i in range(10):
                    _check_container_alive(container, service_name)
                    container.reload()
                    if any(v for v in container.ports.values()):
                        break
                    time.sleep(0.1 + (i / 10))
                else:
                    _check_container_alive(container, service_name)
                    msg = f"Service {service_name!r} failed to create container"
                    raise ValueError(msg)
            else:
                container.reload()

        if container is None:
            msg = f"Service {service_name!r} failed to create container"
            raise ValueError(msg)

        host_port_val = _resolve_binding(container, container_port, protocol)
        resolved_host = self.resolve_service_host(container, container_host)
        service = ServiceContainer(
            container=container,
            host=resolved_host,
            port=host_port_val,
        )

        _wait_for_readiness(
            service,
            service_name,
            wait_for_log,
            check,
            timeout,
            pause,
            wait_for_health=wait_for_health,
        )

        if exec_after_start:
            container.exec_run(exec_after_start)

        try:
            yield service
        finally:
            if transient and not should_keep_containers(getattr(self._session, "config", None)):
                try:
                    container.stop()
                    container.remove(force=True)
                except APIError as exc:
                    if exc.status_code not in {409, 404}:
                        raise

    def _get_container(self, name: str) -> Container | None:
        logical_name = name.removeprefix("pytest_databases_")
        containers = self._client.containers.list(
            filters={
                "label": [
                    f"{MANAGED_LABEL}=true",
                    f"{OWNER_LABEL}={self._owner_id}",
                    f"{SERVICE_LABEL}={logical_name}",
                ]
            },
            ignore_removed=True,
        )
        if len(containers) > 1:
            msg = "More than one running container found"
            raise ValueError(msg)
        if containers:
            return containers[0]
        return None

    def _stop_owned_containers(self) -> None:
        stop_owned_containers(self._client, self._owner_id)

    def _stop_all_containers(self) -> None:
        stop_all_containers(self._client)


DockerService = ContainerService


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
    parser.addoption(
        "--keep-containers",
        action="store_true",
        default=False,
        help="Keep database containers running after the pytest session finishes.",
    )
    parser.addini(
        "container_runtime",
        help="Default container runtime (auto, docker, podman).",
        default=None,
    )


def should_keep_containers(config: Any = None) -> bool:
    """Determine whether session-managed containers should be retained on exit.

    Args:
        config: Optional pytest Config object to inspect for ``--keep-containers``.

    Returns:
        ``True`` if ``PYTEST_DATABASES_KEEP_CONTAINERS`` or ``--keep-containers`` is active.
    """
    env_val = os.getenv("PYTEST_DATABASES_KEEP_CONTAINERS", "").strip().lower()
    if env_val in {"1", "true", "yes"}:
        return True
    if config is not None and hasattr(config, "getoption"):
        try:
            return config.getoption("--keep-containers", default=False) is True
        except (ValueError, AttributeError):
            return False
    return False


def derive_session_owner_id(rootpath: Path, namespace: str | None = None) -> str:
    """Derive a deterministic container owner ID for a pytest rootpath and optional namespace.

    Args:
        rootpath: Root path of the pytest project session.
        namespace: Optional namespace override or suffix.

    Returns:
        A deterministic session identifier.
    """
    resolved = str(rootpath.resolve())
    digest = hashlib.sha256(resolved.encode("utf-8")).hexdigest()[:12]
    raw_namespace = namespace if namespace is not None else os.getenv("PYTEST_DATABASES_NAMESPACE")
    if raw_namespace:
        clean_ns = re.sub(r"[^a-z0-9_]+", "_", raw_namespace.lower()).strip("_")[:16]
        if clean_ns:
            return f"{digest}_{clean_ns}"
    return digest


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


def stop_owned_containers(client: DockerClient, owner_id: str) -> None:
    """Stop all containers owned by a specific session owner ID.

    Args:
        client: The Docker client to issue stop and remove calls against.
        owner_id: The session owner identifier.
    """
    containers: list[Container] = client.containers.list(
        all=True,
        filters={"label": f"{OWNER_LABEL}={owner_id}"},
        ignore_removed=True,
    )
    for container in containers:
        try:
            _stop_single_container(container)
        except APIError as exc:
            if exc.status_code not in {404, 409}:
                raise


def stop_all_containers(client: DockerClient) -> None:
    """Stop all containers managed by pytest_databases.

    Args:
        client: The Docker client to issue stop and remove calls against.
    """
    containers: list[Container] = client.containers.list(
        all=True,
        filters={"label": MANAGED_LABEL},
        ignore_removed=True,
    )
    for container in containers:
        try:
            _stop_single_container(container)
        except APIError as exc:
            if exc.status_code not in {404, 409}:
                raise


def wait_for_container_health(
    container: Container,
    service_name: str,
    timeout: int,
    pause: float,
) -> None:
    """Poll native Docker or Podman ``State.Health.Status`` until ``healthy``.

    Args:
        container: The container instance to inspect.
        service_name: Service identifier for error messages.
        timeout: Maximum wait time in seconds.
        pause: Sleep interval between polling attempts.

    Raises:
        RuntimeError: If the container reports ``unhealthy``, exits, or times out.
    """
    started = time.time()
    last_status = "unknown"
    last_health: dict[str, Any] = {}
    while time.time() - started < timeout:
        _check_container_alive(container, service_name)
        attrs = getattr(container, "attrs", None)
        state = attrs.get("State", {}) if isinstance(attrs, dict) else {}
        health = state.get("Health") if isinstance(state, dict) else None
        if isinstance(health, dict):
            last_health = health
            status = str(health.get("Status", "unknown"))
            last_status = status
            if status == "healthy":
                return
            if status == "unhealthy":
                msg = (
                    f"Service {service_name!r} container became unhealthy.\n"
                    f"Healthcheck logs:\n{_format_health_log(health)}"
                )
                raise RuntimeError(msg)
        time.sleep(pause)

    msg = (
        f"Service {service_name!r} container healthcheck did not become healthy within {timeout}s "
        f"(last status: {last_status!r}).\n"
        f"Healthcheck logs:\n{_format_health_log(last_health)}"
    )
    raise RuntimeError(msg)


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
        if (
            not hasattr(session.config, "workerinput")
            and _get_ctrl_file(session).exists()
            and not should_keep_containers(session.config)
        ):
            rootpath: Path = getattr(session.config, "rootpath", Path.cwd())
            owner_id = derive_session_owner_id(rootpath)
            cli_choice = session.config.getoption("--container-runtime", default=None)
            ini_choice = session.config.getini("container_runtime") or None
            client = resolve_container_runtime(cli_choice or ini_choice).create_client()
            try:
                stop_owned_containers(client, owner_id)
                _COMPLETED_SESSION_OWNERS.add(owner_id)
            finally:
                client.close()


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


def _ensure_image(client: DockerClient, image: str, platform_kwarg: dict[str, Any]) -> None:
    """Ensure image is present locally, pulling if missing with retry.

    Args:
        client: DockerClient to use for querying and pulling.
        image: Image tag string.
        platform_kwarg: Platform keyword arguments.
    """
    try:
        client.images.get(image)
    except ImageNotFound:
        for attempt in range(3):
            try:
                image_name, *tag = image.rsplit(":", maxsplit=1)
                image_tag = tag[0] if tag else None
                client.images.pull(image_name, tag=image_tag, **platform_kwarg)
                break
            except (APIError, ImageNotFound):
                if attempt == 2:
                    raise
                time.sleep(2**attempt)


def _resolve_binding(container: Container, container_port: int, protocol: str) -> int:
    """Extract the bound host port for a given container port and protocol.

    Args:
        container: The container instance.
        container_port: Internal port number.
        protocol: Communication protocol.

    Returns:
        The host port integer.
    """
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
    return int(binding[0]["HostPort"])


def _check_container_alive(container: Container, service_name: str) -> None:
    """Verify that the container has not exited prematurely during startup.

    Args:
        container: The container instance being polled.
        service_name: Name of the service for diagnostic error reporting.

    Raises:
        RuntimeError: If the container has exited or is dead.
    """
    try:
        container.reload()
    except (DockerException, OSError, AttributeError):
        return
    status = getattr(container, "status", None)
    if not status:
        state = getattr(container, "attrs", {}).get("State", {})
        status = state.get("Status")
    if status in {"exited", "dead"}:
        try:
            logs = container.logs(tail=50)
            log_preview = (
                logs.decode("utf-8", errors="replace").strip() if isinstance(logs, bytes) else str(logs).strip()
            )
        except (DockerException, OSError, AttributeError):
            log_preview = "<no logs available>"
        msg = (
            f"Service {service_name!r} container exited prematurely with status {status!r}.\n"
            f"Container logs (tail 50 lines):\n{log_preview}"
        )
        raise RuntimeError(msg)


def _format_health_log(health: dict[str, Any]) -> str:
    """Format the most recent container healthcheck log entries for diagnostics."""
    log_entries = health.get("Log")
    if not isinstance(log_entries, list) or not log_entries:
        return "<no healthcheck logs available>"
    formatted: list[str] = []
    for entry in log_entries[-5:]:
        if isinstance(entry, dict):
            code = entry.get("ExitCode", "?")
            output = str(entry.get("Output", "")).strip()
            formatted.append(f"[exit={code}] {output}")
    return "\n".join(formatted) if formatted else "<no healthcheck logs available>"


def _wait_for_readiness(
    service: ServiceContainer,
    service_name: str,
    wait_for_log: str | bytes | None,
    check: Callable[[ServiceContainer], bool] | None,
    timeout: int,
    pause: float,
    *,
    wait_for_health: bool = False,
) -> None:
    """Wait until a service passes its native healthcheck, log check, and check callable.

    Args:
        service: The service container instance.
        service_name: Name of the service.
        wait_for_log: Log message to await.
        check: Callable readiness check.
        timeout: Maximum seconds to wait.
        pause: Seconds between polling attempts.
        wait_for_health: Whether to poll native container health status first.
    """
    started = time.time()
    if wait_for_health:
        wait_for_container_health(
            service.container,
            service_name,
            timeout=timeout,
            pause=pause,
        )

    if wait_for_log:
        log_bytes = wait_for_log.encode() if isinstance(wait_for_log, str) else wait_for_log
        while time.time() - started < timeout:
            _check_container_alive(service.container, service_name)
            if log_bytes in service.container.logs():
                break
            time.sleep(pause)
        else:
            msg = f"Service {service_name!r} failed to come online"
            raise ValueError(msg)

    if check:
        while time.time() - started < timeout:
            _check_container_alive(service.container, service_name)
            if check(service) is True:
                break
            time.sleep(pause)
        else:
            msg = f"Service {service_name!r} failed to come online"
            raise ValueError(msg)


def _register_atexit_cleanup(
    owner_id: str,
    runtime_config: ContainerRuntimeConfig | None,
    session_config: Any,
) -> None:
    """Register an atexit fallback on the controller process to clean up owned containers."""
    if owner_id in _REGISTERED_ATEXIT_OWNERS:
        return
    _REGISTERED_ATEXIT_OWNERS.add(owner_id)

    def _cleanup() -> None:
        if owner_id in _COMPLETED_SESSION_OWNERS or should_keep_containers(session_config):
            return
        with contextlib.suppress(Exception):
            client = runtime_config.create_client() if runtime_config is not None else get_docker_client()
            try:
                stop_owned_containers(client, owner_id)
            finally:
                with contextlib.suppress(Exception):
                    client.close()

    atexit.register(_cleanup)


def _get_base_tmp_path(tmp_path_factory: pytest.TempPathFactory) -> Path:
    tmp_path: Path = tmp_path_factory.getbasetemp()
    if get_xdist_worker_id() is not None:
        tmp_path = tmp_path.parent
    return tmp_path


def _get_ctrl_file(session: pytest.Session) -> Path:
    config: Any = session.config
    tmp_path_factory: pytest.TempPathFactory = config._tmp_path_factory
    tmp_path = _get_base_tmp_path(tmp_path_factory)
    return tmp_path / "ctrl"
