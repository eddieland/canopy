"""One message for one sink (DESIGN §20): the attention diff, point events, and a digest, in `text` or `json`.

A message holding only attention is exactly the text `notify.cmd` always got (DESIGN §14), so that command sees no
change. Everything here is built from the journal; no model writes any of it.
"""

from __future__ import annotations

import json
import sqlite3
from collections import Counter
from collections.abc import Collection, Mapping, Sequence
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from pathlib import Path
from typing import TYPE_CHECKING, TypedDict, cast
from urllib.parse import quote

from canopy.core import contract, db, records, spend, sql
from canopy.core.items import Item, age
from canopy.core.vocab import FlakyCause, RunStatus, SessionsRead

if TYPE_CHECKING:
    from canopy.notify.journal import Diff

VERSION = 1
# At most this many attention lines and this many events in one message; the rest are counted, and count as delivered.
MAX_LINES = 20
# Events older than this when a sink next succeeds are counted, not listed.
STALE_EVENTS = timedelta(hours=24)
_DONE_LISTED = 10
# The attention list's subjects that are not tickets: a chore, by `chore:<name>`, a PR, by `pr:<url>`, and a one-off
# task, by `task:<id>`, which has no page of its own yet (DESIGN §36).
_CHORE = "chore:"
_PR = "pr:"
_TASK = "task:"
#: How a `ci.flaky` event's `cause` reads in its line: the worker's estimate, so hedged.
_CAUSES = {
    FlakyCause.TEST: "likely a flaky test",
    FlakyCause.RUNNER: "likely the CI runner",
    FlakyCause.SERVICE: "likely a service the job calls",
}


def _line(text: object) -> str:
    return " ".join(str(text).split())


