"""pytest-databases: Ephemeral database fixtures for pytest."""

from __future__ import annotations

from pytest_databases._service import (
    MANAGED_LABEL,
    OWNER_LABEL,
    SERVICE_LABEL,
    ContainerService,
    DockerService,
    derive_session_owner_id,
    should_keep_containers,
    stop_all_containers,
    stop_owned_containers,
    wait_for_container_health,
)
from pytest_databases.runtime import (
    ContainerRuntimeConfig,
    RuntimeCandidate,
    RuntimeResolutionError,
    RuntimeType,
)

__all__ = (
    "MANAGED_LABEL",
    "OWNER_LABEL",
    "SERVICE_LABEL",
    "ContainerRuntimeConfig",
    "ContainerService",
    "DockerService",
    "RuntimeCandidate",
    "RuntimeResolutionError",
    "RuntimeType",
    "derive_session_owner_id",
    "should_keep_containers",
    "stop_all_containers",
    "stop_owned_containers",
    "wait_for_container_health",
)
