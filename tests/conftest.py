"""Shared pytest configuration and plugin registration for test suites.

All pytester tests in this project use ``runpytest_subprocess()`` instead of ``runpytest()``
because ``pytest-xdist`` requires subprocess execution, native C extensions in database
drivers can fault during in-process interpreter shutdown, and pytest 9+ plugin discovery
is isolated cleanly in subprocesses.
"""

from __future__ import annotations

import json
import platform
import textwrap
from typing import TYPE_CHECKING, Any

import pytest

if TYPE_CHECKING:
    from collections.abc import Callable

pytestmark = pytest.mark.anyio

pytest_plugins = [
    "pytest_databases.docker",
    "pytester",
]

PLATFORM_PROCESSOR = platform.processor()
PLATFORM_SYSTEM = platform.system()


def unwrap_fixture(fixture_def: Any) -> Callable[..., Any]:
    """Return the underlying callable wrapped by a pytest fixture definition."""
    return fixture_def.__wrapped__


def run_recording_deprecations(pytester: pytest.Pytester, source: str) -> list[str]:
    """Run ``source`` as a single passing pytester test module and return the DeprecationWarning messages recorded.

    A generated ``conftest.py`` records every ``DeprecationWarning`` pytest reports during the session, so callers can
    assert how many warnings fixture setup emitted and what they say.
    """
    pytester.makeconftest(
        textwrap.dedent("""
        import json

        recorded = []

        def pytest_warning_recorded(warning_message, when, nodeid, location):
            if issubclass(warning_message.category, DeprecationWarning):
                recorded.append(str(warning_message.message))

        def pytest_sessionfinish(session):
            with open("deprecations.json", "w") as handle:
                json.dump(recorded, handle)
        """)
    )
    pytester.makepyfile(textwrap.dedent(source))
    result = pytester.runpytest_subprocess("-p", "pytest_databases", "-W", "always::DeprecationWarning")
    result.assert_outcomes(passed=1)
    return json.loads((pytester.path / "deprecations.json").read_text())


def assert_legacy_platform_handling(
    pytester: pytest.Pytester,
    plugin: str,
    fixture_name: str,
    default: str | None,
    mode: str,
) -> None:
    """Check how ``<backend>_platform`` and the deprecated bare ``platform`` fixture behave for ``plugin``.

    ``mode`` is ``"default"`` (no override, no warning), ``"override"`` (a test-module ``platform`` override is
    honored with one warning), or ``"legacy"`` (requesting bare ``platform`` warns once and returns
    ``linux/x86_64``).
    """
    requested = "platform" if mode == "legacy" else fixture_name
    expected = {"default": default, "override": "linux/arm64", "legacy": "linux/x86_64"}[mode]
    override = (
        '@pytest.fixture(scope="session")\ndef platform():\n    return "linux/arm64"\n' if mode == "override" else ""
    )
    recorded = run_recording_deprecations(
        pytester,
        f"import pytest\n\npytest_plugins = [{plugin!r}]\n\n{override}\n"
        f"def test_platform({requested}):\n    assert {requested} == {expected!r}\n",
    )
    if mode == "default":
        assert recorded == []
        return
    assert len(recorded) == 1, recorded
    assert "v1.0.0" in recorded[0]
    if mode == "override":
        assert f"Override '{fixture_name}'" in recorded[0]
    else:
        assert fixture_name in recorded[0]
