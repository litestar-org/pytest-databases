# MIT License

# Copyright (c) 2024 Litestar

# Permission is hereby granted, free of charge, to any person obtaining a copy
# of this software and associated documentation files (the "Software"), to deal
# in the Software without restriction, including without limitation the rights
# to use, copy, modify, merge, publish, distribute, sublicense, and/or sell
# copies of the Software, and to permit persons to whom the Software is
# furnished to do so, subject to the following conditions:

# The above copyright notice and this permission notice shall be included in all
# copies or substantial portions of the Software.

# THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
# IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,
# FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE
# AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER
# LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM,
# OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN THE
# SOFTWARE.


from __future__ import annotations

import asyncio
import os
import re
import subprocess  # noqa: S404
import sys
import timeit
from typing import TYPE_CHECKING, Any, Callable

import pytest

from pytest_databases.helpers import simple_string_hash, wrap_sync

if TYPE_CHECKING:
    from collections.abc import Awaitable, Generator
    from pathlib import Path


async def wait_until_responsive(
    check: Callable[..., Awaitable],
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
        if await check(**kwargs):
            return
        await asyncio.sleep(pause)
        now = timeit.default_timer()

    msg = "Timeout reached while waiting on service!"
    raise RuntimeError(msg)


SKIP_DOCKER_COMPOSE: bool = bool(os.environ.get("SKIP_DOCKER_COMPOSE", False))
USE_LEGACY_DOCKER_COMPOSE: bool = bool(os.environ.get("USE_LEGACY_DOCKER_COMPOSE", False))
COMPOSE_PROJECT_NAME: str = f"pytest-databases-{simple_string_hash(__file__)}"


class DockerServiceRegistry:
    def __init__(self, worker_id: str, compose_project_name: str = COMPOSE_PROJECT_NAME) -> None:
        self._running_services: set[str] = set()
        self.docker_ip = self._get_docker_ip()
        self._base_command = ["docker-compose"] if USE_LEGACY_DOCKER_COMPOSE else ["docker", "compose"]
        self._compose_files: list[str] = []
        self._base_command.extend(
            [
                f"--project-name={compose_project_name}-{worker_id}",
            ],
        )

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

    async def start(
        self,
        name: str,
        docker_compose_files: list[Path],
        *,
        check: Callable[..., Any],
        timeout: float = 30,
        pause: float = 0.1,
        **kwargs: Any,
    ) -> None:
        if SKIP_DOCKER_COMPOSE:
            self._running_services.add(name)
        if name not in self._running_services:
            self._compose_files = [f"--file={compose_file}" for compose_file in docker_compose_files]
            self.run_command("up", "--force-recreate", "-d", name)
            self._running_services.add(name)

        await wait_until_responsive(
            check=wrap_sync(check),
            timeout=timeout,
            pause=pause,
            host=self.docker_ip,
            **kwargs,
        )

    def stop(self, name: str) -> None:
        self.run_command("down", "--volumes", "-t", "10", name)

    def down(self) -> None:
        if not SKIP_DOCKER_COMPOSE:
            self.run_command("down", "-t", "10")


@pytest.fixture(scope="session")
def compose_project_name() -> str:
    return os.environ.get("COMPOSE_PROJECT_NAME", COMPOSE_PROJECT_NAME)


@pytest.fixture(scope="session")
def docker_services(compose_project_name: str, worker_id: str = "main") -> Generator[DockerServiceRegistry, None, None]:
    if os.getenv("GITHUB_ACTIONS") == "true" and sys.platform != "linux":
        pytest.skip("Docker not available on this platform")

    registry = DockerServiceRegistry(worker_id, compose_project_name=compose_project_name)
    try:
        yield registry
    finally:
        registry.down()


@pytest.fixture(scope="session")
def docker_ip(docker_services: DockerServiceRegistry) -> str:
    return docker_services.docker_ip
