from __future__ import annotations

import json
from pathlib import Path

import pytest
from scripts.ci.pull_images import UnknownProviderError, pull_provider_images

PROJECT_ROOT = Path(__file__).parents[1]
MANIFEST = json.loads((PROJECT_ROOT / ".github" / "ci" / "provider-groups.json").read_text(encoding="utf-8"))


def test_pull_provider_images_uses_only_owned_images() -> None:
    commands: list[list[str]] = []

    def pull(command: list[str]) -> bool:
        commands.append(command)
        return True

    failures = pull_provider_images(MANIFEST, "bigquery", run_command=pull, sleep=lambda _: None)

    assert failures == []
    assert commands == [["docker", "pull", "ghcr.io/goccy/bigquery-emulator:latest"]]


def test_pull_provider_images_retries_and_reports_terminal_failure() -> None:
    attempts = 0

    def fail_then_succeed(_command: list[str]) -> bool:
        nonlocal attempts
        attempts += 1
        return attempts >= 3

    assert (
        pull_provider_images(
            MANIFEST,
            "bigquery",
            run_command=fail_then_succeed,
            sleep=lambda _: None,
            attempts=3,
        )
        == []
    )
    assert attempts == 3

    assert pull_provider_images(
        MANIFEST,
        "bigquery",
        run_command=lambda _: False,
        sleep=lambda _: None,
        attempts=2,
    ) == ["ghcr.io/goccy/bigquery-emulator:latest"]


def test_pull_provider_images_rejects_unknown_provider() -> None:
    with pytest.raises(UnknownProviderError, match="unknown provider"):
        pull_provider_images(MANIFEST, "not-real", run_command=lambda _: True)
