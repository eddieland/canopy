"""The attention list: what needs a human, derived from the journal (DESIGN §14).

Attention items are decisions with action `attention:<reason>`, recorded every tick the cause holds: by the overseer
for what it reads in the world, and by the harness for runs that ended in a way a human must look at (`from_runs`). The
current list is therefore the items of the latest `ok` tick; an item disappears when a tick no longer records it. One
the overseer recorded is held through a tick that did not give the overseer its subject, such as a ticket the harness
decided, or any subject in a tick that ran no overseer, and goes once its ticket is done or stopped (`current`, DESIGN
§37, §39). A tick that could not
run the overseer because `canopy` does not work for it, or its model cannot be used (§13), adds one item of its own to
that list, while it is the latest tick.

A chore's open findings are on the list too, from its latest `ok` run, and a chore whose latest run failed has a
`chore_failed` item the harness records each tick (DESIGN §19). Both are about a chore, named `chore:<name>` where a
ticket key would be, which no ticket key can equal. Only chores configured for this workspace are listed, and no
finding the operator dismissed (`listed`). A one-off task whose run asked a question waits on the operator's reply: its
`awaiting_reply` item is read from the journal as it is listed, named `task:<id>` where a ticket key would be, and
gone once they reply or stop it (DESIGN §36); so is `task_ticket_unrecorded`, for tickets a task's run reported that
canopy did not record.

After every tick, `publish` rewrites `<state_dir>/attention.md` and hands the list to the notification sinks
(`canopy.notify`), each told about each open item once however many ticks it lasts (DESIGN §20).
"""

from __future__ import annotations

import sqlite3
from collections.abc import Collection, Iterable, Mapping, Sequence
from collections.abc import Set as AbstractSet
from dataclasses import dataclass, replace
from datetime import UTC, datetime
from typing import TYPE_CHECKING, NotRequired, TypedDict, assert_never

from canopy.core import (
    artifact_authority,
    chore_result,
    chore_view,
    connector_runs,
    contract,
    conversation,
    db,
    follow_ups,
    memory,
    sql,
    task_tickets,
    tasks,
)
from canopy.core.items import Item, age, fingerprint, one_line, subject
from canopy.core.vocab import Decider, RunKind, RunStatus, TickStatus
from canopy.infra import logs
from canopy.infra.text import printable
from canopy.loop import archive
from canopy.notify import deliver
from canopy.reviews import impact as review_impact
from canopy.reviews import waiting as review_waiting
from canopy.runs import drafted

if TYPE_CHECKING:
    from canopy.core import records
    from canopy.core.context import Context

