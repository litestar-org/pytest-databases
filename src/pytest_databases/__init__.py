"""pytest-databases: Ephemeral database fixtures for pytest."""

from __future__ import annotations

from pytest_databases._service import (
    MANAGED_LABEL,
    OWNER_LABEL,
    SERVICE_LABEL,
    ContainerService,
    DockerService,
    derive_session_owner_id,
    has_active_owner_sessions,
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
from pytest_databases.types import (
    ServiceContainer,
    copy_from_container,
    copy_to_container,
    exec_container_command,
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
    "ServiceContainer",
    "copy_from_container",
    "copy_to_container",
    "derive_session_owner_id",
    "exec_container_command",
    "has_active_owner_sessions",
    "should_keep_containers",
    "stop_all_containers",
    "stop_owned_containers",
    "wait_for_container_health",
)
