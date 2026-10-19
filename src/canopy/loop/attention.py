"""The attention list: what needs a human, derived from the journal (DESIGN §14).

Attention items are decisions with action `attention:<reason>`, recorded every tick the cause holds: by the overseer
for what it reads in the world, and by the harness for runs that ended in a way a human must look at (`from_runs`). The
current list is therefore the items of the latest tick whose overseer finished; an item disappears when a tick no
longer records it. A tick that could not run the overseer because `canopy` does not work for it adds one item of its own
to that list, while it is the latest tick.

A chore's open findings are on the list too, from its latest `ok` run, and a chore whose latest run failed has a
`chore_failed` item the harness records each tick (DESIGN §19). Both are about a chore, named `chore:<name>` where a
ticket key would be, which no ticket key can equal. Only chores configured for this workspace are listed, and no
finding the operator dismissed (`listed`).

After every tick, `publish` rewrites `<state_dir>/attention.md` and hands the list to the notification sinks
(`canopy.notify`), each told about each open item once however many ticks it lasts (DESIGN §20).
"""

from __future__ import annotations

import sqlite3
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import TYPE_CHECKING, NotRequired, TypedDict, assert_never

from canopy.core import chore_view, contract, conversation, db, memory, plans, review_result
from canopy.core.items import Item, age, fingerprint, one_line, subject
from canopy.core.vocab import ReviewRunStatus, RunKind, RunStatus, TickStatus
from canopy.infra import logs
from canopy.notify import deliver
from canopy.runs import drafted

if TYPE_CHECKING:
    from canopy.core import records
    from canopy.core.context import Context

ACTION_PREFIX = "attention:"
# Where a ticket key would be, an item about a chore names it so, and one about a PR with no ticket. A ticket key has
# no colon (DESIGN §17), so neither can equal one.
CHORE_PREFIX = "chore:"
PR_PREFIX = "pr:"


def run_reason(status: RunStatus) -> str | None:
    """The attention reason a run that ended in `status` raises.

    `unknown` and `timeout` both mean the worker left no usable result line. `blocked` and `stopped` raise none: a
    blocked worker asked a question, which reaches the operator on the ticket or as `awaiting_reply`, and the operator
    stopped a stopped one (DESIGN §22).

    Returns:
        The reason, or None for a status a human need not look at.
    """
    match status:
        case RunStatus.CRASHED:
            return "crashed"
        case RunStatus.UNPUSHED:
            return "unpushed"
        case RunStatus.UNKNOWN | RunStatus.TIMEOUT:
            return "unknown_result"
        case RunStatus.FAILED:
            return "worker_failed"
        case RunStatus.RUNNING | RunStatus.DONE | RunStatus.BLOCKED | RunStatus.STOPPED:
            return None
        case _:
            assert_never(status)


# A tick that found `canopy` not working for the overseer closes with this status and raises this item (DESIGN §6).
UNAVAILABLE: str = TickStatus.CANOPY_UNAVAILABLE
#: A review judged `high` the PR of a ticket whose plan a triage waived (DESIGN §25, A second opinion after).
NOT_TRIVIAL = "not_trivial"
# What the harness records itself (`tick._record_harness_items`, and `UNAVAILABLE`), so the overseer does not.
HARNESS_REASONS = frozenset(
    {
        *filter(None, map(run_reason, RunStatus)),
        "awaiting_reply",
        NOT_TRIVIAL,
        chore_view.FAILED_REASON,
        "repo_missing",
        UNAVAILABLE,
        *memory.HARNESS_REASONS,
        drafted.WAITING_REASON,
    }
)
# The window the list reads: how far back to look when working out how long an item has been open. Garbage
# collection keeps every row of a tick inside it (DESIGN §26).
HISTORY_TICKS = 1000
FILE_NAME = "attention.md"
# Kept importable from here: tests and the CLI name items through this module.
__all__ = [
    "ACTION_PREFIX",
    "CHORE_PREFIX",
    "FILE_NAME",
    "Item",
    "age",
    "current",
    "fingerprint",
    "keys",
    "listed",
    "subject",
]


def decided_about(decision: records.Decision) -> str:
    """Name what a decision is about, for display: its ticket, `chore:<name>`, its repository, or `-` for the tick.

    Returns:
        The chore with its prefix, else the PR with its prefix when there is no ticket, else the ticket key, else the
        repository, else `-`.
    """
    if decision.chore is not None:
        return f"{CHORE_PREFIX}{decision.chore}"
    if decision.ticket_key is None and decision.pr is not None:
        return f"{PR_PREFIX}{decision.pr}"
    return decision.ticket_key or decision.repo or "-"


