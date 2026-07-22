from __future__ import annotations

import json
import sys
from pathlib import Path

from scripts.ci.run_tests import build_compatibility_command

PROJECT_ROOT = Path(__file__).parents[1]


def test_build_compatibility_command_uses_only_clientless_nodes() -> None:
    manifest = json.loads((PROJECT_ROOT / ".github" / "ci" / "provider-groups.json").read_text(encoding="utf-8"))

    command = build_compatibility_command(manifest)

    assert command[:3] == [sys.executable, "-m", "pytest"]
    assert command[3:] == manifest["compatibility_test_paths"]
    assert all("test_ci_" in node_id or "without_" in node_id for node_id in command[3:])
