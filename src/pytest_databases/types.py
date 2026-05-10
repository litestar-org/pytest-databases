from __future__ import annotations

import dataclasses
from typing import TYPE_CHECKING, Literal

if TYPE_CHECKING:
    from docker.models.containers import Container


@dataclasses.dataclass
class ServiceContainer:
    container: Container
    host: str
    port: int


XdistIsolationLevel = Literal["database", "server"]