# An item is its ticket, its reason, and its repository if it has one.
_ItemId = tuple[str | None, str, str | None]


def keys(items: Iterable[Item]) -> set[_ItemId]:
    """Each item's identity, as two lists are compared: its ticket, its reason, and its repository.

    Returns:
        The set of `(ticket_key, reason, repo)` tuples, one per distinct item.
    """
    return {(i.ticket_key, i.reason, i.repo) for i in items}


def _sort_key(item_id: _ItemId) -> tuple[str, str, str]:
    return (item_id[0] or "", item_id[1], item_id[2] or "")


def current(conn: sqlite3.Connection) -> list[Item]:
    """Return the current attention list, sorted by ticket key and reason."""
    ticks = [
        int(r[0])
        for r in conn.execute(
            "SELECT id FROM ticks WHERE status = 'ok' ORDER BY id DESC LIMIT ?",
            (HISTORY_TICKS,),
        )
    ]
    if not ticks:
        return _unavailable(conn, None)
    # Only the placeholder count is interpolated; the tick ids are bound parameters.
    rows = conn.execute(
        f"SELECT tick_id, ticket_key, action, rationale, created_at, repo, chore, pr FROM decisions "  # noqa: S608
        f"WHERE action LIKE 'attention:%' AND tick_id IN ({','.join('?' * len(ticks))}) ORDER BY id",
        ticks,
    ).fetchall()
    by_tick: dict[int, dict[_ItemId, tuple[str, str]]] = {t: {} for t in ticks}
    for r in rows:
        key = None if r["ticket_key"] is None else str(r["ticket_key"])
        if r["chore"] is not None:
            key = f"{CHORE_PREFIX}{r['chore']}"
        elif key is None and r["pr"] is not None:
            key = f"{PR_PREFIX}{r['pr']}"
        repo = None if r["repo"] is None else str(r["repo"])
        item_id: _ItemId = (key, str(r["action"]).removeprefix(ACTION_PREFIX), repo)
        by_tick[int(r["tick_id"])].setdefault(item_id, (str(r["rationale"]), str(r["created_at"])))

    latest = by_tick[ticks[0]]
    items: list[Item] = []
    for item_id in sorted(latest, key=_sort_key):
        detail, since = latest[item_id]
        for tick_id in ticks[1:]:
            earlier = by_tick[tick_id].get(item_id)
            if earlier is None:
                break
            since = earlier[1]
        items.append(Item(item_id[0], item_id[1], detail, since, item_id[2]))
    return items + _unavailable(conn, ticks[0])


def _unavailable(conn: sqlite3.Connection, last_ok: int | None) -> list[Item]:
    """The `canopy_unavailable` item, while the latest ended tick closed so (DESIGN §6 step 5).

    That tick ran no overseer, so it leaves the list standing as a failed tick does, and adds this one item: the cause
    is canopy's own, and the operator hears of it at once rather than after `loop.failing`'s streak. It is gone at the
    first tick that ends otherwise.

    Returns:
        The item, open since the first tick of the streak after `last_ok`, or nothing.
    """
    latest = conn.execute("SELECT status FROM ticks WHERE status != 'running' ORDER BY id DESC LIMIT 1").fetchone()
    if latest is None or latest[0] != UNAVAILABLE:
        return []
    rows = conn.execute(
        "SELECT rationale, created_at FROM decisions WHERE action = ? AND tick_id > ? ORDER BY id",
        (f"{ACTION_PREFIX}{UNAVAILABLE}", last_ok or 0),
    ).fetchall()
    if not rows:
        return []
    return [Item(None, UNAVAILABLE, str(rows[-1]["rationale"]), str(rows[0]["created_at"]))]


class OpenItem(TypedDict):
    """An open item the overseer recorded: its ticket, or its PR when it has none, and its repository if it has one."""

    ticket: NotRequired[str | None]
    pr: NotRequired[str]
    repo: NotRequired[str]
    reason: str
    since: str


def for_overseer(conn: sqlite3.Connection) -> list[OpenItem]:
    """The open items the overseer recorded, for its state block (DESIGN §6 step 4, ROADMAP M28).

    An item stays open only while each tick records it again, so the overseer is shown what it would drop by leaving
    one out. Items the harness raises itself, and chores', are left out: the overseer never records those. So is
    every detail, which may quote a comment: the item's subject, reason, and age say which one it is.

    Returns:
        One object per item: its ticket, or its PR when it has no ticket; its repository when it has one; its reason;
        and since when it has been open.
    """
    found: list[OpenItem] = []
    for item in current(conn):
        key = item.ticket_key
        if item.reason in HARNESS_REASONS or (key is not None and key.startswith(CHORE_PREFIX)):
            continue
        found.append(
            {
                **(
                    {"pr": key.removeprefix(PR_PREFIX)}
                    if key is not None and key.startswith(PR_PREFIX)
                    else {"ticket": key}
                ),
                **({"repo": item.repo} if item.repo is not None else {}),
                "reason": item.reason,
                "since": item.since,
            }
        )
    return found


