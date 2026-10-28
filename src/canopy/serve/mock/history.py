"""The mock journal's months before T0, for the reports page (DESIGN §11): the tickets the loop landed since April.

The workspace took up canopy in April 2026, on Opus for a ticket's first run; it moved its workers to Sonnet in June,
and its cache hit rate rose as its prompts settled. Each landed ticket has its worker runs, its PR merged, and what
people other than its author said on the PR, so each month has its cost by model, its landed tickets, and their
iterations, comments, reviews, and waits. Two more tickets were closed without a merge.

Every run started before October, so October's cost is still the fixtures' day alone, against its budget, and the
spend page's week holds none of it; the two tickets October landed did so on its first day.

Only worker runs: ticks, review runs, and chore runs list by id, and the fixtures' own hold the lowest ones, so a month
before October shows no overseer, review, or chore cost. The runs take the lowest ids, below the fixtures', and were
dispatched by tick 1, as run 37 was, which also records the `done` decisions: no older tick can take an id below it.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import TYPE_CHECKING, Final

from canopy.core import db, sql, workspace
from canopy.core.vocab import Phase, RunKind, RunStatus

if TYPE_CHECKING:
    import sqlite3
    from collections.abc import Sequence
    from pathlib import Path

OPUS: Final = "anthropic/claude-opus-4-1"
SONNET: Final = "anthropic/claude-sonnet-4-5"
# The words a branch name leaves out of its ticket's title.
_SMALL_WORDS: Final = frozenset({"a", "an", "the", "to", "in", "on", "for", "of"})


@dataclass(frozen=True)
class Run:
    """A worker run on a landed ticket."""

    kind: RunKind
    #: When it started, in hours after its ticket's first run did.
    hours: float
    minutes: int
    status: RunStatus
    cost_usd: float
    model: str
    summary: str


@dataclass(frozen=True)
class Said:
    """A review or a comment on a landed ticket's PR, from someone other than its author."""

    author: str
    #: When it was left, in hours after its ticket's first run started.
    hours: float
    body: str
    #: A review's state; None for a comment.
    state: str | None = None


@dataclass(frozen=True)
class Ticket:
    """A ticket the loop marked done before T0, and how it got there."""

    key: str
    title: str
    #: The workspace repository its unit is in, and its PR's number there.
    repo: str
    pr: int
    #: When its first worker run started.
    started: datetime
    runs: Sequence[Run]
    said: Sequence[Said]
    #: When the loop marked it done, in hours after its first run started.
    done_hours: float
    #: Whether it was closed without a merge, rather than merged.
    closed: bool = False

    @property
    def url(self) -> str:
        """Its PR's URL."""
        return f"https://github.com/acme/{self.repo}/pull/{self.pr}"

    @property
    def branch(self) -> str:
        """Its branch, named for its key and the first two words of its title that are not small ones."""
        words = [w for w in self.title.lower().split() if w not in _SMALL_WORDS]
        return f"agent/{self.key}-{'-'.join(words[:2])}"

    @property
    def done_at(self) -> datetime:
        """When the loop marked it done."""
        return self.started + timedelta(hours=self.done_hours)


def _on(month: int, day: int, hour: int = 10) -> datetime:
    return datetime(2026, month, day, hour, tzinfo=UTC)


def _implement(cost: float, model: str, summary: str, *, minutes: int = 40) -> Run:
    return Run(RunKind.IMPLEMENT, 0, minutes, RunStatus.DONE, cost, model, summary)


def _resume(hours: float, cost: float, summary: str, *, model: str = SONNET, minutes: int = 18) -> Run:
    return Run(RunKind.RESUME, hours, minutes, RunStatus.DONE, cost, model, summary)


def _fix_ci(hours: float, cost: float, summary: str, *, status: RunStatus = RunStatus.DONE) -> Run:
    return Run(RunKind.FIX_CI, hours, 12, status, cost, SONNET, summary)


