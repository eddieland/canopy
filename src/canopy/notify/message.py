"""One message for one sink (DESIGN §20): the attention diff, point events, and a digest, in `text` or `json`.

A message holding only attention is exactly the text `notify.cmd` always got (DESIGN §14), so that command sees no
change. Everything here is built from the journal; no model writes any of it.
"""

from __future__ import annotations

import json
import sqlite3
from collections import Counter
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from pathlib import Path
from typing import TYPE_CHECKING

from canopy.core import db
from canopy.core.items import Item, age

if TYPE_CHECKING:
    from canopy.notify.journal import Diff

VERSION = 1
# At most this many attention lines and this many events in one message; the rest are counted, and count as delivered.
MAX_LINES = 20
# Events older than this when a sink next succeeds are counted, not listed.
STALE_EVENTS = timedelta(hours=24)
_DONE_LISTED = 10


def _line(text: object) -> str:
    return " ".join(str(text).split())


def event_line(kind: str, fields: dict[str, object]) -> str:  # noqa: PLR0911  (one shape per kind)
    """One line of text for an event, for a person."""
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
    if kind == "loop.failing":
        return (
            f"! loop failing: {f.get('count')} ticks in a row ended other than ok; latest tick {f.get('tick')} "
            f"{f.get('status')}, log {f.get('log')}"
        )
    if kind == "loop.recovered":
        return f"! loop recovered after {f.get('failed')} failed ticks"
    if kind == "loop.sink_failing":
        return _line(f"! sink {f.get('sink')} has failed 3 deliveries in a row: {f.get('error')}")
    if kind == "test":
        return _line(f"* {f.get('text')}")
    return _line(f"{kind} {json.dumps(f)}")


@dataclass(frozen=True)
class Event:
    """One event from the outbox, as a message lists it."""

    id: int
    kind: str
    at: str
    fields: dict[str, object]

    @classmethod
    def of(cls, row: sqlite3.Row) -> Event:
        """Read an outbox row."""
        try:
            parsed: object = json.loads(str(row["fields"]))
        except json.JSONDecodeError:
            parsed = None
        # The event's own keys come first in the `json` format; a field of the same name would shadow them.
        fields = {str(k): v for k, v in parsed.items() if k not in _OWN} if isinstance(parsed, dict) else {}
        return cls(int(row["id"]), str(row["kind"]), str(row["at"]), fields)

    @property
    def line(self) -> str:
        """The event as one line for a person."""
        return event_line(self.kind, self.fields)

    def as_json(self) -> dict[str, object]:
        """The event as the `json` format lists it."""
        return {"id": self.id, "kind": self.kind, "at": self.at, **self.fields, "line": self.line}


_OWN = ("id", "kind", "at", "line")


@dataclass(frozen=True)
class Digest:
    """Progress since a sink's previous digest, from the journal only."""

    since: str
    until: str
    ticks: dict[str, int]
    runs_started: dict[str, int]
    runs_ended: dict[str, int]
    done: list[dict[str, object]]
    blocked: list[dict[str, object]]
    attention: dict[str, int]
    oldest: str | None
    running: int

    def lines(self) -> list[str]:
        """The digest as lines for a person. Sent even when nothing happened: a missing digest means a dead loop."""
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
        out += [f"  done {d['ticket']} {d.get('pr') or ''}".rstrip() for d in self.done[:_DONE_LISTED]]
        out += [f"  blocked {b['ticket']}" for b in self.blocked[:_DONE_LISTED]]
        if self.attention:
            reasons = ", ".join(f"{r} {n}" for r, n in sorted(self.attention.items()))
            out.append(f"  attention: {sum(self.attention.values())} open ({reasons}); oldest {self.oldest}")
        else:
            out.append("  nothing needs you")
        out.append(f"  workers running: {self.running}")
        return out

    def as_json(self) -> dict[str, object]:
        """The digest as the `json` format carries it."""
        return {
            "since": self.since,
            "until": self.until,
            "ticks": self.ticks,
            "runs_started": self.runs_started,
            "runs_ended": self.runs_ended,
            "done": self.done,
            "blocked": self.blocked,
            "attention": {"open": sum(self.attention.values()), "by_reason": self.attention, "oldest": self.oldest},
            "running": self.running,
            "lines": self.lines(),
        }