def listed(ctx: Context) -> list[Item]:
    """Return the attention list as it is shown and notified: `current`, with the chores this workspace runs.

    A chore deleted from the config, or one whose workspaces leave this one out, is not listed at all, nor is a finding
    the operator dismissed (DESIGN §19).
    """
    configured = set(chore_view.configured(ctx.config, ctx.workspace))
    items = [
        i
        for i in current(ctx.conn)
        if i.ticket_key is None
        or not i.ticket_key.startswith(CHORE_PREFIX)
        or i.ticket_key.removeprefix(CHORE_PREFIX) in configured
    ]
    findings = [
        Item(
            f"{CHORE_PREFIX}{f.chore}",
            f.finding.id,
            " ".join(part for part in (f.finding.title, f.finding.link or "") if part),
            f.since,
            finding=True,
        )
        for f in chore_view.open_findings(ctx.conn, ctx.config, ctx.workspace, starts=ctx.finding_starts)
        if not f.dismissed
    ]
    return items + findings


@dataclass(frozen=True)
class RunItem:
    """An attention item the harness raises for a run."""

    ticket_key: str
    reason: str
    detail: str


def from_runs(conn: sqlite3.Connection) -> list[RunItem]:
    """Return an item for each open ticket whose latest run ended in a status that raises a `run_reason`.

    The cause holds until a newer run starts for the ticket, the ticket is marked done, or the operator forgets its
    work. It is set aside while the operator has stopped the ticket, which nothing dispatches, so no reply could answer
    it, and holds again once they start it (DESIGN §14, §22). A triage raises none, however it ended: the ticket is
    planned next, as if triage were off (DESIGN §25, Triage before a plan).
    """
    done = {str(r[0]) for r in conn.execute("SELECT key FROM tickets WHERE done = 1")}
    stopped = set(conversation.stopped(conn))
    items: list[RunItem] = []
    for key, run in sorted(db.latest_runs(conn).items()):
        reason = run_reason(RunStatus(run["status"]))
        if reason is None or key in done or key in stopped or run["kind"] == RunKind.NEEDS_PLAN:
            continue
        items.append(RunItem(key, reason, _detail(run)))
    return items


def _detail(run: sqlite3.Row) -> str:
    note = contract.stored_note(contract.stored_object(run["result_json"]))
    # A split works on no branch. The run is named as `canopy show` reads it, and as the web UI names it.
    what = f"{run['kind']}, {run['branch']}" if run["branch"] else str(run["kind"])
    text = f"run:{run['id']} ({what}) ended {run['status']}"
    if note:
        text += f": {note}"
    return f"{text}; log {run['log_path']}"[:2000]


@dataclass(frozen=True)
class UnitItem:
    """An attention item the harness raises about one unit of a ticket: its work in one repository (DESIGN §18)."""

    ticket_key: str
    #: The unit's repository.
    repo: str | None
    reason: str
    detail: str


def not_trivial(conn: sqlite3.Connection) -> list[UnitItem]:
    """Return a `not_trivial` item for each unit whose PR a review judged `high` while a triage waived its plan.

    Any `done` review of the unit's PR counts, whatever it was run for: the reviewer is not told of the waiver, so its
    impact is a second opinion on the triage's `trivial`. The cause holds until the ticket is marked done, or the
    waiver is no longer in force: forgotten, or replaced by the operator's own setting. The item stops nothing; the
    PR's review is still the gate (DESIGN §25, A second opinion after).

    Returns:
        One item per unit, naming its newest `high` review and the triage run's reason, sorted by ticket and repository.
    """
    rows = conn.execute(
        "SELECT r.id, r.pr_url, r.result_json, u.ticket_key, u.repo FROM review_runs r "
        "JOIN ticket_units u ON u.pr_url = r.pr_url AND (r.repo IS NULL OR u.repo IS NULL OR r.repo = u.repo) "
        "JOIN tickets t ON t.key = u.ticket_key "
        "WHERE r.status = ? AND t.done = 0 AND u.ticket_key IN (SELECT ticket_key FROM plan_waivers) ORDER BY r.id",
        (ReviewRunStatus.DONE,),
    ).fetchall()
    found: dict[tuple[str, str | None], UnitItem] = {}
    for row in rows:
        stored = review_result.stored(row["result_json"])
        ticket = db.get_ticket(conn, str(row["ticket_key"]))
        waived = plans.waiver(conn, ticket) if ticket is not None else None
        if stored is None or stored.impact != "high" or waived is None:
            continue
        key, repo = str(row["ticket_key"]), None if row["repo"] is None else str(row["repo"])
        detail = (
            f"review:{row['id']} judged {row['pr_url']} high impact, but triage run:{waived.run_id} waived its plan "
            f"as trivial: {one_line(waived.reason)}"
        )
        # The newest high review names the item: rows come oldest first.
        found[key, repo] = UnitItem(key, repo, NOT_TRIVIAL, detail[:2000])
    return [found[k] for k in sorted(found, key=lambda k: (k[0], k[1] or ""))]


