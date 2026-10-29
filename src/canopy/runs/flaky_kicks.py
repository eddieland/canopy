"""Flaky kicks (DESIGN §23): the pushes canopy made to rerun a PR's checks a worker judged flaky, and their count.

A kick rebases the branch onto its base and pushes it with a lease, so its checks run again on a new head. Each kick
starts from the head the one before it pushed, so the chain back from a branch's head on origin counts the kicks spent
on the work a worker last pushed; a push of anyone's work starts a head no kick made, whose chain is empty.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from canopy.core import db, records, sql

if TYPE_CHECKING:
    import sqlite3


def spent(conn: sqlite3.Connection, repo: str, branch: str, head: str) -> int:
    """Return how many kicks `branch` in `repo` has had since its work was last pushed, as origin has it at `head`.

    Returns:
        The length of the chain of kicks that ends at `head`: 0 when no kick pushed it.
    """
    query = records.select(records.FlakyKick).where("repo = ? AND branch = ?", repo, branch)
    made = {k.to_head: k.from_head for k in query.all(conn)}
    count = 0
    # Bounded by the rows: a commit pushed again after a kick replaced it never loops the walk.
    while head in made and count < len(made):
        head = made[head]
        count += 1
    return count


def record(conn: sqlite3.Connection, run_id: int, *, repo: str, branch: str, from_head: str, to_head: str) -> None:
    """Record that run `run_id` kicks `branch` in `repo` from `from_head` to `to_head`, before it pushes (`forget`)."""
    row = sql.insert(
        "flaky_kicks",
        run_id=run_id,
        repo=repo,
        branch=branch,
        from_head=from_head,
        to_head=to_head,
        kicked_at=db.now(),
    )
    sql.execute(conn, row)


def forget(conn: sqlite3.Connection, run_id: int, repo: str) -> None:
    """Drop run `run_id`'s kick in `repo`, recorded before a push that then failed: the branch was not kicked."""
    sql.execute(conn, sql.delete("flaky_kicks").where("run_id = ? AND repo = ?", run_id, repo))
