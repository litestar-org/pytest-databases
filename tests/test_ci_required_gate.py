from __future__ import annotations

import pytest
from scripts.ci.check_required_jobs import evaluate_required_jobs


@pytest.mark.parametrize("optional_status", ["skipped", "success"])
def test_required_gate_accepts_intentional_skips(optional_status: str) -> None:
    failures = evaluate_required_jobs(
        {
            "select": "success",
            "quality": optional_status,
            "compatibility": optional_status,
            "docs": optional_status,
            "provider": optional_status,
            "coverage": optional_status,
        },
        expected={"quality": False, "compatibility": False, "docs": False, "provider": False, "coverage": False},
    )

    assert failures == []


def test_required_gate_accepts_successful_expected_jobs() -> None:
    statuses = dict.fromkeys(("select", "quality", "compatibility", "docs", "provider", "coverage"), "success")

    assert (
        evaluate_required_jobs(
            statuses,
            expected={"quality": True, "compatibility": True, "docs": True, "provider": True, "coverage": True},
        )
        == []
    )


@pytest.mark.parametrize("status", ["failure", "cancelled", "timed_out", "action_required"])
def test_required_gate_rejects_unsuccessful_terminal_states(status: str) -> None:
    statuses = dict.fromkeys(("select", "quality", "compatibility", "docs", "provider", "coverage"), "success")
    statuses["quality"] = status

    assert evaluate_required_jobs(
        statuses,
        expected={"quality": True, "compatibility": True, "docs": True, "provider": True, "coverage": True},
    ) == [f"quality was {status}"]


def test_required_gate_rejects_expected_provider_skip() -> None:
    statuses = {
        "select": "success",
        "quality": "success",
        "compatibility": "success",
        "docs": "skipped",
        "provider": "skipped",
        "coverage": "skipped",
    }

    assert evaluate_required_jobs(
        statuses,
        expected={"quality": True, "compatibility": True, "docs": False, "provider": True, "coverage": True},
    ) == [
        "provider was skipped but selection required it",
        "coverage was skipped but selection required it",
    ]


def test_required_gate_rejects_selector_failure_even_when_everything_else_skips() -> None:
    statuses = dict.fromkeys(("quality", "compatibility", "docs", "provider", "coverage"), "skipped")
    statuses["select"] = "failure"

    assert evaluate_required_jobs(
        statuses,
        expected={"quality": False, "compatibility": False, "docs": False, "provider": False, "coverage": False},
    ) == ["select was failure"]