def awaiting_detail(waiting: conversation.Awaiting) -> str:
    """The `awaiting_reply` item's detail: the question, and how to answer it (DESIGN §22).

    Returns:
        The message id and the question on one line, cut to 1800 characters, then the `canopy reply` to answer it.
    """
    text = f"message {waiting.message_id}: {one_line(waiting.question)}"
    return f"{text[:1800]}; answer with `canopy reply {waiting.key}`"


def render(items: Sequence[Item], now: datetime, more: Mapping[str, int] | None = None) -> str:
    """Return `attention.md`: the items grouped by reason, one line each with key, age, and detail.

    `more` holds, by `chore:<name>`, how many findings a chore's latest `ok` run found past its `max_findings` and did
    not list (DESIGN §19), said in the chore's section after the ones it did.
    """
    more = {chore: n for chore, n in (more or {}).items() if n > 0}
    stamp = now.astimezone(UTC).strftime("%Y-%m-%d %H:%M UTC")
    lines = ["# canopy attention", ""]
    if not items:
        # A count of findings not listed is no item: the list still needs nothing, and says so above it.
        lines += [f"Nothing needs you. Updated {stamp}.", ""]
        if not more:
            return "\n".join(lines)
    else:
        count = f"{len(items)} item{'s' if len(items) != 1 else ''}"
        lines += [f"{count}, updated {stamp}. An item leaves this list when its cause is gone.", ""]
    reasons = [i for i in items if not i.finding]
    for reason in sorted({i.reason for i in reasons}):
        lines += [f"## {reason}", ""]
        lines += [f"- {i.subject}, {age(i.since, now)}: {one_line(i.detail)}" for i in reasons if i.reason == reason]
        lines.append("")
    # A section per chore after the ticket items: one line per finding, with its title, age, and link (DESIGN §19).
    findings = [i for i in items if i.finding]
    for chore in sorted({i.subject for i in findings} | set(more)):
        lines += [f"## {chore}", ""]
        lines += [f"- {one_line(i.detail)}, {age(i.since, now)} ({i.reason})" for i in findings if i.subject == chore]
        if chore in more:
            lines.append(f"- {more_text(more[chore])}")
        lines.append("")
    return "\n".join(lines)


def more_text(count: int) -> str:
    """Say that a chore found `count` findings past its `max_findings` and did not list them (DESIGN §19).

    Returns:
        The sentence `attention.md`, `canopy status`, and `canopy show` say it in.
    """
    return f"{count} more finding{'s' if count != 1 else ''} not listed, past the chore's max_findings"


def publish(ctx: Context, log: logs.TickAdapter) -> None:
    """Rewrite `attention.md` and deliver to the notification sinks (DESIGN §6 step 7, §20).

    Failures are logged, never raised: the tick is already closed. A delivery that fails is tried again next tick.
    """
    items = write(ctx, log)
    dismissed = {
        fingerprint(f"{CHORE_PREFIX}{f.chore}", f.finding.id, None)
        for f in chore_view.open_findings(ctx.conn, ctx.config, ctx.workspace)
        if f.dismissed
    }
    try:
        deliver.publish(ctx, items, ctx.state_dir / FILE_NAME, log, dismissed=dismissed)
    except Exception as e:
        log.exception("notification failed", extra={"error": str(e)})


def write(ctx: Context, log: logs.TickAdapter) -> list[Item]:
    """Rewrite `attention.md` from the journal: after a tick, and after the operator dismisses a finding.

    A failure is logged, never raised.

    Returns:
        The list as written.
    """
    items = listed(ctx)
    more = {
        f"{CHORE_PREFIX}{state.name}": state.more_findings()
        for state in chore_view.states(ctx.conn, ctx.config, ctx.workspace, starts=ctx.finding_starts)
    }
    path = ctx.state_dir / FILE_NAME
    try:
        logs.write_private(path, render(items, datetime.now(UTC), more))
    except OSError as e:
        log.error("could not write the attention list", extra={"path": str(path), "error": str(e)})  # noqa: TRY400
    return items