ACTION_PREFIX = "attention:"
# Where a ticket key would be, an item about a chore names it so, and one about a PR with no ticket. A ticket key has
# no colon (DESIGN §17), so neither can equal one.
CHORE_PREFIX = "chore:"
PR_PREFIX = "pr:"
#: Where a ticket key would be, an item about a one-off task names it so (DESIGN §36).
TASK_PREFIX = "task:"
#: What the overseer's verb about a ticket the harness decided records, refused (DESIGN §37, `loop.tools`).
REFUSED_DECIDED = "refused:decided"


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
#: A tick that found too little free disk closes with this status and raises this item (DESIGN §6).
DISK_LOW: str = TickStatus.DISK_LOW
#: The statuses of a tick that did not run the overseer for a cause of canopy's own, each raising an item of its name.
HALTS = frozenset({UNAVAILABLE, DISK_LOW})
#: The statuses of a tick that did not run the overseer because its chosen model cannot be used (DESIGN §13), each
#: raising an item of its name. Kept out of `HALTS` and `HARNESS_REASONS`: a dispatch's refusal raises an item of the
#: same name about its ticket, which the overseer recorded.
MODEL_HALTS: frozenset[str] = frozenset({TickStatus.MODEL_MISSING, TickStatus.MODEL_LIST_FAILED})
#: A primary clone whose own config leaves git's automatic maintenance on, which sync turns off (DESIGN §18).
MAINTENANCE_ON = "auto_maintenance_on"
#: A git on `PATH` too old to put canopy's marks on a worker's commits (TRUST_MODEL T5).
GIT_TOO_OLD = "git_too_old"
# What the harness records itself (`tick._record_harness_items`, and `HALTS`), so the overseer does not.
HARNESS_REASONS = frozenset(
    {
        *filter(None, map(run_reason, RunStatus)),
        "awaiting_reply",
        chore_view.FAILED_REASON,
        "repo_missing",
        MAINTENANCE_ON,
        GIT_TOO_OLD,
        *HALTS,
        connector_runs.FAILED_REASON,
        archive.REASON,
        *memory.HARNESS_REASONS,
        drafted.WAITING_REASON,
        *review_waiting.REASONS,
        follow_ups.REASON,
        task_tickets.REASON,
        artifact_authority.REASON,
    },
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
    """Return the current attention list, sorted by ticket key and reason.

    It is the latest `ok` tick's items, each open since the first tick of its unbroken run. An item the harness raises
    is recorded every tick its cause holds, so it is open only while the latest `ok` tick recorded it. One the overseer
    recorded is held besides through every `ok` tick that did not give the overseer its subject (`_gave`), such as a
    ticket the harness decided there (DESIGN §37), or one that ran no overseer at all (§39): the overseer cannot record
    again what it was not shown. It goes the
    first tick the overseer is given its subject and leaves it out, or once its ticket is done or stopped.
    """
    rows = sql.execute(
        conn,
        sql.select("id, overseer_ran").from_("ticks").where("status = 'ok'").order_by("id DESC").limit(HISTORY_TICKS),
    ).fetchall()
    ticks = [int(r[0]) for r in rows]
    if not ticks:
        return _halted(conn, None)
    by_tick = _recorded(conn, ticks)
    subjects = {i[0] for found in by_tick.values() for i, r in found.items() if r.held and i[0] is not None}
    given = _given(conn, ticks, subjects)
    # A tick from before it was recorded that closed `ok` ran its overseer (DESIGN §39).
    ran = frozenset(int(r[0]) for r in rows if r[1] != 0)
    open_items: dict[_ItemId, _Open] = {}
    for tick_id in reversed(ticks):
        now: dict[_ItemId, _Open] = {}
        for item_id, r in by_tick[tick_id].items():
            earlier = open_items.get(item_id)
            now[item_id] = r if earlier is None else replace(r, since=earlier.since)
        for item_id, r in open_items.items():
            if item_id not in now and r.held and not _gave(item_id[0], tick_id, given, ran):
                now[item_id] = r
        open_items = now
    ended = _ended(conn, {i[0] for i, r in open_items.items() if r.held and i[0] is not None})
    halted = _halted(conn, ticks[0])
    # A halt's item stands in for the same item the latest `ok` tick recorded, such as tasks waiting on the same model.
    shadowed = keys(halted)
    items = [
        Item(i[0], i[1], r.detail, r.since, i[2])
        for i, r in sorted(open_items.items(), key=lambda found: _sort_key(found[0]))
        if not (r.held and i[0] in ended) and i not in shadowed
    ]
    return items + halted


@dataclass(frozen=True)
class _Open:
    """An item as the ticks up to one left it (`current`)."""

    #: Its detail, as the newest tick that recorded it worded it.
    detail: str
    #: When the first tick of its unbroken run recorded it.
    since: str
    #: Whether the overseer recorded it, so it is held through a tick that did not give the overseer its subject.
    held: bool


def _recorded(conn: sqlite3.Connection, ticks: Collection[int]) -> dict[int, dict[_ItemId, _Open]]:
    """The attention items each of `ticks` recorded, each as its first row there words it.

    Returns:
        By tick, each item, held when the overseer recorded it there: a reason the harness does not raise, recorded
        other than by the harness.
    """
    rows = sql.execute(
        conn,
        sql.select("tick_id, ticket_key, action, rationale, created_at, repo, chore, pr, decider")
        .from_("decisions")
        .where("action LIKE 'attention:%'")
        .where_in("tick_id", ticks)
        .order_by("id"),
    ).fetchall()
    by_tick: dict[int, dict[_ItemId, _Open]] = {t: {} for t in ticks}
    for r in rows:
        key = None if r["ticket_key"] is None else str(r["ticket_key"])
        if r["chore"] is not None:
            key = f"{CHORE_PREFIX}{r['chore']}"
        elif key is None and r["pr"] is not None:
            key = f"{PR_PREFIX}{r['pr']}"
        repo = None if r["repo"] is None else str(r["repo"])
        reason = str(r["action"]).removeprefix(ACTION_PREFIX)
        item_id: _ItemId = (key, reason, repo)
        held = r["decider"] != Decider.HARNESS and reason not in HARNESS_REASONS
        found = by_tick[int(r["tick_id"])]
        first = found.get(item_id)
        if first is None:
            found[item_id] = _Open(str(r["rationale"]), str(r["created_at"]), held=held)
        elif held and not first.held:
            found[item_id] = replace(first, held=True)
    return by_tick


def _given(conn: sqlite3.Connection, ticks: Collection[int], keys: Collection[str]) -> dict[int, set[str]]:
    """Which of tickets `keys` the overseer was given in each of `ticks`: those it recorded a decision about there.

    An `ok` tick has a decision about every ticket its state block listed, or its duties check would have failed it
    (DESIGN §6 step 5). A mirror decides nothing, and a refusal `decided` is about a ticket the harness took, which
    the overseer was not shown; neither counts, nor anything the harness recorded.

    Returns:
        By tick, the keys.
    """
    found: dict[int, set[str]] = {t: set() for t in ticks}
    if not keys:
        return found
    rows = sql.execute(
        conn,
        sql.select("tick_id, ticket_key, action, decider")
        .from_("decisions")
        .where_in("tick_id", ticks)
        .where_in("ticket_key", keys)
        .where("action NOT IN (?, ?)", conversation.MIRROR_ACTION, REFUSED_DECIDED),
    ).fetchall()
    for r in rows:
        action = str(r["action"])
        raised = action.startswith(ACTION_PREFIX) and action.removeprefix(ACTION_PREFIX) in HARNESS_REASONS
        if r["decider"] != Decider.HARNESS and not raised:
            found[int(r["tick_id"])].add(str(r["ticket_key"]))
    return found


def _gave(key: str | None, tick_id: int, given: Mapping[int, AbstractSet[str]], ran: AbstractSet[int]) -> bool:
    """Whether tick `tick_id` gave the overseer `key`, the subject of an item it recorded (`current`).

    A ticket is given where the overseer recorded a decision about it (`_given`); a PR, a chore, or the workspace
    wherever the overseer ran.

    Returns:
        True when an item the tick left out ends there.
    """
    if key is None or key.startswith((PR_PREFIX, CHORE_PREFIX)):
        return tick_id in ran
    return key in given[tick_id]


def _ended(conn: sqlite3.Connection, keys: Collection[str]) -> set[str]:
    """Which of `keys` an item the overseer recorded is no longer about: done, or stopped by the operator (§37).

    Returns:
        Their keys.
    """
    if not keys:
        return set()
    done = sql.select("key").from_("tickets").where("done = 1").where_in("key", keys)
    stopped = (
        sql.select("subject_id")
        .from_("starts")
        .where("subject_kind = ? AND status = 'stopped'", conversation.TICKET)
        .where_in("subject_id", keys)
    )
    return {str(r[0]) for r in sql.execute(conn, done)} | {str(r[0]) for r in sql.execute(conn, stopped)}


def _halted(conn: sqlite3.Connection, last_ok: int | None) -> list[Item]:
    """The item of a `HALTS` or `MODEL_HALTS` status while the latest ended tick closed with it (DESIGN §6 step 5).

    That tick ran no overseer, so it leaves the list standing as a failed tick does, and adds this one item: the cause
    is canopy's own, and the operator hears of it at once rather than after `loop.failing`'s streak. It is gone at the
    first tick that ends otherwise.

    Returns:
        The item, open since the first tick after `last_ok` that raised it, or nothing.
    """
    latest = sql.execute(
        conn,
        sql.select("status").from_("ticks").where("status != 'running'").order_by("id DESC").limit(1),
    ).fetchone()
    if latest is None or latest[0] not in HALTS | MODEL_HALTS:
        return []
    reason = str(latest[0])
    # Only the halted ticks' own items: a refusal in another tick may raise an item of the same name.
    rows = sql.execute(
        conn,
        sql.select("rationale, created_at")
        .from_("decisions")
        .where("action = ? AND tick_id > ?", f"{ACTION_PREFIX}{reason}", last_ok or 0)
        .where("tick_id IN (SELECT id FROM ticks WHERE status = ?)", reason)
        .order_by("id"),
    ).fetchall()
    if not rows:
        return []
    return [Item(None, reason, str(rows[-1]["rationale"]), str(rows[0]["created_at"]))]


class OpenItem(TypedDict):
    """An open item the overseer recorded: its ticket, or its PR when it has none, and its repository if it has one."""

    ticket: NotRequired[str | None]
    pr: NotRequired[str]
    repo: NotRequired[str]
    reason: str
    since: str


def for_overseer(conn: sqlite3.Connection, *, decided: AbstractSet[str] = frozenset()) -> list[OpenItem]:
    """The open items the overseer recorded, for its state block (DESIGN §6 step 4, ROADMAP M28).

    An item stays open only while each tick that gives the overseer its subject records it again, so the overseer is
    shown what it would drop by leaving one out. Items the harness raises itself, and chores', are left out: the
    overseer never records those, nor one about no ticket and no PR, such as the item of a model tasks wait on. So
    are those about `decided`, the tickets the harness decided this tick, which the block does not list and which hold
    their items until the overseer is given them again (`current`). So is every detail, which may quote a comment: the
    item's subject, reason, and age say which one it is.

    Returns:
        One object per item: its ticket, or its PR when it has no ticket; its repository when it has one; its reason;
        and since when it has been open.
    """
    found: list[OpenItem] = []
    for item in current(conn):
        key = item.ticket_key
        if key is None or item.reason in HARNESS_REASONS or key.startswith(CHORE_PREFIX) or key in decided:
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
            },
        )
    return found


