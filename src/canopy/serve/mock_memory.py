"""The mock journal's agent memory (DESIGN §28), for `python -m canopy.serve --mock`.

Ticket notes are in use and lessons recording, as the mock's config sets them. ABC-100's runs wrote notes, one
superseded, and one written to the journal by hand past the bounds, with a link and a zero-width space, which every
surface shows as plain text with the space named. Run 37 was rendered while notes were recording, so it read nothing;
run 40 read run 37's note and had a secret refused. Two proposals wait, one from a private ticket's run, and one
promoted earlier is a lesson, recorded and served to no run.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from canopy.core import sql

if TYPE_CHECKING:
    import sqlite3
    from collections.abc import Callable


def seed(conn: sqlite3.Connection, at: Callable[[int], str]) -> None:
    """Insert what each run recorded and read of memory, the notes and proposals, and the lesson."""
    sql.execute_many(
        conn,
        sql.insert_rows("run_memory", ("run_id", "ticket_notes", "proposals", "refused")),
        [
            (37, "record", "record", "[]"),
            (39, "use", "record", "[]"),
            (
                40,
                "use",
                "record",
                '[{"field": "notes", "key": "staging-login", "why": "its text looks like it holds a secret"}]',
            ),
            (42, "use", "record", "[]"),
        ],
    )
    notes = (
        # id, scope, ticket, repo, key, body, status, why, run, head, created, last used, uses, promoted from
        (
            1,
            "ticket",
            "ABC-100",
            None,
            "flaky-checkout",
            "checkout.spec.ts fails about one run in five; it looks like a timing issue in the payment step.",
            "superseded",
            "superseded by note 2",
            37,
            "4f1c2a9e07b3",
            at(-200),
            at(-115),
            1,
            None,
        ),
        (
            2,
            "ticket",
            "ABC-100",
            None,
            "flaky-checkout",
            "checkout.spec.ts races the payment iframe: waiting on its load event made it pass 20 of 20 runs locally.",
            "active",
            None,
            40,
            "9b2e5d01c4a7",
            at(-112),
            None,
            0,
            None,
        ),
        (
            3,
            "ticket",
            "ABC-100",
            None,
            "ci-cache",
            (
                "CI's cache key leaves out [package-lock.json](https://evil.example/lock)\u200b, so a bumped "
                "lockfile installs from a stale cache."
            ),
            "active",
            None,
            40,
            "9b2e5d01c4a7",
            at(-112),
            None,
            0,
            None,
        ),
        (
            4,
            "ticket",
            "ABC-102",
            None,
            "export-encoding",
            "The CSV writer needs utf-8-sig for Excel to read accented names; plain utf-8 shows mojibake.",
            "active",
            None,
            42,
            "c0ffee12ab34",
            at(-30),
            None,
            0,
            None,
        ),
        (
            5,
            "proposal",
            "ABC-099",
            "web",
            "web-tests",
            "Run web's tests with `npm test -- --run`: plain `npm test` watches and never exits.",
            "pending",
            None,
            39,
            "77aa21d0e9f3",
            at(-62),
            None,
            0,
            None,
        ),
        (
            6,
            "proposal",
            "ABC-102",
            None,
            # Under lesson 8's key, so the memory page shows a proposal that would replace a lesson in force.
            "billing-client",
            "Billing retries go through retry() in src/billing/client.ts too; never loop on a 503 by hand.",
            "pending",
            None,
            42,
            "c0ffee12ab34",
            at(-30),
            None,
            0,
            None,
        ),
        (
            7,
            "proposal",
            "ABC-103",
            "web",
            "billing-client",
            "Billing calls go through src/billing/client.ts; never call the v1 endpoints directly.",
            "superseded",
            "promoted to lesson 8",
            38,
            "1d2c3b4a5f6e",
            at(-126),
            None,
            0,
            None,
        ),
    )
    sql.execute_many(
        conn,
        sql.insert_rows(
            "memories",
            (
                "id",
                "scope",
                "ticket_key",
                "repo",
                "key",
                "body",
                "status",
                "why",
                "run_id",
                "head",
                "created_at",
                "last_used_at",
                "use_count",
                "promoted_from",
                "author",
                "tick_id",
            ),
        ),
        [(*n, "worker", 1) for n in notes],
    )
    # Note 2 is the second version of `flaky-checkout`, as `_run` links a note to the one under its key it replaced.
    sql.execute(conn, sql.update("memories").set(supersedes=1).where("id = 2"))
    sql.execute(
        conn,
        sql.insert(
            "memories",
            id=8,
            scope="lesson",
            repo="web",
            key="billing-client",
            body="Billing goes through src/billing/client.ts alone; the v1 endpoints are gone.",
            status="active",
            author="operator",
            promoted_from=7,
            created_at=at(-100),
            approved_at=at(-100),
            review_at=at(90 * 24 * 60),
        ),
    )
    sql.execute(conn, sql.insert("memory_reads", run_id=40, memory_id=1, cited="used"))
