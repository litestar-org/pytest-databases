"""pytest-databases: Ephemeral database fixtures for pytest."""

from __future__ import annotations

from pytest_databases._service import (
    MANAGED_LABEL,
    OWNER_LABEL,
    SERVICE_LABEL,
    ContainerService,
    DockerService,
    _stop_all_containers,
    _stop_owned_containers,
    derive_session_owner_id,
    stop_all_containers,
    stop_owned_containers,
)
from pytest_databases.runtime import (
    ContainerRuntimeConfig,
    ContainerRuntimeKind,
    ResolvedContainerRuntimeKind,
    ResolvedRuntime,
    RuntimeCandidate,
    RuntimeResolutionError,
    RuntimeType,
)

__all__ = [
    "MANAGED_LABEL",
    "OWNER_LABEL",
    "SERVICE_LABEL",
    "ContainerRuntimeConfig",
    "ContainerRuntimeKind",
    "ContainerService",
    "DockerService",
    "ResolvedContainerRuntimeKind",
    "ResolvedRuntime",
    "RuntimeCandidate",
    "RuntimeResolutionError",
    "RuntimeType",
    "_stop_all_containers",
    "_stop_owned_containers",
    "derive_session_owner_id",
    "stop_all_containers",
    "stop_owned_containers",
]
