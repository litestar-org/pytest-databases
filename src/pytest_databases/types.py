from __future__ import annotations

import dataclasses


@dataclasses.dataclass
class ServiceContainer:
    host: str
    port: int