def event_line(kind: str, fields: Mapping[str, object]) -> str:  # noqa: C901, PLR0911, PLR0912  (one shape per kind)
    """One line of text for an event, for a person.

    Returns:
        The line, led by `>`, `<`, `?`, `+`, `!`, or `*` for the event's kind. A kind it does not know shows its
        fields as JSON.
    """
    f = fields
    if kind == "run.started":
        return (
            f"> {f.get('ticket')} run {f.get('run')} started: {f.get('run_kind')} on {f.get('branch') or '-'} "
            f"(attempt {f.get('attempt')} of {f.get('limit')})"
        )
    if kind == "run.ended":
        text = f"< {f.get('ticket')} run {f.get('run')} {f.get('run_kind')} ended {f.get('status')}"
        extras = [str(x) for x in (f.get("pr"), f.get("summary")) if x]
        if f.get("question"):
            extras.append(f"question: {f.get('question')}")
        return _line(f"{text}: {' '.join(extras)}" if extras else text)
    if kind == "plan.proposed":
        return f"? {f.get('ticket')} plan {f.get('plan')} waits on your approval: canopy show {f.get('ticket')}"
    if kind == "plan.approved":
        which = "feedback plan" if f.get("feedback") else "plan"
        return _line(f"+ {f.get('ticket')} {which} {f.get('plan')} approved by its planner: {f.get('reason')}")
    if kind == "follow_ups.filed":
        given = f.get("follow_ups")
        filed: dict[str, object] = cast("dict[str, object]", given) if isinstance(given, dict) else {}
        named = [f"{k} ({v})" if v else str(k) for k, v in filed.items()]
        count = f.get("count")
        if isinstance(count, int) and count > len(named):
            named.append(f"{count - len(named)} more")
        return _line(
            f"? {f.get('ticket')} run {f.get('run')} filed follow-ups {', '.join(named) or '-'}: "
            "label or `canopy start` each one you want worked",
        )
    if kind == "ci.flaky":
        return _flaky_line(f)
    if kind == "ci.kicked":
        pr = f" {f.get('pr')}" if f.get("pr") else ""
        return _line(
            f"! {f.get('ticket')} run {f.get('run')}: canopy force-pushed {f.get('branch')} in {f.get('repo')} "
            f"to rerun a check left as flaky (kick {f.get('kick')} of {f.get('limit')}): "
            f"{str(f.get('from_head'))[:12]} -> {str(f.get('to_head'))[:12]}{pr}",
        )
    if kind == "task.ended":
        text = f"< task:{f.get('task')} run {f.get('run')} ended {f.get('status')}"
        extras = [str(x) for x in (f.get("pr"), f.get("summary")) if x]
        if f.get("question"):
            extras.append(f"question: {f.get('question')}")
        if f.get("branch") and f.get("head"):
            extras.append(f"{f.get('branch')} at {str(f.get('head'))[:12]}")
        given = f.get("tickets")
        tickets: list[str] = [str(k) for k in cast("list[object]", given)] if isinstance(given, list) else []
        if tickets:
            extras.append(f"filed {', '.join(tickets)}")
        return _line(f"{text}: {' '.join(extras)}" if extras else text)
    if kind == "chore.ended":
        findings = f.get("findings") or 0
        text = f"< chore:{f.get('chore')} run {f.get('run')} ended {f.get('status')} ({findings} findings)"
        return _line(f"{text}: {f.get('summary')}" if f.get("summary") else text)
    if kind == "review.ended":
        ticket = f" ({f.get('ticket')})" if f.get("ticket") else ""
        verdict = " ".join(str(x) for x in (f.get("verdict"), f.get("impact")) if x)
        text = f"< review run {f.get('run')} of {f.get('pr')}{ticket} ended {f.get('status')}"
        findings = f.get("findings") or 0
        return _line(f"{text}: {verdict} ({findings} findings)" if verdict else text)
    if kind == "reply.recorded":
        return _line(f"+ {f.get('ticket')} your reply from Slack recorded: {f.get('body')}")
    if kind == "reply.refused":
        about = f" on {f.get('ticket')}" if f.get("ticket") else ""
        return _line(f"! your reply from Slack{about} not recorded ({f.get('guard')}): {f.get('reason')}")
    if kind == "loop.failing":
        return (
            f"! loop failing: {f.get('count')} ticks in a row ended other than ok; latest tick {f.get('tick')} "
            f"{f.get('status')}, log {f.get('log')}"
        )
    if kind == "loop.recovered":
        return f"! loop recovered after {f.get('failed')} failed ticks"
    if kind == "loop.sink_failing":
        return _line(f"! sink {f.get('sink')} has failed 3 deliveries in a row: {f.get('error')}")
    if kind == "loop.budget_reached":
        return _line(_budget_line(f))
    if kind == "test":
        return _line(f"* {f.get('text')}")
    return _line(f"{kind} {json.dumps(f)}")


def _flaky_line(f: Mapping[str, object]) -> str:
    """The line of a `ci.flaky` event.

    Returns:
        The line, led by `+` when canopy kicked the check, or `?` when it waits on the operator's rerun.
    """
    given = f.get("kicked")
    kicked = [str(r) for r in cast("list[object]", given)] if isinstance(given, list) else []
    given = f.get("prs")
    prs = [str(u) for u in cast("list[object]", given)] if isinstance(given, list) else []
    head = f"{f.get('ticket')} run {f.get('run')} left a failed check as flaky"
    cause = f.get("cause")
    if isinstance(cause, str) and cause in FlakyCause:
        head = f"{head}, {_CAUSES[FlakyCause(cause)]}"
    elif f.get("other_cause"):
        head = f"{head}, cause given as {json.dumps(str(f.get('other_cause')))}, not one canopy knows"
    if kicked:
        text = f"+ {head}; canopy pushed {', '.join(kicked)} again to rerun it"
    else:
        text = f"? {head}; rerun it, or `canopy reply` that it is real"
    extras = [*prs, f"why: {f.get('estimate')}" if f.get("estimate") else "", str(f.get("note") or "")]
    return _line(f"{text}: {' '.join(x for x in extras if x)}")