#: The tickets, the oldest first.
TICKETS: Final[Sequence[Ticket]] = (
    Ticket(
        "ABC-041",
        "Add a health check endpoint",
        "api",
        3,
        _on(4, 14),
        [_implement(3.92, OPUS, "Added GET /healthz, which checks the database and the queue.")],
        [Said("bob", 23, "Simple and does what it says.", "approved")],
        29,
    ),
    Ticket(
        "ABC-043",
        "Rewrite the admin in Svelte",
        "web",
        43,
        _on(4, 20, 13),
        [
            # Not blocked: a blocked run waits on the operator, whose ticket's being done does not end the wait.
            Run(RunKind.IMPLEMENT, 0, 60, RunStatus.TIMEOUT, 1.24, OPUS, "the worker ran past its 60 minutes"),
        ],
        [],
        52,
        closed=True,
    ),
    Ticket(
        "ABC-044",
        "Paginate the orders list",
        "web",
        41,
        _on(4, 21),
        [
            _implement(4.61, OPUS, "The orders list loads 50 at a time, with a cursor from the API.", minutes=55),
            _resume(26, 2.08, "Kept the page size in the URL, as review asked.", model=OPUS, minutes=24),
        ],
        [
            Said("alice", 20, "The page size should survive a reload.", "changes_requested"),
            Said("alice", 20, "Put the page size in the URL, not in state."),
            Said("alice", 20, "What happens when the cursor points at a deleted order?"),
            Said("alice", 45, "Thanks, that reads well now.", "approved"),
        ],
        55,
    ),
    Ticket(
        "ABC-047",
        "Rate-limit the login form",
        "api",
        5,
        _on(5, 5),
        [_implement(4.07, OPUS, "Login allows 5 tries a minute per address and per account.")],
        [
            Said("carol", 4, "Five a minute per account, or per address too?"),
            Said("carol", 18, "Both is right.", "approved"),
        ],
        26,
    ),
    Ticket(
        "ABC-049",
        "Dark mode for settings",
        "web",
        47,
        _on(5, 11),
        [
            _implement(5.18, OPUS, "The settings pages follow the system theme and have a toggle.", minutes=62),
            _fix_ci(2, 0.61, "The visual tests still fail: their baselines are light only.", status=RunStatus.FAILED),
            _fix_ci(3, 0.88, "Recorded dark baselines for the settings pages."),
            _resume(30, 2.37, "Moved the toggle to the account menu, as review asked."),
        ],
        [
            Said("alice", 22, "The toggle belongs in the account menu.", "changes_requested"),
            Said("alice", 22, "This grey fails contrast on the dark background."),
            Said("dana", 23, "Agree on the menu."),
            Said("alice", 58, "Looks right in both themes.", "approved"),
        ],
        74,
    ),
    Ticket(
        "ABC-052",
        "Retry webhooks on 5xx",
        "api",
        7,
        _on(5, 26),
        [_implement(3.31, OPUS, "Failed webhooks retry with backoff, up to 6 times over an hour.")],
        [Said("bob", 6, "Good: capped, and with jitter.", "approved")],
        27,
    ),
    Ticket(
        "ABC-055",
        "Upgrade React Router",
        "web",
        52,
        _on(6, 3),
        [
            _implement(2.41, SONNET, "Moved to React Router 7 and its data routers.", minutes=48),
            _resume(28, 1.12, "Kept the old redirect for /account, as review asked."),
        ],
        [
            Said("dana", 20, "/account/old still has links pointing at it.", "changes_requested"),
            Said("dana", 20, "Keep a redirect for it."),
            Said("dana", 44, "Thanks.", "approved"),
        ],
        50,
    ),
    Ticket(
        "ABC-058",
        "Push notifications opt-in screen",
        "mobile",
        31,
        _on(6, 10),
        [_implement(2.02, SONNET, "Added the opt-in screen, shown once after the first order.")],
        [
            Said("erin", 5, "Can we skip it for users who already declined in the OS?"),
            Said("erin", 21, "Answered in the code, thanks.", "approved"),
        ],
        25,
    ),
    Ticket(
        "ABC-060",
        "CSV import validation",
        "web",
        55,
        _on(6, 23),
        [
            _implement(2.66, SONNET, "The import checks each row and reports the bad ones with their line numbers."),
            _fix_ci(1, 0.47, "Fixed a test that read the sample file from the wrong directory."),
        ],
        [Said("alice", 19, "Nice error messages.", "approved")],
        28,
    ),
    Ticket(
        "ABC-063",
        "Cache product thumbnails",
        "web",
        58,
        _on(7, 1),
        [_implement(1.87, SONNET, "Thumbnails are cached for a day at the CDN, keyed by the image's hash.")],
        [Said("bob", 3, "Ship it.", "approved")],
        22,
    ),
    Ticket(
        "ABC-066",
        "Localize the checkout into German",
        "web",
        60,
        _on(7, 13),
        [
            _implement(3.14, SONNET, "The checkout reads its strings from the catalog; added German.", minutes=58),
            _resume(27, 1.38, "Formatted prices with the locale, as review asked."),
            _resume(50, 0.91, "Shortened the button labels that wrapped on small screens."),
        ],
        [
            Said("alice", 22, "Prices need the locale's separators.", "changes_requested"),
            Said("alice", 22, "1.234,56 € in German, not €1,234.56."),
            Said("alice", 22, "The tax line is still in English."),
            Said("carol", 46, "Two buttons wrap on a small phone.", "changes_requested"),
            Said("carol", 46, "'Zahlungspflichtig bestellen' needs a shorter fallback."),
            Said("carol", 70, "All good now.", "approved"),
        ],
        75,
    ),
    Ticket(
        "ABC-067",
        "Migrate to Postgres 17",
        "api",
        8,
        _on(7, 20),
        [],
        [],
        2,
        closed=True,
    ),
    Ticket(
        "ABC-068",
        "Offline queue for mobile orders",
        "mobile",
        35,
        _on(7, 27),
        [_implement(2.58, SONNET, "Orders placed offline queue on the device and send when it reconnects.")],
        [
            Said("erin", 20, "What if the price changed while offline?"),
            Said("erin", 26, "The server check covers it.", "approved"),
        ],
        48,
    ),
    Ticket(
        "ABC-071",
        "Fix timezone in invoice dates",
        "api",
        9,
        _on(8, 11),
        [_implement(1.21, SONNET, "Invoices print dates in the customer's timezone, not the server's.")],
        [Said("bob", 21, "Good catch.", "approved")],
        25,
    ),
    Ticket(
        "ABC-073",
        "Search suggestions",
        "web",
        64,
        _on(8, 24),
        [
            _implement(2.19, SONNET, "The search box suggests the top five matches as you type."),
            _resume(30, 0.83, "Suggestions wait 200 ms after the last key, as review asked."),
        ],
        [
            Said("dana", 23, "This sends a request on every key.", "changes_requested"),
            Said("dana", 23, "Debounce it."),
            Said("dana", 47, "Better.", "approved"),
        ],
        53,
    ),
    Ticket(
        "ABC-076",
        "Stripe webhooks v2",
        "api",
        11,
        _on(9, 2),
        [
            _implement(2.04, SONNET, "Moved the Stripe handler to v2 events and their signatures."),
            _fix_ci(1, 0.38, "Updated the recorded fixtures for the v2 event shapes."),
        ],
        [
            Said("carol", 6, "Do we still check the v1 signature during the cutover?"),
            Said("carol", 20, "Matches the migration guide.", "approved"),
        ],
        48,
    ),
    Ticket(
        "ABC-079",
        "Image upload progress",
        "mobile",
        40,
        _on(9, 9),
        [_implement(1.66, SONNET, "Uploads show a progress bar and can be cancelled.")],
        [Said("erin", 4, "Approved; nice touch on cancel.", "approved")],
        22,
    ),
    Ticket(
        "ABC-082",
        "Audit log export",
        "web",
        70,
        _on(9, 16),
        [
            _implement(2.47, SONNET, "Admins can export the audit log for a date range as CSV."),
            _resume(25, 0.97, "Capped an export at 90 days, as review asked."),
        ],
        [
            Said("dana", 21, "A year of events times out.", "changes_requested"),
            Said("dana", 21, "Cap the range, or stream it."),
            Said("alice", 22, "Capping is fine for now."),
            Said("dana", 44, "Thanks.", "approved"),
        ],
        52,
    ),
    Ticket(
        "ABC-085",
        "Drop the legacy cart",
        "web",
        73,
        _on(9, 24),
        [_implement(1.58, SONNET, "Removed the v1 cart and its feature flag; 2,300 lines gone.")],
        [
            Said("bob", 1, "Does analytics still count abandoned carts?"),
            Said("alice", 2, "Deleting code is my favorite kind of PR.", "approved"),
        ],
        26,
    ),
    Ticket(
        "ABC-088",
        "Feature flags for checkout",
        "web",
        78,
        _on(9, 29),
        [_implement(1.79, SONNET, "Checkout steps read their flags from the flag service, with safe defaults.")],
        [Said("bob", 19, "Defaults look safe.", "approved")],
        51,
    ),
    Ticket(
        "ABC-091",
        "Accessible date picker",
        "web",
        81,
        _on(9, 28),
        [
            _implement(2.21, SONNET, "The date picker works from the keyboard and names each day for screen readers."),
            _resume(50, 0.89, "Escape closes the picker and returns focus, as review asked."),
        ],
        [
            Said("alice", 24, "Escape should close it and return focus.", "changes_requested"),
            Said("alice", 24, "Arrow keys skip the disabled days; good."),
            Said("carol", 70, "Works with VoiceOver.", "approved"),
        ],
        77,
    ),
)

