from __future__ import annotations

import platform

import pytest

pytestmark = pytest.mark.anyio


pytest_plugins = [
    "pytest_databases.docker",
    "pytester",
]

PLATFORM_PROCESSOR = platform.processor()
PLATFORM_SYSTEM = platform.system()
