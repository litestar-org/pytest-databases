"""Docker service utilities and legacy compose registry."""

from __future__ import annotations

import os
import re
import subprocess  # ruff: ignore[suspicious-subprocess-import]
import time
import timeit
from contextlib import AbstractContextManager
from typing import TYPE_CHECKING, Any, Callable

from pytest_databases.helpers import simple_string_hash

if TYPE_CHECKING:
    from collections.abc import Iterable
    from pathlib import Path
    from types import TracebackType

__all__ = (
    "COMPOSE_PROJECT_NAME",
    "SKIP_DOCKER_COMPOSE",
    "TRUE_VALUES",
    "USE_LEGACY_DOCKER_COMPOSE",
    "DockerServiceRegistry",
    "wait_until_responsive",
)

TRUE_VALUES = {"True", "true", "1", "yes", "y", "Y", "T", "on", "enabled", "ok"}
SKIP_DOCKER_COMPOSE: bool = os.environ.get("SKIP_DOCKER_COMPOSE", "False") in TRUE_VALUES
USE_LEGACY_DOCKER_COMPOSE: bool = os.environ.get("USE_LEGACY_DOCKER_COMPOSE", "False") in TRUE_VALUES
COMPOSE_PROJECT_NAME: str = f"pytest-databases-{simple_string_hash(__file__)}"


def wait_until_responsive(
    check: Callable[..., bool],
    timeout: float,
    pause: float,
    **kwargs: Any,
) -> None:
    """Wait until a service is responsive.

    Args:
        check: Callable returning a truthy value when waiting should stop.
        timeout: Maximum seconds to wait.
        pause: Seconds to wait between calls to ``check``.
        **kwargs: Keyword arguments forwarded to ``check``.
    """
    ref = timeit.default_timer()
    now = ref
    while (now - ref) < timeout:
        if check(**kwargs):
            return
        time.sleep(pause)
        now = timeit.default_timer()

    msg = "Timeout reached while waiting on service!"
    raise RuntimeError(msg)


class DockerServiceRegistry(AbstractContextManager):
    """Manage Docker Compose services for a pytest worker."""

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
        self._base_command.extend([f"--project-name={compose_project_name}-{worker_id}"])
        self._before_start = list(before_start) if before_start else []

    def __exit__(
        self,
        /,
        __exc_type: type[BaseException] | None,
        __exc_value: BaseException | None,
        __traceback: TracebackType | None,
    ) -> None:
        self.down()

    def run_command(self, *args: str) -> None:
        """Execute a Docker Compose command for the active project."""
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
        """Start a compose service and wait until its readiness check succeeds."""
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
        """Stop a single compose service and remove its volumes."""
        self.run_command("down", "--volumes", "-t", "10", name)

    def down(self) -> None:
        """Stop all compose services for the active project."""
        if not SKIP_DOCKER_COMPOSE:
            self.run_command("down", "-t", "10", "--volumes")

    @staticmethod
    def _get_docker_ip() -> str:
        docker_host = os.environ.get("DOCKER_HOST", "").strip()
        if not docker_host or docker_host.startswith("unix://"):
            return "127.0.0.1"

        if match := re.match(r"^tcp://(.+?):\d+$", docker_host):
            return match[1]

        msg = f'Invalid value for DOCKER_HOST: "{docker_host}".'
        raise ValueError(msg)
