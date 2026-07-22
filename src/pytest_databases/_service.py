from __future__ import annotations

# ruff: noqa: PLW0717
import contextlib
import hashlib
import json
import os
import secrets
import tempfile
import time
from contextlib import AbstractContextManager, contextmanager
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING, Any, Callable

import filelock
import pytest
from docker.errors import APIError, ImageNotFound
from typing_extensions import Self

from pytest_databases.helpers import get_xdist_worker_id
from pytest_databases.runtime import ResolvedRuntime, RuntimeResolutionError, RuntimeType, resolve_container_runtime
from pytest_databases.types import ServiceContainer

if TYPE_CHECKING:
    from collections.abc import Generator
    from types import TracebackType

    from docker.models.containers import Container
    from docker.types import Ulimit

    from docker import DockerClient


OWNER_LABEL = "pytest_databases.owner"
SERVICE_LABEL = "pytest_databases.service"
MANAGED_LABEL = "pytest_databases"
SESSION_STATE_FILE = "pytest-databases-session.json"


@dataclass(frozen=True)
class RuntimeSessionState:
    owner_id: str
    runtime: ResolvedRuntime


def get_docker_host() -> str:
    """Return the endpoint chosen by auto discovery for backward compatibility."""
    return resolve_container_runtime(RuntimeType.AUTO).endpoint


def get_docker_client() -> DockerClient:
    """Create a compatibility client using environment/auto resolution only."""
    return resolve_container_runtime(RuntimeType.AUTO).create_client()


def _stop_owned_containers(client: DockerClient, owner_id: str) -> None:
    containers: list[Container] = client.containers.list(
        all=True,
        filters={"label": f"{OWNER_LABEL}={owner_id}"},
        ignore_removed=True,
    )
    for container in containers:
        # Containers may disappear between the list and the kill/remove call -
        # they are tagged remove=True so they vacate as soon as they stop, and
        # transient teardown can race with this loop. Treat 404 (already gone)
        # and 409 (removal already in progress) as success.
        try:
            if container.status == "running":
                container.kill()
            elif container.status in {"created", "stopped", "dead"}:
                container.remove()
            elif container.status == "removing":
                continue
            else:
                msg = f"Cannot handle container in state {container.status}"
                raise RuntimeError(msg)
        except APIError as exc:
            if exc.status_code not in {404, 409}:
                raise


def _creation_lock_path(
    runtime: ResolvedRuntime,
    *,
    temp_directory: Path | None = None,
    uid: int | None = None,
) -> Path:
    resolved_uid = os.getuid() if uid is None and hasattr(os, "getuid") else (uid or 0)
    identity = f"{runtime.kind.value}\0{runtime.endpoint}\0{resolved_uid}".encode()
    digest = hashlib.sha256(identity).hexdigest()[:20]
    directory = Path(tempfile.gettempdir()) if temp_directory is None else temp_directory
    return directory / f"pytest-databases-create-{digest}.lock"


def _session_state_path(base_tmp_path: Path) -> Path:
    return base_tmp_path / SESSION_STATE_FILE


def _load_session_state(path: Path) -> RuntimeSessionState:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
        runtime = ResolvedRuntime.from_dict(payload["runtime"])
        owner_id = str(payload["owner_id"])
    except (KeyError, OSError, TypeError, ValueError) as error:
        message = f"invalid pytest-databases session state at {path}"
        raise RuntimeResolutionError(message) from error
    return RuntimeSessionState(owner_id=owner_id, runtime=runtime)


def _load_or_create_session_state(
    base_tmp_path: Path,
    requested: RuntimeType | str,
    *,
    resolver: Callable[[RuntimeType | str], ResolvedRuntime] = resolve_container_runtime,
) -> RuntimeSessionState:
    path = _session_state_path(base_tmp_path)
    with filelock.FileLock(path.with_suffix(".lock")):
        if path.exists():
            state = _load_session_state(path)
            requested_type = RuntimeType(requested) if isinstance(requested, str) else requested
            if requested_type is not RuntimeType.AUTO and state.runtime.kind is not requested_type:
                message = (
                    f"pytest session already selected {state.runtime.kind.value}, "
                    f"but a worker requested {requested_type.value}"
                )
                raise RuntimeResolutionError(message)
            return state
        state = RuntimeSessionState(owner_id=secrets.token_hex(16), runtime=resolver(requested))
        descriptor = json.dumps({"owner_id": state.owner_id, "runtime": state.runtime.to_dict()}, sort_keys=True)
        file_descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        with os.fdopen(file_descriptor, "w", encoding="utf-8") as state_file:
            state_file.write(descriptor)
        return state