# What a run's tokens are per dollar it cost, as the fixtures' runs are, but for the cache read, which grew as the
# prompts settled: by the month the run started in.
_CACHE_READ_PER_USD: Final = {4: 90_000, 5: 140_000, 6: 220_000, 7: 300_000, 8: 330_000, 9: 380_000}
_REVIEW_IDS: Final = 4_100_100_000
_COMMENT_IDS: Final = 2_460_100_000


def seed(conn: sqlite3.Connection, root: Path) -> None:
    """Insert each ticket in TICKETS: its row, its unit and PR, its runs and the models they ran on, and its `done`."""
    run_id = 0
    said_id = 0
    for ticket in TICKETS:
        _ticket(conn, root, ticket)
        for run in ticket.runs:
            run_id += 1
            _run(conn, root, run_id, ticket, run)
        for said in ticket.said:
            said_id += 1
            _said(conn, ticket, said_id, said)
        sql.execute(
            conn,
            sql.insert(
                "decisions",
                tick_id=1,
                created_at=db.format_time(ticket.done_at),
                ticket_key=ticket.key,
                repo=None if ticket.closed else ticket.repo,
                pr=None if ticket.closed else ticket.url,
                action="done",
                rationale=db.CLOSED_RATIONALE if ticket.closed else f"merged: {ticket.url}",
            ),
        )


