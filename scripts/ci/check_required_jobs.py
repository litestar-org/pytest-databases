"""Evaluate dynamic workflow results behind one stable required check."""

from __future__ import annotations

import argparse
import sys
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from collections.abc import Mapping, Sequence


def evaluate_required_jobs(statuses: Mapping[str, str], *, expected: Mapping[str, bool]) -> list[str]:
    """Return deterministic explanations for failed or incorrectly skipped jobs."""
    failures: list[str] = []
    for job, status in statuses.items():
        required = job == "select" or expected.get(job, False)
        if status == "success":
            continue
        if status == "skipped" and not required:
            continue
        if status == "skipped":
            failures.append(f"{job} was skipped but selection required it")
        else:
            failures.append(f"{job} was {status or 'missing'}")
    return failures


def _parse_bool(value: str) -> bool:
    return value.lower() == "true"


def main(argv: Sequence[str] | None = None) -> int:
    """Validate Actions job results and selector intent."""
    parser = argparse.ArgumentParser()
    for job in ("select", "quality", "compatibility", "docs", "provider", "coverage"):
        parser.add_argument(f"--{job}", required=True)
    for job in ("quality", "compatibility", "docs", "provider", "coverage"):
        parser.add_argument(f"--expect-{job}", required=True)
    args = parser.parse_args(argv)

    statuses = {
        job: getattr(args, job) for job in ("select", "quality", "compatibility", "docs", "provider", "coverage")
    }
    expected = {
        job: _parse_bool(getattr(args, f"expect_{job}"))
        for job in ("quality", "compatibility", "docs", "provider", "coverage")
    }
    failures = evaluate_required_jobs(statuses, expected=expected)
    if failures:
        sys.stderr.write("\n".join(failures) + "\n")
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
