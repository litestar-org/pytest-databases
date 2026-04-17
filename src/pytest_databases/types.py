from __future__ import annotations

import dataclasses
from typing import Literal

from docker.models.containers import Container


@dataclasses.dataclass
class ServiceContainer:
    container: Container
    host: str
    port: int


XdistIsolationLevel = Literal["database", "server"]
