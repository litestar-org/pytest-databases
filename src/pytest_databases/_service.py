"""Container lifecycle and service orchestration for test databases."""

from __future__ import annotations

import atexit
import contextlib
import hashlib
import os
import re
import tempfile
import time
import uuid
import warnings
from contextlib import AbstractContextManager, contextmanager
from pathlib import Path
from typing import TYPE_CHECKING, Any, Self

import filelock
import pytest
from docker.errors import APIError, DockerException, ImageNotFound

from pytest_databases.helpers import TRUE_VALUES, exec_output_to_bytes, get_xdist_worker_id
from pytest_databases.runtime import (
    ContainerRuntimeConfig,
    RuntimeResolutionError,
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
    "has_active_owner_sessions",
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
SESSION_LOCK_DIR_ENV = "PYTEST_DATABASES_SESSION_LOCK_DIR"
_RUNTIME_STASH_KEY = pytest.StashKey[ContainerRuntimeConfig]()
_REGISTERED_ATEXIT_RUNS: set[tuple[str, str]] = set()
_COMPLETED_SESSION_RUNS: set[tuple[str, str]] = set()
_ACTIVE_PROCESS_LEASES: dict[tuple[str, str], list[tuple[filelock.BaseFileLock, Path]]] = {}


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
        self._owner_id = owner_id if owner_id is not None else derive_session_owner_id(session.config.rootpath)
        self._run_id = _derive_run_id(tmp_path)
        self._session_lease: filelock.BaseFileLock | None = None
        self._session_lease_path: Path | None = None
        self._executed_after_start: set[tuple[str, str]] = set()

    @property
    def owner_id(self) -> str:
        """Deterministic session owner identifier."""
        return self._owner_id

    @property
    def temp_dir(self) -> Path:
        """Shared session temporary directory used for cross-worker lock files."""
        return self._tmp_path

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
        _COMPLETED_SESSION_RUNS.discard((self._owner_id, self._run_id))
        ctrl_file = _get_ctrl_file(self._session)
        keep = should_keep_containers(self._session.config)
        self._session_lease, self._session_lease_path, other_active = _acquire_session_lease(
            self._owner_id,
            self._run_id,
        )
        if self._is_xdist:
            with filelock.FileLock(ctrl_file.with_suffix(".lock")):
                if not ctrl_file.exists():
                    ctrl_file.write_text(self._owner_id, encoding="utf-8")
                    if not keep and not other_active:
                        self._stop_owned_containers()
        else:
            ctrl_file.write_text(self._owner_id, encoding="utf-8")
            if not keep and not other_active:
                self._stop_owned_containers()
            _register_atexit_cleanup(
                self._owner_id,
                self._run_id,
                self._runtime_config,
                self._session.config,
            )
        return self

    def __exit__(
        self,
        /,
        __exc_type: type[BaseException] | None,
        __exc_value: BaseException | None,
        __traceback: TracebackType | None,
    ) -> None:
        other_active = _release_session_lease(
            self._owner_id,
            self._run_id,
            self._session_lease,
            self._session_lease_path,
        )
        self._session_lease = None
        self._session_lease_path = None
        if not self._is_xdist:
            _COMPLETED_SESSION_RUNS.add((self._owner_id, self._run_id))
            if not should_keep_containers(self._session.config) and not other_active:
                self._stop_owned_containers()

    def resolve_service_host(self, container_host: str = "127.0.0.1") -> str:
        """Resolve the reachable host for container port communication.

        Args:
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
        if not kwargs.get("name"):
            kwargs["name"] = self.container_name(service_name)

        ports = kwargs.get("ports")
        has_dynamic_port = isinstance(ports, dict) and any(v is None for v in ports.values())
        retries = 2 if has_dynamic_port else 0
        for attempt in range(retries):
            try:
                return self._client.containers.run(image, *args, **kwargs)
            except APIError as exc:
                err_msg = str(exc).lower()
                if "address already in use" not in err_msg and "portmanager.addport" not in err_msg:
                    raise
                with contextlib.suppress(APIError):
                    self._client.containers.get(kwargs["name"]).remove(force=True)
                time.sleep(0.05 * (attempt + 1))
        return self._client.containers.run(image, *args, **kwargs)

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
        volumes: dict[str, dict[str, str]] | list[str] | None = None,
        user: str | int | None = None,
        tmpfs: dict[str, str] | None = None,
        extra_hosts: dict[str, str] | None = None,
    ) -> Generator[ServiceContainer, None, None]:
        """Start and manage an ephemeral container service lifecycle.

        Args:
            image: The container image to run.
            container_port: The internal container port to expose.
            name: The service name identifier.
            container_host: The host address to expose.
            command: The command to run in the container.
            env: Environment variables to pass into the container.
            exec_after_start: Command executed once per container after readiness passes.
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
            volumes: Optional host-to-container volume mappings or volume binding specs.
            user: Optional container user or numeric ``uid[:gid]`` override.
            tmpfs: Optional container tmpfs mount mapping (for example ``{"/run": "size=64m"}``).
            extra_hosts: Optional extra ``/etc/hosts`` hostname-to-IP mappings.

        Yields:
            A ServiceContainer handle with host and port bindings.
        """
        if check is None and wait_for_log is None and not wait_for_health:
            msg = "Must set at least check, wait_for_log, or wait_for_health"
            raise ValueError(msg)

        platform_kwarg: dict[str, Any] = {}
        if platform is not None:
            platform_kwarg["platform"] = platform

        extra_run_kwargs = _build_extra_run_kwargs(
            shm_size=shm_size,
            entrypoint=entrypoint,
            privileged=privileged,
            ipc_mode=ipc_mode,
            cap_add=cap_add,
            devices=devices,
            hostname=hostname,
            volumes=volumes,
            user=user,
            tmpfs=tmpfs,
            extra_hosts=extra_hosts,
        )

        service_name = f"pytest_databases_{name}"
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
                container = self.run_container(
                    image,
                    command,
                    service_name=service_name,
                    detach=True,
                    remove=True,
                    ports=ports_dict,
                    environment=env,
                    ulimits=ulimits,
                    mem_limit=mem_limit,
                    **platform_kwarg,
                    **extra_run_kwargs,
                )

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
        resolved_host = self.resolve_service_host(container_host)
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
            self._run_exec_after_start(container, service_name, exec_after_start, transient=transient)

        try:
            yield service
        finally:
            if transient and not should_keep_containers(self._session.config):
                try:
                    container.stop()
                    container.remove(force=True)
                except APIError as exc:
                    if exc.status_code not in {409, 404}:
                        raise

    def _run_exec_after_start(
        self,
        container: Container,
        service_name: str,
        command: str | list[str],
        *,
        transient: bool,
    ) -> None:
        """Execute ``exec_after_start`` at most once per shared container under lock."""
        raw_id = getattr(container, "id", None)
        raw_token = raw_id[:12] if isinstance(raw_id, str) and raw_id else f"obj{id(container):x}"
        container_token = re.sub(r"[^a-zA-Z0-9_.-]+", "_", raw_token)
        key = (service_name, container_token)

        if self._is_xdist:
            safe_service = re.sub(r"[^a-zA-Z0-9_.-]+", "_", service_name)
            marker_stem = f"{safe_service}_{container_token}.after_start"
            lock_path = self._tmp_path / f"{marker_stem}.lock"
            done_path = self._tmp_path / f"{marker_stem}.done"
            lock_path.parent.mkdir(parents=True, exist_ok=True)
            with filelock.FileLock(lock_path):
                if done_path.exists():
                    return
                _invoke_exec_after_start(container, service_name, command)
                if not transient:
                    done_path.write_text("1", encoding="utf-8")
            return

        if not transient and key in self._executed_after_start:
            return
        _invoke_exec_after_start(container, service_name, command)
        if not transient:
            self._executed_after_start.add(key)

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


def should_keep_containers(config: pytest.Config | None = None) -> bool:
    """Determine whether session-managed containers should be retained on exit.

    Args:
        config: Optional pytest configuration to inspect for ``--keep-containers``.

    Returns:
        ``True`` if ``PYTEST_DATABASES_KEEP_CONTAINERS`` is set to a truthy value or ``--keep-containers`` is active.
    """
    if os.getenv("PYTEST_DATABASES_KEEP_CONTAINERS", "").strip() in TRUE_VALUES:
        return True
    return config is not None and config.getoption("--keep-containers", default=False) is True


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


def has_active_owner_sessions(owner_id: str, *, exclude_run_id: str | None = None) -> bool:
    """Return whether any live pytest session currently holds an active lease for ``owner_id``.

    Stale lease files left behind by crashed or ``SIGKILL``ed processes are unlocked automatically by the operating
    system kernel and swept during the probe.

    Args:
        owner_id: Deterministic session owner identifier.
        exclude_run_id: Optional session run identifier to exclude (for example the caller's own session).

    Returns:
        ``True`` if at least one live external session holds an active lease for ``owner_id``.
    """
    session_dir = _session_lock_dir(owner_id)
    if not session_dir.exists():
        return False
    session_dir.mkdir(parents=True, exist_ok=True)
    with filelock.FileLock(session_dir / ".coord.lock"):
        return _sweep_and_detect_active_leases(session_dir, exclude_run_id=exclude_run_id)


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
        RuntimeError: If the image has no ``HEALTHCHECK``, or the container reports ``unhealthy``, exits, or
            times out.
    """
    started = time.time()
    last_status = "unknown"
    last_health: dict[str, Any] = {}
    while time.time() - started < timeout:
        _check_container_alive(container, service_name)
        health = container.attrs.get("State", {}).get("Health")
        if not health:
            msg = (
                f"Service {service_name!r} was started with wait_for_health=True, but image "
                f"{container.attrs.get('Config', {}).get('Image', '<unknown>')!r} defines no HEALTHCHECK."
            )
            raise RuntimeError(msg)
        last_health = health
        last_status = str(health.get("Status", "unknown"))
        if last_status == "healthy":
            return
        if last_status == "unhealthy":
            msg = (
                f"Service {service_name!r} container became unhealthy.\nHealthcheck logs:\n{_format_health_log(health)}"
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
    runtime = resolve_container_runtime(_requested_runtime(request.config))
    request.config.stash[_RUNTIME_STASH_KEY] = runtime
    return runtime


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
        ctrl_file = _get_ctrl_file(session)
        if (
            not hasattr(session.config, "workerinput")
            and ctrl_file.exists()
            and not should_keep_containers(session.config)
        ):
            _cleanup_session_containers(session, ctrl_file)


def _requested_runtime(config: pytest.Config) -> str | None:
    """Return the runtime requested through ``--container-runtime`` or the ``container_runtime`` ini option.

    Args:
        config: The pytest configuration.

    Returns:
        The requested runtime name, or ``None`` for automatic selection.
    """
    return config.getoption("--container-runtime", default=None) or config.getini("container_runtime") or None


def _cleanup_session_containers(session: pytest.Session, ctrl_file: Path) -> None:
    """Stop the containers owned by this session from the controller process.

    The owner recorded in the control file and the runtime already resolved in this process are reused. Under
    ``pytest-xdist`` the controller resolves the runtime itself. When another concurrent pytest session actively holds
    a lease on the same ``owner_id``, container teardown is deferred to the final exiting session. Cleanup failures are
    reported as warnings so they never replace the test session result.

    Args:
        session: The completing pytest session.
        ctrl_file: The session control file written by the first container service.
    """
    owner_id = ctrl_file.read_text(encoding="utf-8").strip() or derive_session_owner_id(session.config.rootpath)
    run_id = _derive_run_id(ctrl_file.parent)
    if has_active_owner_sessions(owner_id, exclude_run_id=run_id):
        _COMPLETED_SESSION_RUNS.add((owner_id, run_id))
        return
    try:
        runtime = session.config.stash.get(_RUNTIME_STASH_KEY, None) or resolve_container_runtime(
            _requested_runtime(session.config)
        )
        client = runtime.create_client()
    except (DockerException, RuntimeResolutionError) as exc:
        warnings.warn(f"pytest-databases could not clean up session containers: {exc}", RuntimeWarning, stacklevel=1)
        return
    try:
        stop_owned_containers(client, owner_id)
        _COMPLETED_SESSION_RUNS.add((owner_id, run_id))
    except DockerException as exc:
        warnings.warn(f"pytest-databases could not clean up session containers: {exc}", RuntimeWarning, stacklevel=1)
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
    except (DockerException, OSError):
        return
    status = container.status
    if status in {"exited", "dead"}:
        try:
            log_preview = container.logs(tail=50).decode("utf-8", errors="replace").strip()
        except (DockerException, OSError):
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
    run_id: str,
    runtime_config: ContainerRuntimeConfig | None,
    session_config: pytest.Config,
) -> None:
    """Register an interpreter-exit fallback that stops this session's containers.

    Registered only when not running under ``pytest-xdist``, where the session's own container service runs in this
    process. It releases any remaining leases held by this run and skips stopping containers when another concurrent
    local session still holds a lease on ``owner_id`` or ``--keep-containers`` is active.

    Args:
        owner_id: Session owner identifier.
        run_id: Session run identifier derived from the session temporary directory.
        runtime_config: Runtime resolved for the session, if any.
        session_config: The pytest configuration.
    """
    run_key = (owner_id, run_id)
    if run_key in _REGISTERED_ATEXIT_RUNS:
        return
    _REGISTERED_ATEXIT_RUNS.add(run_key)

    def _cleanup() -> None:
        _release_all_run_leases(owner_id, run_id)
        if run_key in _COMPLETED_SESSION_RUNS or should_keep_containers(session_config):
            return
        with contextlib.suppress(DockerException, RuntimeResolutionError, OSError):
            if has_active_owner_sessions(owner_id, exclude_run_id=run_id):
                return
            client = runtime_config.create_client() if runtime_config is not None else get_docker_client()
            try:
                stop_owned_containers(client, owner_id)
            finally:
                client.close()

    atexit.register(_cleanup)


def _build_extra_run_kwargs(
    *,
    shm_size: int | str | None,
    entrypoint: str | list[str] | None,
    privileged: bool,
    ipc_mode: str | None,
    cap_add: list[str] | None,
    devices: list[str] | None,
    hostname: str | None,
    volumes: dict[str, dict[str, str]] | list[str] | None,
    user: str | int | None,
    tmpfs: dict[str, str] | None,
    extra_hosts: dict[str, str] | None,
) -> dict[str, Any]:
    """Assemble optional container creation keyword arguments for ``containers.run``."""
    optional_values: tuple[tuple[str, Any], ...] = (
        ("shm_size", shm_size),
        ("entrypoint", entrypoint),
        ("ipc_mode", ipc_mode),
        ("cap_add", cap_add),
        ("devices", devices),
        ("hostname", hostname),
        ("volumes", volumes),
        ("user", user),
        ("tmpfs", tmpfs),
        ("extra_hosts", extra_hosts),
    )
    extra_run_kwargs: dict[str, Any] = {key: value for key, value in optional_values if value is not None}
    if privileged:
        extra_run_kwargs["privileged"] = True
    return extra_run_kwargs


def _invoke_exec_after_start(container: Container, service_name: str, command: str | list[str]) -> None:
    """Execute ``exec_after_start`` and raise ``RuntimeError`` on integer non-zero exit status."""
    result = container.exec_run(command)
    exit_code: object = result[0] if isinstance(result, tuple) else getattr(result, "exit_code", 0)
    if isinstance(exit_code, int) and not isinstance(exit_code, bool) and exit_code != 0:
        raw_output: Any = result[1] if isinstance(result, tuple) else getattr(result, "output", b"")
        detail = (
            exec_output_to_bytes(raw_output).decode("utf-8", errors="replace").strip()
            if isinstance(raw_output, (bytes, str))
            else ""
        )
        msg = f"Service {service_name!r} exec_after_start failed with exit code {exit_code}: {detail}"
        raise RuntimeError(msg)


def _derive_run_id(base_tmp_path: Path) -> str:
    """Compute a deterministic identifier for a single pytest invocation's base temporary directory."""
    return hashlib.sha256(str(base_tmp_path.resolve()).encode("utf-8")).hexdigest()[:12]


def _session_lock_dir(owner_id: str) -> Path:
    """Return the host lock directory tracking concurrent local sessions for ``owner_id``."""
    configured_root = os.getenv(SESSION_LOCK_DIR_ENV)
    root = Path(configured_root) if configured_root else Path(tempfile.gettempdir()) / "pytest_databases_sessions"
    safe_owner = re.sub(r"[^a-zA-Z0-9_.-]+", "_", owner_id)
    return root / safe_owner


def _acquire_session_lease(owner_id: str, run_id: str) -> tuple[filelock.BaseFileLock, Path, bool]:
    """Acquire an OS file-descriptor flock lease for ``(owner_id, run_id)`` and detect peer sessions."""
    session_dir = _session_lock_dir(owner_id)
    session_dir.mkdir(parents=True, exist_ok=True)
    with filelock.FileLock(session_dir / ".coord.lock"):
        other_active = _sweep_and_detect_active_leases(session_dir, exclude_run_id=run_id)
        lease_path = session_dir / f"{run_id}__{os.getpid()}_{uuid.uuid4().hex[:8]}.lease"
        lease_lock: filelock.BaseFileLock = filelock.FileLock(lease_path)
        lease_lock.acquire(timeout=0)
        _ACTIVE_PROCESS_LEASES.setdefault((owner_id, run_id), []).append((lease_lock, lease_path))
        return lease_lock, lease_path, other_active


def _release_session_lease(
    owner_id: str,
    run_id: str,
    lease_lock: filelock.BaseFileLock | None,
    lease_path: Path | None,
) -> bool:
    """Release a session lease and return whether any external session still holds ``owner_id``."""
    session_dir = _session_lock_dir(owner_id)
    session_dir.mkdir(parents=True, exist_ok=True)
    with filelock.FileLock(session_dir / ".coord.lock"):
        if lease_lock is not None and lease_lock.is_locked:
            lease_lock.release()
        if lease_path is not None:
            with contextlib.suppress(OSError):
                lease_path.unlink()
        tracked = _ACTIVE_PROCESS_LEASES.get((owner_id, run_id))
        if tracked is not None:
            _ACTIVE_PROCESS_LEASES[owner_id, run_id] = [
                entry for entry in tracked if entry[1] != lease_path and entry[0].is_locked
            ]
            if not _ACTIVE_PROCESS_LEASES[owner_id, run_id]:
                _ACTIVE_PROCESS_LEASES.pop((owner_id, run_id), None)
        return _sweep_and_detect_active_leases(session_dir, exclude_run_id=run_id)


def _release_all_run_leases(owner_id: str, run_id: str) -> None:
    """Release any unclosed process-local leases recorded for ``(owner_id, run_id)``."""
    tracked = _ACTIVE_PROCESS_LEASES.pop((owner_id, run_id), [])
    if not tracked:
        return
    session_dir = _session_lock_dir(owner_id)
    with contextlib.suppress(OSError), filelock.FileLock(session_dir / ".coord.lock"):
        for lease_lock, lease_path in tracked:
            if lease_lock.is_locked:
                lease_lock.release()
            with contextlib.suppress(OSError):
                lease_path.unlink()


def _sweep_and_detect_active_leases(session_dir: Path, *, exclude_run_id: str | None) -> bool:
    """Sweep stale lease files inside ``session_dir`` and detect active peer session leases.

    Must be called while holding ``session_dir / '.coord.lock'``.
    """
    other_active = False
    excluded_prefix = f"{exclude_run_id}__" if exclude_run_id else None
    for candidate in sorted(session_dir.glob("*.lease")):
        if excluded_prefix is not None and candidate.name.startswith(excluded_prefix):
            continue
        probe = filelock.FileLock(candidate)
        try:
            probe.acquire(timeout=0)
        except filelock.Timeout:
            other_active = True
            continue
        probe.release()
        with contextlib.suppress(OSError):
            candidate.unlink()
    return other_active


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