def item_page(ui: str | None, ticket_key: str | None) -> str | None:
    """The web UI's page for an attention item's subject: its ticket's, chore's, or PR's, else the attention list.

    Returns:
        The page's URL under `ui`, or None when `ui` is None.
    """
    if ticket_key is None or ticket_key.startswith(_TASK):
        return page(ui, "attention")
    if ticket_key.startswith(_CHORE):
        return page(ui, "chores", ticket_key.removeprefix(_CHORE))
    if ticket_key.startswith(_PR):
        return page(ui, "pull-requests", "pr", query=ticket_key.removeprefix(_PR))
    return page(ui, "tickets", ticket_key)


def event_page(ui: str | None, kind: str, fields: Mapping[str, object]) -> str | None:  # noqa: PLR0911  (a page per kind)
    """The web UI's page for what an event is about: a run, a plan, a chore run, a review run, a failed tick, or spend.

    Returns:
        The page's URL under `ui`, or None when `ui` is None or the event is about nothing with a page of its own.
    """
    f = fields
    match kind:
        case "run.started" | "run.ended" | "follow_ups.filed" | "ci.flaky" | "ci.kicked" if f.get("run"):
            return page(ui, "runs", f["run"])
        case "plan.proposed" | "plan.approved" if f.get("ticket"):
            # A feedback plan has no page of its own yet: its ticket's page is where its PRs are.
            return page(ui, "tickets", f["ticket"], *(() if f.get("feedback") else ("plan",)))
        case "reply.recorded" if f.get("ticket"):
            return page(ui, "tickets", f["ticket"])
        case "chore.ended" if f.get("chore") and f.get("run"):
            return page(ui, "chores", f["chore"], "runs", f["run"])
        case "review.ended" if f.get("run"):
            return page(ui, "reviews", f["run"])
        case "loop.failing" if f.get("tick"):
            return page(ui, "ticks", f["tick"])
        case "loop.budget_reached":
            return page(ui, "spend")
        case _:
            return None


def page(ui: str | None, *parts: object, query: str | None = None) -> str | None:
    """A page of the web UI at `ui`, each of `parts` one segment of its path, and `query` its `url` parameter.

    Every part is percent-encoded whole, so no ticket key or chore name can reach another page.

    Returns:
        The page's URL, or None when `ui` is None.
    """
    if ui is None:
        return None
    path = "/".join(quote(str(part), safe="") for part in parts)
    return f"{ui}{path}" + (f"?url={quote(query, safe='')}" if query is not None else "")


@dataclass(frozen=True)
class Event:
    """One event from the outbox, as a message lists it."""

    id: int
    kind: str
    at: str
    fields: Mapping[str, object]

    @classmethod
    def of(cls, row: records.NotifyEvent) -> Event:
        """Read an outbox row.

        Returns:
            The event. Fields that do not parse as a JSON object are read as none.
        """
        try:
            parsed: object = json.loads(row.fields)
        except json.JSONDecodeError:
            parsed = None
        # The event's own keys come first in the `json` format; a field of the same name would shadow them.
        fields = {str(k): v for k, v in parsed.items() if k not in _OWN} if isinstance(parsed, dict) else {}
        return cls(row.id, row.kind, row.at, fields)

    @property
    def line(self) -> str:
        """The event as one line for a person."""
        return event_line(self.kind, self.fields)

    def as_json(self, titles: Mapping[str, str] | None = None, ui: str | None = None) -> dict[str, object]:
        """The event as the `json` format lists it: an event about a ticket also carries its title from `titles`.

        Returns:
            The event's id, kind, time, fields, the ticket's title if it has one, its `line`, and its page in the web
            UI at `ui`, None when there is none.
        """
        ticket = self.fields.get("ticket")
        named = {"title": (titles or {}).get(str(ticket))} if ticket else {}
        own = {"line": self.line, "ui": event_page(ui, self.kind, self.fields)}
        return {"id": self.id, "kind": self.kind, "at": self.at, **self.fields, **named, **own}


