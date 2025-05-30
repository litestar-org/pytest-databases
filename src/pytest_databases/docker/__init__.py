from __future__ import annotations

import os
import re
import subprocess  # noqa: S404
import time
import timeit
from contextlib import AbstractContextManager
from typing import TYPE_CHECKING, Any, Callable

from pytest_databases.helpers import simple_string_hash

if TYPE_CHECKING:
    from collections.abc import Awaitable, Generator, Iterable
    from pathlib import Path
    from types import TracebackType

TRUE_VALUES = {"True", "true", "1", "yes", "y", "Y", "T", "on", "enabled", "ok"}


def wait_until_responsive(
    check: Callable[..., bool],
    timeout: float,
    pause: float,
    **kwargs: Any,
) -> None:
    """Wait until a service is responsive.

    Args:
        check: Coroutine, return truthy value when waiting should stop.
        timeout: Maximum seconds to wait.
        pause: Seconds to wait between calls to `check`.
        **kwargs: Given as kwargs to `check`.
    """
    ref = timeit.default_timer()
    now = ref
    while (now - ref) < timeout:  # sourcery skip
        if check(**kwargs):
            return
        time.sleep(pause)
        now = timeit.default_timer()

    msg = "Timeout reached while waiting on service!"
    raise RuntimeError(msg)


SKIP_DOCKER_COMPOSE: bool = os.environ.get("SKIP_DOCKER_COMPOSE", "False") in TRUE_VALUES
USE_LEGACY_DOCKER_COMPOSE: bool = os.environ.get("USE_LEGACY_DOCKER_COMPOSE", "False") in TRUE_VALUES
COMPOSE_PROJECT_NAME: str = f"pytest-databases-{simple_string_hash(__file__)}"


class DockerServiceRegistry(AbstractContextManager):
    def __init__(
        self,
        worker_id: str,
        compose_project_name: str = COMPOSE_PROJECT_NAME,
        before_start: Iterable[Callable[[], Any]] | None = None,
    ) -> None:
        self._running_services: set[str] = set()
        self.docker_ip = self._get_docker_ip()
        self._base_command = ["docker-compose"] if USE_LEGACY_DOCKER_COMPOSE else ["docker", "compose"]
        self._compose_files: list[str] = []
        self._base_command.extend(
            [
                f"--project-name={compose_project_name}-{worker_id}",
            ],
        )
        self._before_start = list(before_start) if before_start else []

    def __exit__(
        self,
        /,
        __exc_type: type[BaseException] | None,
        __exc_value: BaseException | None,
        __traceback: TracebackType | None,
    ) -> None:
        self.down()

    @staticmethod
    def _get_docker_ip() -> str:
        docker_host = os.environ.get("DOCKER_HOST", "").strip()
        if not docker_host or docker_host.startswith("unix://"):
            return "127.0.0.1"

        if match := re.match(r"^tcp://(.+?):\d+$", docker_host):
            return match[1]

        msg = f'Invalid value for DOCKER_HOST: "{docker_host}".'
        raise ValueError(msg)

    def run_command(self, *args: str) -> None:
        command = [*self._base_command, *self._compose_files, *args]
        subprocess.run(command, check=True, capture_output=True)

    def start(
        self,
        name: str,
        docker_compose_files: list[Path],
        *,
        check: Callable[..., bool],
        timeout: float = 30,
        pause: float = 0.1,
        **kwargs: Any,
    ) -> None:
        for before_start in self._before_start:
            before_start()

        if SKIP_DOCKER_COMPOSE:
            self._running_services.add(name)
        if name not in self._running_services:
            self._compose_files = [f"--file={compose_file}" for compose_file in docker_compose_files]
            self.run_command("up", "--force-recreate", "-d", name)
            self._running_services.add(name)

        wait_until_responsive(
            check=check,
            timeout=timeout,
            pause=pause,
            host=self.docker_ip,
            **kwargs,
        )

    def stop(self, name: str) -> None:
        self.run_command("down", "--volumes", "-t", "10", name)

    def down(self) -> None:
        if not SKIP_DOCKER_COMPOSE:
            self.run_command("down", "-t", "10", "--volumes")
