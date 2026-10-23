"""Shared pytest configuration and plugin registration for test suites.

All pytester tests in this project use ``runpytest_subprocess()`` instead of ``runpytest()``
because ``pytest-xdist`` requires subprocess execution, native C extensions in database
drivers can fault during in-process interpreter shutdown, and pytest 9+ plugin discovery
is isolated cleanly in subprocesses.
"""

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