_OWN = ("id", "kind", "at", "line", "ui")


class DoneRun(TypedDict):
    """A run that ended `done`, as the digest lists it, with the PRs its result named."""

    ticket: str
    title: str | None
    run: int
    pr: str | None


class BlockedRun(TypedDict):
    """A run that ended `blocked`, as the digest lists it."""

    ticket: str
    title: str | None
    run: int


class DigestAttention(TypedDict):
    """The open attention list in a digest: how many items, how many by reason, and the oldest one's age."""

    open: int
    by_reason: dict[str, int]
    oldest: str | None


class DigestSpend(TypedDict):
    """What the runs that started in a digest's span cost, in US dollars, in total and by kind (DESIGN §11).

    Each is None when none of its runs reported a cost. `idle` is the part of `overseer` that idle ticks spent, and
    `dry_run` the dry runs' overseers, apart from it. `total` counts the sessions outside canopy too.
    """

    total: float | None
    overseer: float | None
    idle: float | None
    dry_run: float | None
    workers: float | None
    plans: float | None
    chores: float | None
    reviews: float | None
    #: The operator's one-off tasks' runs (DESIGN §36).
    tasks: float | None
    #: No run of canopy's: the runtime's sessions outside canopy, as `canopy loop` last read them.
    outside: float | None


class DigestJson(TypedDict):
    """The digest as the `json` format carries it."""

    since: str
    until: str
    ticks: dict[str, int]
    runs_started: dict[str, int]
    runs_ended: dict[str, int]
    done: list[DoneRun]
    blocked: list[BlockedRun]
    attention: DigestAttention
    running: int
    spend: DigestSpend
    lines: list[str]


@dataclass(frozen=True)
class Digest:
    """Progress since a sink's previous digest, from the journal only."""

    since: str
    until: str
    ticks: Mapping[str, int]
    runs_started: Mapping[str, int]
    runs_ended: Mapping[str, int]
    done: Sequence[DoneRun]
    blocked: Sequence[BlockedRun]
    attention: Mapping[str, int]
    oldest: str | None
    running: int
    #: What the runs that started since `since` cost, by kind.
    costs: spend.Costs

    def lines(self) -> list[str]:
        """The digest as lines for a person. Sent even when nothing happened: a missing digest means a dead loop.

        Returns:
            A heading line with the tick counts, then an indented line for each of runs, what they cost, tickets done
            and blocked, attention, and workers running.
        """
        span = f"Digest since {self.since}:"
        ticks = ", ".join(f"{s} {n}" for s, n in sorted(self.ticks.items())) or "none"
        total = sum(self.ticks.values())
        out = [f"{span} {total} ticks ({ticks})"]
        if self.runs_started or self.runs_ended:
            started = ", ".join(f"{k} {n}" for k, n in sorted(self.runs_started.items())) or "none"
            ended = ", ".join(f"{s} {n}" for s, n in sorted(self.runs_ended.items())) or "none"
            out.append(f"  runs started: {started}; ended: {ended}")
        else:
            out.append("  nothing ran")
        out.append(_spend_line(self.costs))
        out += [f"  done {d['ticket']} {d.get('pr') or ''}".rstrip() for d in self.done[:_DONE_LISTED]]
        out += [f"  blocked {b['ticket']}" for b in self.blocked[:_DONE_LISTED]]
        if self.attention:
            reasons = ", ".join(f"{r} {n}" for r, n in sorted(self.attention.items()))
            out.append(f"  attention: {sum(self.attention.values())} open ({reasons}); oldest {self.oldest}")
        else:
            out.append("  nothing needs you")
        out.append(f"  workers running: {self.running}")
        return out

    def as_json(self) -> DigestJson:
        """The digest as the `json` format carries it.

        Returns:
            The digest's fields, attention as its open count, counts by reason, and oldest age, and its `lines`.
        """
        return {
            "since": self.since,
            "until": self.until,
            "ticks": dict(self.ticks),
            "runs_started": dict(self.runs_started),
            "runs_ended": dict(self.runs_ended),
            "done": list(self.done),
            "blocked": list(self.blocked),
            "attention": {
                "open": sum(self.attention.values()),
                "by_reason": dict(self.attention),
                "oldest": self.oldest,
            },
            "running": self.running,
            "spend": {
                "total": self.costs.total,
                "overseer": self.costs.overseer,
                "idle": self.costs.idle,
                "dry_run": self.costs.dry_run,
                "workers": self.costs.workers,
                "plans": self.costs.plans,
                "chores": self.costs.chores,
                "reviews": self.costs.reviews,
                "tasks": self.costs.tasks,
                "outside": self.costs.outside,
            },
            "lines": self.lines(),
        }


