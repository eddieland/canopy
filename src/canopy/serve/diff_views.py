"""A kept diff as the API sends it, for the web UI's diff panels.

A review's (DESIGN §21), a run's at its pushed head (§29), or a checklist's stretch (§42): each is read by
`review_diff.read`, within its bounds, and laid out here.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from canopy.serve.schema import DiffFile, DiffHunk, DiffLine, ReviewDiff

if TYPE_CHECKING:
    from canopy.core import review_diff


def diff_view(diff: review_diff.Diff) -> ReviewDiff:
    """Return a kept diff as the web UI reads it: a review's, a run's at its pushed head, or a checklist's stretch."""
    return ReviewDiff(
        files=[
            DiffFile(
                path=f.path,
                old_path=f.old_path,
                binary=f.binary,
                hunks=[
                    DiffHunk(
                        header=h.header,
                        lines=[DiffLine(kind=ln.kind, old=ln.old, new=ln.new, text=ln.text) for ln in h.lines],
                    )
                    for h in f.hunks
                ],
            )
            for f in diff.files
        ],
        truncated=diff.truncated,
    )
