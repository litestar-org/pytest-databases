# SPDX-FileCopyrightText: 2023-present Litestar
#
# SPDX-License-Identifier: MIT

from __future__ import annotations

from pathlib import Path

import pytest

pytestmark = pytest.mark.anyio
here = Path(__file__).parent
root_path = here.parent
pytest_plugins = [
    "pytest_databases.docker",
]


@pytest.fixture
def anyio_backend() -> str:
    return "asyncio"