# A `loop.budget_reached` event's line: the month's spend against its budget, then canopy's runs' part and the part
# outside canopy, as of when `canopy loop` last read the runtime's sessions, or last tried to, when that read failed.
# An event recorded before it carried the parts names none.
def _budget_line(f: Mapping[str, object]) -> str:
    spent, projected, percent = f.get("spent"), f.get("projected"), f.get("percent")
    so_far = _usd(spent) if isinstance(spent, int | float) else "-"
    pace = f", on pace for {_usd(projected)}" if isinstance(projected, int | float) else ""
    what = "its budget" if percent == spend.FULL else f"{percent}% of its budget"
    text = f"! spend for {f.get('month')} reached {what}: {so_far} of ${f.get('budget')}{pace}"
    runs, outside, read = f.get("runs"), f.get("outside"), f.get("sessions_read_at")
    if not isinstance(runs, int | float):
        return text
    if not isinstance(read, str) or not isinstance(outside, int | float):
        return f"{text}; canopy's runs {_usd(runs)}, outside canopy not read yet"
    at = db.parse_time(read).astimezone().strftime("%Y-%m-%d %H:%M")
    how = "the last read of sessions failed" if f.get("sessions_read") == SessionsRead.FAILED else "sessions read"
    return f"{text}; canopy's runs {_usd(runs)}, outside canopy {_usd(outside)} ({how} {at})"


# The digest's line for what its span cost: the total, then each kind that reported a cost, the idle ticks' part of
# the overseer's beside it, the dry runs', since they are no part of the loop's work, and the sessions outside canopy
# last, since they are none of canopy's.
def _spend_line(costs: spend.Costs) -> str:
    total = costs.total
    if total is None:
        return "  spent: none reported"
    overseer = None
    if costs.overseer is not None:
        overseer = f"overseer {_usd(costs.overseer)}" + (f" (idle {_usd(costs.idle)})" if costs.idle else "")
    kinds = [
        ("workers", costs.workers),
        ("plans", costs.plans),
        ("chores", costs.chores),
        ("reviews", costs.reviews),
        ("tasks", costs.tasks),
    ]
    parts = [overseer] if overseer is not None else []
    rest = (*kinds, ("dry runs", costs.dry_run), ("outside canopy", costs.outside))
    parts += [f"{name} {_usd(usd)}" for name, usd in rest if usd is not None]
    return f"  spent: {_usd(total)} ({', '.join(parts)})"


def _usd(usd: float) -> str:
    return f"${usd:.2f}"


def titles(conn: sqlite3.Connection) -> dict[str, str]:
    """Each named ticket's title by its key (DESIGN §13), for the `json` format to carry beside the key.

    Returns:
        Titles by ticket key. A ticket with no title is left out.
    """
    q = sql.select("key, title").from_("tickets").where("title IS NOT NULL")
    return {str(r[0]): str(r[1]) for r in sql.execute(conn, q)}


