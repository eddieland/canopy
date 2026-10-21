"""A PR's review limit, and the reviews the operator grants it past `policy.max_reviews_per_pr` (DESIGN §21, §22).

A PR's limit is the policy's plus the sum of its grants. Every review run still counts, however it ended (D030): a
grant raises one PR's limit and resets nothing. `start.py` enforces the limit; the state block shows a PR's `granted`
beside its `review_runs`. Only the operator grants (TRUST_MODEL T3).
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

from canopy.core import conversation, db, review_runs, sql

if TYPE_CHECKING:
    import sqlite3

    from canopy.core.config import Config

# The KIND `canopy grant` takes for a PR.
KIND = "review"


def limit(conn: sqlite3.Connection, config: Config, pr_url: str) -> int:
    """Return the most review runs the PR at `pr_url` may have: the policy's limit plus the runs granted it."""
    return config.policy.max_reviews_per_pr + granted(conn, pr_url)


def granted(conn: sqlite3.Connection, pr_url: str) -> int:
    """Return the review runs the operator granted the PR at `pr_url` past the policy's limit, 0 for none."""
    row = sql.execute(
        conn,
        sql.select("coalesce(sum(runs), 0)").from_("review_grants").where("pr_url = ?", pr_url),
    ).fetchone()
    return int(row[0])


def hint(pr_url: str) -> str:
    """Return what a `review_limit` attention item tells the operator they can do about it."""
    return f"allow it another review with `canopy grant {pr_url} review`"


@dataclass(frozen=True)
class Granted:
    """What `grant` recorded: the PR's review runs, and its limit with the grant counted."""

    runs: int
    limit: int


def grant(conn: sqlite3.Connection, config: Config, ref: conversation.Ref, *, runs: int) -> Granted:
    """Grant the PR `ref` names `runs` more review runs than the policy allows (DESIGN §22). Operator only.

    Every run still counts (D030): a grant raises the PR's limit, and the next `canopy review run` of it sees it.

    Returns:
        The PR's review runs, and its limit for them with the grant counted.

    Raises:
        Refused: `inside_run` inside one of canopy's own ticks or runs, `bad_ref` for a PR named as `REPO#N`, which
            review runs do not record, or `unknown` for a PR canopy has never reviewed.
    """
    conversation.check_operator()
    if not ref.id.startswith("https://"):
        raise conversation.Refused("bad_ref", f"name the PR by its URL, as `canopy review show` does, not {ref}")
    reviewed = len(review_runs.review_runs_of(conn, ref.id))
    if reviewed == 0:
        raise conversation.Refused("unknown", f"canopy has not reviewed {ref}, so it has no review limit to grant past")
    # The limit is read in the grant's own write transaction, so it counts this grant and none committed after it.
    with db.transaction(conn):
        sql.execute(conn, sql.insert("review_grants", pr_url=ref.id, runs=runs, granted_at=db.now()))
        return Granted(runs=reviewed, limit=limit(conn, config, ref.id))