def _ticket(conn: sqlite3.Connection, root: Path, ticket: Ticket) -> None:
    done = db.format_time(ticket.done_at)
    sql.execute(
        conn,
        sql.insert(
            "tickets",
            key=ticket.key,
            repo=str(root),
            first_seen_at=db.format_time(ticket.started - timedelta(hours=1)),
            last_seen_at=done,
            changed_at=done,
            title=ticket.title,
            phase=Phase.BLOCKED if ticket.closed else Phase.MERGED,
            branch=ticket.branch if ticket.runs else None,
            done=1,
        ),
    )
    if ticket.closed:
        return
    sql.execute(
        conn,
        sql.insert(
            "ticket_units",
            ticket_key=ticket.key,
            repo=ticket.repo,
            branch=ticket.branch,
            pr_url=ticket.url,
            phase=Phase.MERGED,
        ),
    )
    title = f"{ticket.key}: {ticket.title}"
    sql.execute(conn, sql.insert("pr_titles", pr_url=ticket.url, title=title, updated_at=done))
    sql.execute(
        conn,
        sql.insert(
            "observed_prs",
            url=ticket.url,
            repository=f"acme/{ticket.repo}",
            number=ticket.pr,
            base_ref="main",
            state="merged",
            draft=0,
            author="op",
            observed_at=done,
            title=title,
        ),
    )


def _run(conn: sqlite3.Connection, root: Path, run_id: int, ticket: Ticket, run: Run) -> None:
    started = ticket.started + timedelta(hours=run.hours)
    result: dict[str, object] = {"summary": run.summary}
    if run.status is RunStatus.DONE and run.kind is RunKind.IMPLEMENT:
        result["prs"] = {ticket.repo: ticket.url}
    elif run.status in {RunStatus.FAILED, RunStatus.TIMEOUT}:
        result = {"harness": run.summary}
    cost = run.cost_usd
    sql.execute(
        conn,
        sql.insert(
            "runs",
            id=run_id,
            tick_id=1,
            ticket_key=ticket.key,
            kind=run.kind,
            branch=ticket.branch,
            started_at=db.format_time(started),
            ended_at=db.format_time(started + timedelta(minutes=run.minutes)),
            status=run.status,
            result_json=json.dumps(result),
            log_path=str(root.absolute() / workspace.WORKSPACE_STATE_DIR / "runs" / f"{run_id}.log"),
            session_id=f"ses_mock{run_id}",
            cost_usd=cost,
            tokens_input=int(cost * 40_000),
            tokens_output=int(cost * 6_000),
            tokens_reasoning=int(cost * 2_000),
            tokens_cache_read=int(cost * _CACHE_READ_PER_USD[started.month]),
            tokens_cache_write=int(cost * 8_000),
            tokens_peak_context=int(cost * 60_000),
        ),
    )
    read_at = db.format_time(started + timedelta(minutes=run.minutes + 1))
    sql.execute(
        conn,
        sql.insert("run_model_reads", run_table="runs", run_id=run_id, status="found", attempts=1, read_at=read_at),
    )
    replies = max(1, round(cost * 30))
    sql.execute(
        conn,
        sql.insert("run_models", run_table="runs", run_id=run_id, model=run.model, replies=replies, cost_usd=cost),
    )


def _said(conn: sqlite3.Connection, ticket: Ticket, n: int, said: Said) -> None:
    url = ticket.url
    if said.state is not None:
        values: dict[str, sql.Value] = {
            "item": "review",
            "id": _REVIEW_IDS + n,
            "state": said.state,
            "url": f"{url}#pullrequestreview-{_REVIEW_IDS + n}",
        }
    else:
        values = {
            "item": "comment",
            "id": _COMMENT_IDS + n,
            "url": f"{url}#discussion_r{_COMMENT_IDS + n}",
            "thread_id": f"PRRT_mock{n}",
            "side": "right",
            "outdated": 0,
            "resolved": 1,
        }
    sql.execute(
        conn,
        sql.insert(
            "observed_reviews",
            pr_url=url,
            author=said.author,
            bot=0,
            created_at=db.format_time(ticket.started + timedelta(hours=said.hours)),
            body=said.body,
            observed_at=db.format_time(ticket.done_at),
            **values,
        ),
    )