def digest(
    conn: sqlite3.Connection,
    items: Collection[Item],
    *,
    since: str,
    now: datetime,
    state_dir: Path,
) -> Digest:
    """Build the digest for the time since `since`: ticks, runs and what they cost, the open attention list, workers.

    Returns:
        The digest, read from the journal and `items` only.
    """
    ticks = Counter(
        str(r[0]) for r in sql.execute(conn, sql.select("status").from_("ticks").where("started_at >= ?", since))
    )
    started = Counter(
        str(r[0]) for r in sql.execute(conn, sql.select("kind").from_("runs").where("started_at >= ?", since))
    )
    ended_rows = records.select(records.Run).where("ended_at >= ?", since).order_by("id").all(conn)
    ended = Counter(str(r.status) for r in ended_rows)
    named = titles(conn)
    done: list[DoneRun] = [
        {"ticket": r.ticket_key, "title": named.get(r.ticket_key), "run": r.id, "pr": _pr(r.result_json)}
        for r in ended_rows
        if r.status is RunStatus.DONE
    ]
    blocked: list[BlockedRun] = [
        {"ticket": r.ticket_key, "title": named.get(r.ticket_key), "run": r.id}
        for r in ended_rows
        if r.status is RunStatus.BLOCKED
    ]
    oldest = min((i.since for i in items), default=None)
    return Digest(
        since=since,
        until=db.format_time(now),
        ticks=dict(ticks),
        runs_started=dict(started),
        runs_ended=dict(ended),
        done=done,
        blocked=blocked,
        attention=dict(Counter(i.reason for i in items)),
        oldest=age(oldest, now) if oldest is not None else None,
        running=len(db.running_runs(conn, "runs")),
        costs=spend.costs(conn, since, db.format_time(now), state_dir=state_dir),
    )


def _pr(result_json: str | None) -> str | None:
    parsed = contract.stored_object(result_json)
    prs = parsed.get("prs")
    if isinstance(prs, dict):
        urls = [str(u) for u in prs.values() if u]
        if urls:
            return " ".join(urls)
    pr = parsed.get("pr")
    return str(pr) if pr else None


class AddedItem(TypedDict):
    """An attention item new since the sink's last delivery."""

    ticket: str | None
    title: str | None
    repo: str | None
    reason: str
    detail: str
    since: str
    #: The subject's page in the web UI, when the loop serves it.
    ui: str | None


class ResolvedItem(TypedDict):
    """An attention item gone since the sink's last delivery, and whether the operator dismissed it."""

    ticket: str | None
    title: str | None
    repo: str | None
    reason: str
    dismissed: bool


class AttentionJson(TypedDict):
    """The attention diff as the `json` format carries it, with the open count and the full list's path."""

    added: list[AddedItem]
    resolved: list[ResolvedItem]
    open: int
    path: str
    #: The attention list's page in the web UI, when the loop serves it.
    ui: str | None


