"""Shared service container and isolation types."""

from __future__ import annotations

import dataclasses
from typing import TYPE_CHECKING, Literal

if TYPE_CHECKING:
    from docker.models.containers import Container

__all__ = ("ServiceContainer", "XdistIsolationLevel")


@dataclasses.dataclass
class ServiceContainer:
    """Base metadata for a started container service."""

    container: Container
    host: str
    port: int


XdistIsolationLevel = Literal["database", "server"]
