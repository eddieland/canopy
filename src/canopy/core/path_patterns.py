"""Paths and patterns from a repository's root, as config names them, and whether one covers a path git names.

`high_impact_paths` (DESIGN §21), a checklist's paths (§42), and `index.exclude` (§46) are each a list of these, checked
by `impact_path` when the config is read and compared by `covers`.
"""

from __future__ import annotations

import fnmatch
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from collections.abc import Sequence


def impact_path(value: str) -> str:
    """Check `value` as a path or pattern from a repository's root, as `high_impact_paths` and a checklist's take them.

    Returns:
        `value`, unchanged.

    Raises:
        ValueError: it is not one.
    """
    # Compared with the paths git names, which are from the root, by whole components (`canopy.reviews.impact`). A part
    # may hold `*` and `?`, or be `**`. `[`, `]`, and `\` are refused, so no entry is read as a class or an escape its
    # author did not mean, or meant one this does not read.
    parts = value.removesuffix("/").split("/")
    if (
        not value.isprintable()
        or value.startswith("/")
        or any(c in value for c in "[]\\")
        or any(p in {"", ".", ".."} or ("**" in p and p != "**") for p in parts)
    ):
        raise ValueError(
            "must be a path from the repository's root, such as '.agents/' or 'docs/TRUST_MODEL.md', or a pattern, "
            "such as '**/OWNERS' or 'services/*/migrations/': no leading '/', empty part, '.', or '..'; '*' and '?' "
            "within a part, '**' only as a whole part, and no '[', ']', or '\\'",
        )
    return value


def covers(parts: Sequence[str], components: Sequence[str]) -> bool:
    """Whether the pattern `parts`, an entry split at its `/`, covers the path `components`, split the same way.

    An entry covers the paths it matches and everything under them, compared by whole components: `.agents/` and
    `.agents` both cover `.agents/x.md`, and neither `.agentsrc`. Within a component `*` matches any run of characters
    and `?` one; a component `**` matches any number of components, none included.

    Returns:
        True when some prefix of `components` matches every part.
    """
    # Walks the parts once, keeping every count of components they can have matched so far, so a pattern with many
    # wildcards costs parts times components, never the backtracking of one regular expression over the whole path.
    # Any count left at the end is a prefix the pattern matches, and an entry covers everything under what it matches.
    reached = {0}
    for part in parts:
        if part == "**":
            reached = set(range(min(reached), len(components) + 1))
        else:
            reached = {n + 1 for n in reached if n < len(components) and fnmatch.fnmatchcase(components[n], part)}
        if not reached:
            return False
    return True