@dataclass
class Message:
    """What one delivery tells one sink, with what it may list and what it only counts."""

    sink: str
    repo: str
    path: Path
    attention: Diff | None
    open_items: int
    events: list[Event] = field(default_factory=list[Event])
    digest: Digest | None = None
    now: datetime | None = None
    # Ticket titles by key, which the `json` format carries beside each key; the `text` format shows keys alone.
    titles: dict[str, str] = field(default_factory=dict[str, str])
    #: The web UI's address, ending in `/`, when the loop serves it: the `json` format links to its pages. The `text`
    #: format links nothing, so `notify.cmd` sees no change.
    ui: str | None = None

    def is_empty(self) -> bool:
        """Whether there is nothing to send.

        Returns:
            True if the message has no attention change, no event, and no digest.
        """
        return not self.attention and not self.events and self.digest is None

    def _bounded(self) -> tuple[Sequence[Item], Sequence[tuple[str, str]], Sequence[Event], int]:
        """The attention lines and events to list, and how many are left out.

        Returns:
            The items added and resolved and the events to list, together at most `MAX_LINES` attention lines and
            `MAX_LINES` events, and the count of the rest. Events older than `STALE_EVENTS` are counted, not listed.
        """
        added = self.attention.added if self.attention else ()
        resolved = self.attention.resolved if self.attention else ()
        listed_added = added[:MAX_LINES]
        listed_resolved = resolved[: max(0, MAX_LINES - len(listed_added))]
        omitted = len(added) - len(listed_added) + len(resolved) - len(listed_resolved)
        fresh = [e for e in self.events if self.now is None or db.parse_time(e.at) >= self.now - STALE_EVENTS]
        listed_events = fresh[:MAX_LINES]
        omitted += len(self.events) - len(listed_events)
        return listed_added, listed_resolved, listed_events, omitted

    def text(self) -> str:
        """The `text` format. With only attention in it, exactly the message `notify.cmd` always got (DESIGN §14).

        Returns:
            The message as lines ending in a newline, the last naming the full attention list's path.
        """
        added, resolved, events, omitted = self._bounded()
        if self.attention:
            total_added, total_resolved = len(self.attention.added), len(self.attention.resolved)
            lines = [f"canopy attention: {total_added} new, {total_resolved} resolved"]
        elif self.events:
            lines = [f"canopy: {len(self.events)} event{'s' if len(self.events) != 1 else ''}"]
        else:
            lines = ["canopy digest"]
        lines += [f"+ {i.subject} {i.reason}: {_line(i.detail)}" for i in added]
        dismissed = self.attention.resolved_dismissed if self.attention else ()
        lines += [
            f"- {name} {reason}{' (dismissed)' if i < len(dismissed) and dismissed[i] else ''}"
            for i, (name, reason) in enumerate(resolved)
        ]
        lines += [e.line for e in events]
        if omitted:
            lines.append(f"... and {omitted} more: see {self.path} and `canopy status`")
        if self.digest is not None:
            lines += self.digest.lines()
        lines.append(f"Full list: {self.path}")
        return "\n".join(lines) + "\n"

    def json(self) -> str:
        """The `json` format: one object (DESIGN §20). `text` holds the same message in the text format.

        Returns:
            The object serialized as one JSON document.
        """
        added, resolved, events, omitted = self._bounded()
        attention: AttentionJson | None = None
        if self.attention is not None:
            resolved_items = self.attention.resolved_items[: len(resolved)]
            dismissed = self.attention.resolved_dismissed
            attention = {
                "added": [
                    {
                        "ticket": i.ticket_key,
                        "title": self._title(i.ticket_key),
                        "repo": i.repo,
                        "reason": i.reason,
                        "detail": _line(i.detail)[:500],
                        "since": i.since,
                        "ui": item_page(self.ui, i.ticket_key),
                    }
                    for i in added
                ],
                "resolved": [
                    {
                        "ticket": k,
                        "title": self._title(k),
                        "repo": r,
                        "reason": reason,
                        "dismissed": i < len(dismissed) and dismissed[i],
                    }
                    for i, (k, reason, r) in enumerate(resolved_items)
                ],
                "open": self.open_items,
                "path": str(self.path),
                "ui": page(self.ui, "attention"),
            }
        body = {
            "version": VERSION,
            "sink": self.sink,
            "repo": self.repo,
            "sent_at": db.format_time(self.now) if self.now is not None else db.now(),
            "ui": self.ui,
            "attention": attention,
            "events": [e.as_json(self.titles, self.ui) for e in events],
            "omitted": omitted,
            "digest": self.digest.as_json() if self.digest is not None else None,
            "text": self.text(),
        }
        return json.dumps(body)

    def render(self, fmt: str) -> str:
        """The message in format `fmt`, `json` or `text`.

        Returns:
            The `json` format if `fmt` is `json`, the `text` format otherwise.
        """
        return self.json() if fmt == "json" else self.text()

    def _title(self, key: str | None) -> str | None:
        return self.titles.get(key) if key is not None else None