def digest(conn: sqlite3.Connection, items: list[Item], *, since: str, now: datetime) -> Digest:
    """Build the digest for the time since `since`: ticks, runs, the open attention list, workers running now."""
    ticks = Counter(str(r[0]) for r in conn.execute("SELECT status FROM ticks WHERE started_at >= ?", (since,)))
    started = Counter(str(r[0]) for r in conn.execute("SELECT kind FROM runs WHERE started_at >= ?", (since,)))
    ended_rows = conn.execute("SELECT * FROM runs WHERE ended_at >= ? ORDER BY id", (since,)).fetchall()
    ended = Counter(str(r["status"]) for r in ended_rows)
    done = [
        {"ticket": r["ticket_key"], "run": r["id"], "pr": _pr(r["result_json"])}
        for r in ended_rows
        if r["status"] == "done"
    ]
    blocked = [{"ticket": r["ticket_key"], "run": r["id"]} for r in ended_rows if r["status"] == "blocked"]
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
        running=len(db.running_runs(conn)),
    )


def _pr(result_json: object) -> str | None:
    if not isinstance(result_json, str) or not result_json:
        return None
    try:
        parsed: object = json.loads(result_json)
    except json.JSONDecodeError:
        return None
    if not isinstance(parsed, dict):
        return None
    prs: object = parsed.get("prs")
    if isinstance(prs, dict):
        urls = [str(u) for u in prs.values() if u]
        if urls:
            return " ".join(urls)
    pr: object = parsed.get("pr")
    return str(pr) if pr else None


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

    def is_empty(self) -> bool:
        """Whether there is nothing to send."""
        return not self.attention and not self.events and self.digest is None

    def _bounded(self) -> tuple[list[Item], list[tuple[str, str]], list[Event], int]:
        """The attention lines and events to list, and how many are left out."""
        added: list[Item] = self.attention.added if self.attention else []
        resolved: list[tuple[str, str]] = self.attention.resolved if self.attention else []
        listed_added = added[:MAX_LINES]
        listed_resolved = resolved[: max(0, MAX_LINES - len(listed_added))]
        omitted = len(added) - len(listed_added) + len(resolved) - len(listed_resolved)
        fresh = [e for e in self.events if self.now is None or db.parse_time(e.at) >= self.now - STALE_EVENTS]
        listed_events = fresh[:MAX_LINES]
        omitted += len(self.events) - len(listed_events)
        return listed_added, listed_resolved, listed_events, omitted

    def text(self) -> str:
        """The `text` format. With only attention in it, exactly the message `notify.cmd` always got (DESIGN §14)."""
        added, resolved, events, omitted = self._bounded()
        if self.attention:
            total_added, total_resolved = len(self.attention.added), len(self.attention.resolved)
            lines = [f"canopy attention: {total_added} new, {total_resolved} resolved"]
        elif self.events:
            lines = [f"canopy: {len(self.events)} event{'s' if len(self.events) != 1 else ''}"]
        else:
            lines = ["canopy digest"]
        lines += [f"+ {i.subject} {i.reason}: {_line(i.detail)}" for i in added]
        lines += [f"- {name} {reason}" for name, reason in resolved]
        lines += [e.line for e in events]
        if omitted:
            lines.append(f"... and {omitted} more: see {self.path} and `canopy status`")
        if self.digest is not None:
            lines += self.digest.lines()
        lines.append(f"Full list: {self.path}")
        return "\n".join(lines) + "\n"

    def json(self) -> str:
        """The `json` format: one object (DESIGN §20). `text` holds the same message in the text format."""
        added, resolved, events, omitted = self._bounded()
        attention: dict[str, object] | None = None
        if self.attention is not None:
            resolved_items = self.attention.resolved_items[: len(resolved)]
            attention = {
                "added": [
                    {
                        "ticket": i.ticket_key,
                        "repo": i.repo,
                        "reason": i.reason,
                        "detail": _line(i.detail)[:500],
                        "since": i.since,
                    }
                    for i in added
                ],
                "resolved": [{"ticket": k, "repo": r, "reason": reason} for k, reason, r in resolved_items],
                "open": self.open_items,
                "path": str(self.path),
            }
        body = {
            "version": VERSION,
            "sink": self.sink,
            "repo": self.repo,
            "sent_at": db.format_time(self.now) if self.now is not None else db.now(),
            "attention": attention,
            "events": [e.as_json() for e in events],
            "omitted": omitted,
            "digest": self.digest.as_json() if self.digest is not None else None,
            "text": self.text(),
        }
        return json.dumps(body)

    def render(self, fmt: str) -> str:
        """The message in format `fmt`, `json` or `text`."""
        return self.json() if fmt == "json" else self.text()
