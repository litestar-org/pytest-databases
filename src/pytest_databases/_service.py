from __future__ import annotations

import json
import multiprocessing
import os
import pathlib
import subprocess
import time
from contextlib import AbstractContextManager, contextmanager
from typing import Callable, Generator, Any

import docker
import filelock
import pytest
from docker.models.containers import Container

from pytest_databases.helpers import get_xdist_worker_id
from pytest_databases.types import ServiceContainer


def get_docker_host() -> str:
    result = subprocess.run(
        ["docker", "context", "ls", "--format=json"],
        text=True,
        capture_output=True,
        check=True,
    )
    contexts = (json.loads(l) for l in result.stdout.splitlines())
    return next(context["DockerEndpoint"] for context in contexts if context["Current"] is True)


def get_docker_client() -> docker.DockerClient:
    env = {**os.environ}
    if "DOCKER_HOST" not in env:
        env["DOCKER_HOST"] = get_docker_host()
    return docker.DockerClient.from_env(environment=env)


class DockerService(AbstractContextManager):
    def __init__(
        self,
        client: docker.DockerClient,
        tmp_path: pathlib.Path,
        session: pytest.Session,
    ) -> None:
        self._client = client
        self._tmp_path = tmp_path
        self._daemon_proc: multiprocessing.Process | None = None
        self._session = session
        self._is_xdist = get_xdist_worker_id() is not None

    def _daemon(self):
        while (self._tmp_path / "ctrl").exists():
            time.sleep(0.1)
        self._stop_all_containers()

    def __enter__(self) -> DockerService:
        if self._is_xdist:
            with filelock.FileLock(self._tmp_path / "startup.lock"):
                ctrl_file = _get_ctrl_file(self._session)
                if not ctrl_file.exists():
                    ctrl_file.touch()
                    self._stop_all_containers()
                    self._daemon_proc = multiprocessing.Process(
                        target=self._daemon,
                        daemon=True,
                    )
                    self._daemon_proc.start()
        else:
            self._stop_all_containers()
        return self

    def __exit__(self, exc_type, exc_val, exc_tb) -> None:
        if not self._is_xdist:
            self._stop_all_containers()

    def _get_container(self, name: str) -> Container | None:
        containers = self._client.containers.list(
            filters={"name": name},
        )
        if len(containers) > 1:
            raise ValueError(f"More than one running container found")
        if containers:
            return containers[0]
        return None

    def _stop_all_containers(self) -> None:
        containers: list[Container] = self._client.containers.list(all=True, filters={"label": "pytest_databases"})
        for container in containers:
            container.kill()

    @contextmanager
    def run(
        self,
        image: str,
        check: Callable[[ServiceContainer], bool],
        container_port: int,
        name: str,
        env: dict[str, Any] | None,
        exec_after_start: str | list[str] | None = None,
    ) -> Generator[ServiceContainer, None, None]:
        name = f"pytest_databases_{name}"
        with filelock.FileLock(self._tmp_path.joinpath(name).with_suffix(".lock")):
            container = self._get_container(name)
            if container is None:
                container = self._client.containers.run(
                    image,
                    detach=True,
                    remove=True,
                    ports={container_port: None},
                    labels=["pytest_databases"],
                    name=name,
                    environment=env,
                )
                container.reload()

        host_port = int(
            container.ports[next(k for k in container.ports if k.startswith(str(container_port)))][0]["HostPort"]
        )
        service = ServiceContainer(host="127.0.0.1", port=host_port)
        for i in range(10):
            result = check(service)
            if result is True:
                break
            time.sleep(0.1 * i)
        else:
            raise RuntimeError(f"Service {name!r} failed to come online")

        if exec_after_start:
            container.exec_run(exec_after_start)

            yield service


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
    tmp_path = _get_base_tmp_path(session.config._tmp_path_factory)
    return tmp_path / "ctrl"


@pytest.hookimpl(wrapper=True)
def pytest_sessionfinish(session: pytest.Session, exitstatus):
    """Insert teardown that you want to occur only once here"""
    try:
        return (yield)
    finally:
        if get_xdist_worker_id() and not hasattr(session.config, "workerinput"):
            # if we're running on xdist, delete the ctrl file, telling the deamon proc
            # to stop all running containers.
            # when not running on xdist, containers are stopped by the service itself
            ctrl_file = _get_ctrl_file(session)
            ctrl_file.unlink()
