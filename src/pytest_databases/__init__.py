# SPDX-FileCopyrightText: 2024-present Litestar <hello@litestar.dev>
#
# SPDX-License-Identifier: MIT

# Re-export fixtures from _service module so they are available when the package is imported.
# This is necessary because pytest 9.0+ enforces strict plugin name uniqueness, and the
# entry point name "pytest_databases" conflicts with the package name when using
# pytest_plugins declarations that import submodules (e.g., pytest_databases.docker.postgres).
from pytest_databases._service import (
    DockerService,
    docker_client,
    docker_service,
    get_docker_client,
    get_docker_host,
    pytest_sessionfinish,
)

__all__ = [
    "DockerService",
    "docker_client",
    "docker_service",
    "get_docker_client",
    "get_docker_host",
    "pytest_sessionfinish",
]