def listed(ctx: Context) -> list[Item]:
    """Return the attention list as it is shown and notified: `current`, with the chores this workspace runs.

    A chore deleted from the config, or one whose workspaces leave this one out, is not listed at all, nor is a finding
    the operator dismissed (DESIGN §19). A `drafts_waiting` item says what waits now, not at the tick that recorded
    it, so one the operator sent or dropped every draft of is gone at once (DESIGN §29), and so do a review's
    `review_waiting` and `review_unsettled`, gone once the operator publishes or a read settles it (§34). So do a
    task's `awaiting_reply` and `task_ticket_unrecorded`, which no tick records (DESIGN §36). An item about a PR whose
    latest review is `high` impact, or about its ticket, comes before the rest (§21), so a notification lists it first.
    """
    configured = set(chore_view.configured(ctx.config, ctx.workspace))
    items = [
        i
        for i in _reviews_now(ctx.conn, _drafts_now(ctx.conn, current(ctx.conn)))
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
    waiting = [_task_item(w) for w in tasks.awaiting(ctx.conn)]
    unrecorded = [_unrecorded_item(u) for u in task_tickets.unrecorded(ctx.conn)]
    return _high_first(ctx.conn, items) + waiting + unrecorded + findings


def _high_first(conn: sqlite3.Connection, items: Sequence[Item]) -> list[Item]:
    """The items about a PR, or its ticket, whose latest reviewed commit has a `high` review first (DESIGN §21).

    Returns:
        `items` in their order, but each such item before every other.
    """
    prs = {i.ticket_key.removeprefix(PR_PREFIX) for i in items if i.ticket_key and i.ticket_key.startswith(PR_PREFIX)}
    tickets = {i.ticket_key for i in items if i.ticket_key and ":" not in i.ticket_key}
    found = review_impact.high(conn, tickets, prs)
    ranked = {*found.tickets, *(f"{PR_PREFIX}{url}" for url in found.prs)}
    return sorted(items, key=lambda i: i.ticket_key not in ranked)


def _task_item(waiting: tasks.Awaiting) -> Item:
    """A task's `awaiting_reply` item: it names the task and where to read its question, never the question (§36).

    Returns:
        The item, open since the run asked.
    """
    ref = f"{TASK_PREFIX}{waiting.task_id}"
    run = f"run {waiting.run_id}" if waiting.run_id is not None else "a run"
    detail = (
        f"{ref}'s {run} asked you a question, message {waiting.message_id}: read it with `canopy show {ref}`, "
        f"and answer with `canopy reply {ref}`"
    )
    return Item(ref, "awaiting_reply", detail, waiting.at)


def _unrecorded_item(found: task_tickets.Unrecorded) -> Item:
    """A task's `task_ticket_unrecorded` item: it names the task, its run, and how many, never the keys (§36).

    Returns:
        The item, open since the run ended.
    """
    ref = f"{TASK_PREFIX}{found.task_id}"
    entries = f"{found.count} {'ticket' if found.count == 1 else 'tickets'}"
    detail = (
        f"{ref}'s run {found.run_id} reported {entries} that canopy did not record against it: "
        f"`canopy show {ref}` names each and why. It clears when you reply to the task or stop it"
    )
    return Item(ref, task_tickets.REASON, detail, found.at)


def _drafts_now(conn: sqlite3.Connection, items: Iterable[Item]) -> list[Item]:
    """Check each `drafts_waiting` item against the drafts as they stand, not as the tick that recorded it saw them.

    An item that starts to wait again, a drop taken back, is listed from the next tick, which records its age.

    Returns:
        The items in order, each `drafts_waiting` one with the drafts that wait now, or left out when none still does.
    """
    waiting: dict[tuple[str, str | None], str] = {}
    for w in drafted.waiting(conn):
        # The tick records the first of a unit's items, as `current` keeps it.
        waiting.setdefault((w.ticket_key, w.repo), w.detail)
    found: list[Item] = []
    for item in items:
        if item.reason != drafted.WAITING_REASON or item.ticket_key is None:
            found.append(item)
        elif (detail := waiting.get((item.ticket_key, item.repo))) is not None:
            found.append(replace(item, detail=detail))
    return found


def _reviews_now(conn: sqlite3.Connection, items: Iterable[Item]) -> list[Item]:
    """Check each review's item against its drafts as they stand, as `_drafts_now` does a run's drafts.

    Returns:
        The items in order, each review's with what it says now, or left out once its cause is gone.
    """
    now = {(i.ticket or f"{PR_PREFIX}{i.pr}", i.reason): i.detail for i in review_waiting.items(conn)}
    found: list[Item] = []
    for item in items:
        if item.reason not in review_waiting.REASONS:
            found.append(item)
        elif (detail := now.get((item.ticket_key or "", item.reason))) is not None:
            found.append(replace(item, detail=detail))
    return found


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
    it, and holds again once they start it (DESIGN §14, §22). An old triage raises none, however it ended: the ticket
    is planned next (M55).
    """
    done = {str(r[0]) for r in sql.execute(conn, sql.select("key").from_("tickets").where("done = 1"))}
    stopped = set(conversation.stopped(conn))
    items: list[RunItem] = []
    for key, run in sorted(db.latest_runs(conn).items()):
        reason = run_reason(run.status)
        if reason is None or key in done or key in stopped or run.kind == RunKind.NEEDS_PLAN:
            continue
        items.append(RunItem(key, reason, _detail(run)))
    return items


def _detail(run: records.Run) -> str:
    note = contract.stored_note(contract.stored_object(run.result_json))
    # A plan works on no branch. The run is named as `canopy show` reads it, and as the web UI names it.
    what = f"{run.kind}, {run.branch}" if run.branch else str(run.kind)
    text = f"run:{run.id} ({what}) ended {run.status}"
    if note:
        text += f": {note}"
    return f"{text}; log {run.log_path}"[:2000]


def awaiting_detail(waiting: conversation.Awaiting) -> str:
    """The `awaiting_reply` item's detail: the question, and how to answer it (DESIGN §22).

    Returns:
        The message id and the question, its line breaks kept, cut to 1800 characters, then the `canopy reply` to
        answer it.
    """
    text = f"message {waiting.message_id}: {printable(waiting.question).strip()}"
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
            lines.append(f"- {chore_result.more_text(more[chore])}")
        lines.append("")
    return "\n".join(lines)


def publish(ctx: Context, log: logs.TickAdapter, *, ui: str | None = None) -> None:
    """Rewrite `attention.md` and deliver to the notification sinks (DESIGN §6 step 7, §20), linking to `ui` if set.

    Failures are logged, never raised: the tick is already closed. A delivery that fails is tried again next tick.
    """
    items = write(ctx, log)
    dismissed = {
        fingerprint(f"{CHORE_PREFIX}{f.chore}", f.finding.id, None)
        for f in chore_view.open_findings(ctx.conn, ctx.config, ctx.workspace)
        if f.dismissed
    }
    try:
        deliver.publish(ctx, items, ctx.state_dir / FILE_NAME, log, dismissed=dismissed, ui=ui)
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
