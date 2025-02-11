from __future__ import annotations

import contextlib
import json
import os
import subprocess  # noqa: S404
import time
from contextlib import AbstractContextManager, contextmanager
from typing import TYPE_CHECKING, Any, Callable, Generator

import filelock
import pytest
from typing_extensions import Self

import docker
from docker.errors import ImageNotFound
from pytest_databases.helpers import get_xdist_worker_id
from pytest_databases.types import ServiceContainer

if TYPE_CHECKING:
    import pathlib
    from types import TracebackType

    from docker.models.containers import Container
    from docker.types import Ulimit


def get_docker_host() -> str:
    result = subprocess.run(
        ["docker", "context", "ls", "--format=json"],  # noqa: S607
        text=True,
        capture_output=True,
        check=True,
    )
    docker_ls = result.stdout.splitlines()
    # if this is empty, we are not in a dockerized environment; It's probably a podman environment on linux
    if not docker_ls or (len(docker_ls) == 1 and docker_ls[0] == "[]"):
        uid_result = subprocess.run(
            ["id", "-u"],  # noqa: S607
            text=True,
            capture_output=True,
            check=True,
        )
        uid = uid_result.stdout.strip()
        return f"unix:///run/user/{uid}/podman/podman.sock"
    contexts = (json.loads(line) for line in docker_ls)
    return next(context["DockerEndpoint"] for context in contexts if context["Current"] is True)


def get_docker_client() -> docker.DockerClient:
    env = {**os.environ}
    if "DOCKER_HOST" not in env:
        env["DOCKER_HOST"] = get_docker_host()
    return docker.DockerClient.from_env(environment=env)


def _stop_all_containers(client: docker.DockerClient) -> None:
    containers: list[Container] = client.containers.list(
        all=True,
        filters={"label": "pytest_databases"},
        ignore_removed=True,
    )
    for container in containers:
        if container.status == "running":
            container.kill()
        elif container.status in {"stopped", "dead"}:
            container.remove()
        elif container.status == "removing":
            continue
        else:
            msg = f"Cannot handle container in state {container.status}"
            raise RuntimeError(msg)


class DockerService(AbstractContextManager):
    def __init__(
        self,
        client: docker.DockerClient,
        tmp_path: pathlib.Path,
        session: pytest.Session,
    ) -> None:
        self._client = client
        self._tmp_path = tmp_path
        self._session = session
        self._is_xdist = get_xdist_worker_id() is not None

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

    @contextmanager
    def run(
        self,
        image: str,
        container_port: int,
        name: str,
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
    ) -> Generator[ServiceContainer, None, None]:
        if check is None and wait_for_log is None:
            msg = "Must set at least check or wait_for_log"
            raise ValueError(msg)

        name = f"pytest_databases_{name}"
        lock = filelock.FileLock(self._tmp_path / name) if self._is_xdist else contextlib.nullcontext()

        with lock:
            container = self._get_container(name)
            try:
                self._client.images.get(image)
            except ImageNotFound:
                self._client.images.pull(*image.rsplit(":", maxsplit=1))  # pyright: ignore[reportCallIssue,reportArgumentType]

            if container is None:
                container = self._client.containers.run(  # pyright: ignore[reportCallIssue,reportArgumentType]
                    image,
                    command,
                    detach=True,
                    remove=True,
                    ports={container_port: None},  # pyright: ignore[reportArgumentType]
                    labels=["pytest_databases"],
                    name=name,
                    environment=env,
                    ulimits=ulimits,
                    mem_limit=mem_limit,
                )

                # reload the container; sometimes it can take a while before docker
                # spins it up and the metadata becomes available, so we're redoing the
                # check with a small incremental backup here
                for i in range(10):
                    if any(v for v in container.ports.values()):
                        break
                    container.reload()
                    time.sleep(0.1 + (i / 10))
                else:
                    msg = f"Service {name!r} failed to create container"
                    raise ValueError(msg)

        host_port = int(
            container.ports[next(k for k in container.ports if k.startswith(str(container_port)))][0]["HostPort"]
        )
        service = ServiceContainer(
            host="127.0.0.1",
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
                msg = f"Service {name!r} failed to come online"
                raise ValueError(msg)

        if check:
            while time.time() - started < timeout:
                if check(service) is True:
                    break
                time.sleep(pause)
            else:
                msg = f"Service {name!r} failed to come online"
                raise ValueError(msg)

        if exec_after_start:
            container.exec_run(exec_after_start)

        yield service

        if transient:
            try:
                container.stop()
                container.remove(force=True)
            except docker.errors.APIError as exc:  # pyright: ignore[reportAttributeAccessIssue]
                # '409 - Conflict' means removal is already in progress. this is the
                # safest way of delaiyng with it, since the API is a bit borked when it
                # comes to concurrent requests
                if exc.status_code not in {409, 404}:
                    raise


@pytest.fixture(scope="session")
def docker_client() -> Generator[docker.DockerClient, None, None]:
    client = get_docker_client()
    try:
        yield client
    finally:
        client.close()


@pytest.fixture(scope="session")
def docker_service(
    docker_client: docker.DockerClient,
    tmp_path_factory: pytest.TempPathFactory,
    request: pytest.FixtureRequest,
) -> Generator[DockerService, None, None]:
    tmp_path = _get_base_tmp_path(tmp_path_factory)
    with DockerService(
        client=docker_client,
        tmp_path=tmp_path,
        session=request.session,
    ) as service:
        yield service


def _get_base_tmp_path(tmp_path_factory: pytest.TempPathFactory) -> pathlib.Path:
    tmp_path = tmp_path_factory.getbasetemp()
    if get_xdist_worker_id() is not None:
        tmp_path = tmp_path.parent
    return tmp_path


def _get_ctrl_file(session: pytest.Session) -> pathlib.Path:
    tmp_path = _get_base_tmp_path(session.config._tmp_path_factory)  # type: ignore[attr-defined]
    return tmp_path / "ctrl"


@pytest.hookimpl(wrapper=True)
def pytest_sessionfinish(session: pytest.Session, exitstatus: int) -> Generator[Any, Any, Any]:
    try:
        return (yield)
    finally:
        if not hasattr(session.config, "workerinput") and _get_ctrl_file(session).exists():
            # if we're running on xdist, delete the ctrl file, telling the deamon proc
            # to stop all running containers.
            # when not running on xdist, containers are stopped by the service itself
            _stop_all_containers(get_docker_client())
