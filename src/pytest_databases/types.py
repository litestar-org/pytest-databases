from __future__ import annotations

import dataclasses
from typing import Literal


@dataclasses.dataclass
class ServiceContainer:
    host: str
    port: int


XdistIsolationLevel = Literal["database", "server"]