class ContainerService(AbstractContextManager):
    def __init__(
        self,
        client: DockerClient,
        tmp_path: Path,
        session: pytest.Session,
        owner_id: str,
        runtime: ResolvedRuntime,
    ) -> None:
        self._client = client
        self._tmp_path = tmp_path
        self._session = session
        self._owner_id = owner_id
        self._runtime = runtime
        self._creation_lock = filelock.FileLock(_creation_lock_path(runtime))
        self._is_xdist = get_xdist_worker_id() is not None

    def __enter__(self) -> Self:
        if self._is_xdist:
            ctrl_file = _get_ctrl_file(self._session)
            with filelock.FileLock(ctrl_file.with_suffix(".lock")):
                if not ctrl_file.exists():
                    ctrl_file.touch()
        return self

    def __exit__(
        self,
        /,
        __exc_type: type[BaseException] | None,
        __exc_value: BaseException | None,
        __traceback: TracebackType | None,
    ) -> None:
        if not self._is_xdist:
            self._stop_owned_containers()

    @property
    def owner_id(self) -> str:
        return self._owner_id

    def container_name(self, service_name: str) -> str:
        logical_name = service_name.removeprefix("pytest_databases_")
        return f"pytest_databases_{logical_name}_{self._owner_id[:12]}"

    def container_labels(self, service_name: str) -> dict[str, str]:
        logical_name = service_name.removeprefix("pytest_databases_")
        return {MANAGED_LABEL: "true", OWNER_LABEL: self._owner_id, SERVICE_LABEL: logical_name}

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
        _stop_owned_containers(self._client, self._owner_id)

    def run_container(
        self,
        image: str,
        *args: Any,
        service_name: str,
        **kwargs: Any,
    ) -> Any:
        """Create a managed container inside the daemon-wide port-allocation lock."""
        kwargs["labels"] = self.container_labels(service_name)
        if "name" in kwargs:
            kwargs["name"] = self.container_name(service_name)
        with self._creation_lock:
            return self._client.containers.run(image, *args, **kwargs)

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
        # ``host_port`` is honored only when a new container is created; if an
        # existing container is reused via ``_get_container(name)`` the request
        # is ignored and the existing port mapping wins (gh-131).
        if check is None and wait_for_log is None:
            msg = "Must set at least check or wait_for_log"
            raise ValueError(msg)

        platform_kwarg = {}
        if platform is not None:
            platform_kwarg = {"platform": platform}

        logical_name = name.removeprefix("pytest_databases_")
        container_name = self.container_name(logical_name)
        lock = filelock.FileLock(self._tmp_path / container_name) if self._is_xdist else contextlib.nullcontext()
        with lock:
            container = self._get_container(logical_name)
            try:
                self._client.images.get(image)
            except ImageNotFound:
                # Registries can fail transiently: Docker Hub rate-limits
                # anonymous pulls with 500s, MCR's WAF returns 404s wrapping
                # a block page. Retry a few times before giving up.
                for attempt in range(3):
                    try:
                        self._client.images.pull(*image.rsplit(":", maxsplit=1), **platform_kwarg)  # pyright: ignore[reportCallIssue,reportArgumentType]
                        break
                    except (APIError, ImageNotFound):
                        if attempt == 2:
                            raise
                        time.sleep(2**attempt)

            if container is None:
                container = self.run_container(
                    image,
                    command,
                    service_name=logical_name,
                    detach=True,
                    remove=True,
                    ports={container_port: host_port},  # pyright: ignore[reportArgumentType]
                    name=container_name,
                    environment=env,
                    ulimits=ulimits,
                    mem_limit=mem_limit,
                    shm_size=shm_size,
                    **platform_kwarg,  # pyright: ignore[reportArgumentType]
                )

                # reload the container; sometimes it can take a while before docker
                # spins it up and the metadata becomes available, so we're redoing the
                # check with a small incremental backup here
                for i in range(10):
                    container.reload()
                    if any(v for v in container.ports.values()):
                        break
                    time.sleep(0.1 + (i / 10))
                else:
                    msg = f"Service {logical_name!r} failed to create container"
                    raise ValueError(msg)

        # Get port binding based on protocol configuration
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

        host_port = int(binding[0]["HostPort"])
        service = ServiceContainer(
            container=container,
            host=container_host,
            port=host_port,
        )

        started = time.time()
        if wait_for_log:
            if isinstance(wait_for_log, str):
                wait_for_log = wait_for_log.encode()
            while time.time() - started < timeout:
                if wait_for_log in container.logs():
                    break
                time.sleep(pause)
            else:
                msg = f"Service {logical_name!r} failed to come online"
                raise ValueError(msg)

        if check:
            while time.time() - started < timeout:
                if check(service) is True:
                    break
                time.sleep(pause)
            else:
                msg = f"Service {logical_name!r} failed to come online"
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
                except APIError as exc:  # pyright: ignore[reportAttributeAccessIssue]
                    # '409 - Conflict' means removal is already in progress. this is the
                    # safest way of delaying with it, since the API is a bit borked when it
                    # comes to concurrent requests
                    if exc.status_code not in {409, 404}:
                        raise


