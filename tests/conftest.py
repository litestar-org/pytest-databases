from __future__ import annotations

import pytest

pytestmark = pytest.mark.anyio


pytest_plugins = [
    "pytest_databases.docker",
    "pytester",
]
