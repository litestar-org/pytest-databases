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

# NOTE: All pytester tests in this project use runpytest_subprocess() instead of runpytest().
# This is required because:
# 1. Tests using pytest-xdist (-n flag) need subprocess mode since xdist isn't available in-process
# 2. Many database drivers use native extensions (grpc, cryptography, pymssql, etc.) that can
#    cause segfaults during Python interpreter shutdown if loaded in the main test process
# 3. pytest 9.0+ has stricter plugin discovery that works more reliably in subprocess mode