DockerService = ContainerService


@pytest.fixture(scope="session")
def container_runtime() -> RuntimeType | str:
    """Select ``auto``, ``docker``, or ``podman`` for this pytest session."""
    return os.environ.get("PYTEST_DATABASES_CONTAINER_RUNTIME", RuntimeType.AUTO.value)


@pytest.fixture(scope="session")
def _runtime_session_state(
    container_runtime: RuntimeType | str,
    tmp_path_factory: pytest.TempPathFactory,
) -> RuntimeSessionState:
    return _load_or_create_session_state(_get_base_tmp_path(tmp_path_factory), container_runtime)


@pytest.fixture(scope="session")
def resolved_container_runtime(_runtime_session_state: RuntimeSessionState) -> ResolvedRuntime:
    """Return the exact transport shared by all workers and controller teardown."""
    return _runtime_session_state.runtime


@pytest.fixture(scope="session")
def container_client(resolved_container_runtime: ResolvedRuntime) -> Generator[DockerClient, None, None]:
    client = resolved_container_runtime.create_client()
    try:
        yield client
    finally:
        client.close()


@pytest.fixture(scope="session")
def docker_client(container_client: DockerClient) -> DockerClient:
    """Backward-compatible alias for :func:`container_client`."""
    return container_client


@pytest.fixture(scope="session")
def container_service(
    container_client: DockerClient,
    _runtime_session_state: RuntimeSessionState,
    tmp_path_factory: pytest.TempPathFactory,
    request: pytest.FixtureRequest,
) -> Generator[ContainerService, None, None]:
    tmp_path = _get_base_tmp_path(tmp_path_factory)
    with ContainerService(
        client=container_client,
        tmp_path=tmp_path,
        session=request.session,
        owner_id=_runtime_session_state.owner_id,
        runtime=_runtime_session_state.runtime,
    ) as service:
        yield service


@pytest.fixture(scope="session")
def docker_service(container_service: ContainerService) -> ContainerService:
    """Backward-compatible alias for :func:`container_service`."""
    return container_service


def _get_base_tmp_path(tmp_path_factory: pytest.TempPathFactory) -> Path:
    tmp_path = tmp_path_factory.getbasetemp()
    if get_xdist_worker_id() is not None:
        tmp_path = tmp_path.parent
    return tmp_path


def _get_ctrl_file(session: pytest.Session) -> Path:
    tmp_path = _get_base_tmp_path(session.config._tmp_path_factory)  # type: ignore[attr-defined]
    return tmp_path / "ctrl"


@pytest.hookimpl(wrapper=True)
def pytest_sessionfinish(session: pytest.Session, exitstatus: int) -> Generator[Any, Any, Any]:
    try:
        return (yield)
    finally:
        if not hasattr(session.config, "workerinput") and _get_ctrl_file(session).exists():
            state_path = _session_state_path(_get_base_tmp_path(session.config._tmp_path_factory))  # type: ignore[attr-defined]
            if state_path.exists():
                state = _load_session_state(state_path)
                client = state.runtime.create_client()
                try:
                    _stop_owned_containers(client, state.owner_id)
                finally:
                    client.close()
