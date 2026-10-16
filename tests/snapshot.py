"""Snapshot tests: what canopy's code renders, compared with a file recorded under `tests/snapshots/`.

A snapshot holds deterministic output whole, so a change to its shape shows as a diff in review and a regression in a
part no assertion names still fails. It is for what canopy renders, never for model output (AGENTS.md, Testing).
`make snapshots` (pytest's `--update-snapshots`) records every snapshot that differs; review the diff before committing.
"""

from __future__ import annotations

import difflib
from dataclasses import dataclass
from pathlib import Path

import pytest

SNAPSHOTS_DIR = Path(__file__).parent / "snapshots"
UPDATE_OPTION = "--update-snapshots"


@dataclass(frozen=True)
class Snapshot:
    """Compares rendered text with its recorded snapshot, or records it when `update` is set."""

    update: bool

    def assert_matches(self, name: str, text: str) -> None:
        """Fail unless `text` is exactly the snapshot `name`, showing the difference. With `update`, record it instead.

        A missing snapshot fails too, unless recording: a test never passes against a file nobody reviewed.
        """
        path = SNAPSHOTS_DIR / name
        recorded = path.read_text() if path.exists() else None
        if text == recorded:
            return
        if self.update:
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(text)
            return
        if recorded is None:
            pytest.fail(f"no snapshot {name}: record it with `make snapshots`, then review it", pytrace=False)
        diff = difflib.unified_diff(
            recorded.splitlines(keepends=True), text.splitlines(keepends=True), f"recorded {name}", "rendered"
        )
        pytest.fail(
            f"{name} differs from its snapshot:\n{''.join(diff)}\n"
            "If the change is meant, record it with `make snapshots` and review the diff.",
            pytrace=False,
        )
