"""Drafts (DESIGN §29): the comments a run would have posted, kept for the operator to read, edit, drop, or send.

A run rendered under `trust.review_replies = "approve"` drafts each comment it would have posted. `_run` hands this
module the run's result to write, in the transaction that closes the run (`record_run`). A worker's drafts are parsed
apart from its result (`parse`), never stored in `runs.result_json`: a draft's text lives in its versions alone. Each
entry is checked as it is written and refused alone, never cut or cleaned, with why recorded in the harness's words on
the run's `run_replies` row. A draft for a PR waits `unchecked` until a whole read of its PR says its thread exists; a
ticket's is `waiting` at once.

It is core, since `_run` writes it and the CLI and the web UI read and send it (DESIGN §5).
"""

from __future__ import annotations

import json
import sqlite3
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field

from pydantic import BaseModel, ConfigDict, JsonValue

from canopy.core import contract, db, records
from canopy.core.memory_text import TextRefused, check_text
from canopy.core.replies import MAX_DRAFT_CHARS, MAX_DRAFTS, run_replies
from canopy.core.vocab import DraftAuthor, DraftKind, DraftStance, DraftStatus, ReplyMode
from canopy.infra import logs

# The longest ticket URL a draft may name; the post command checks the rest.
MAX_URL = 2048


class Fields(BaseModel):
    """A worker's drafts, read from its result line apart from the result. Untrusted: each entry is checked alone."""

    model_config = ConfigDict(extra="ignore", frozen=True, defer_build=True)

    drafts: JsonValue = None


def parse(text: str) -> Fields | None:
    """Parse the drafts of `text`'s result line, the last line that starts with `{` (DESIGN §13).

    Returns:
        The fields, or None when there is no such line or it is not a JSON object.
    """
    return contract.last_line(Fields, text)


@dataclass(frozen=True)
class Refused:
    """A draft `_run` did not write: its number in the run's list, and why, in the harness's words."""

    number: int
    why: str

    def as_json(self) -> dict[str, int | str]:
        """Return the entry as `run_replies.refused` holds it."""
        return {"number": self.number, "why": self.why}


def record_run(conn: sqlite3.Connection, run_id: int, fields: Fields | None) -> list[Refused]:
    """Write the drafts run `run_id` sent, if its prompt was rendered under `approve` (DESIGN §29).

    Call inside the transaction that closes the run. The ticket is the run's own, read from its row, and a draft for a
    PR must name one of the PRs its units hold for the repositories it covered, so no run drafts for another's. A run
    rendered under `post`, or of a kind that comments nowhere, writes nothing, whatever it sent; so does one whose
    result line was not a valid result, which is why `fields` is None.

    Returns:
        The drafts refused, as recorded in the run's `run_replies.refused`.
    """
    rendered = run_replies(conn, run_id)
    if rendered is None or rendered.mode is not ReplyMode.APPROVE or fields is None or fields.drafts is None:
        return []
    run = conn.execute("SELECT ticket_key, tick_id, started_at FROM runs WHERE id = ?", (run_id,)).fetchone()
    writing = _Writing(
        run_id=run_id,
        ticket_key=str(run["ticket_key"]),
        basis=str(run["started_at"]),
        prs=_run_prs(conn, run_id, str(run["ticket_key"])),
        ticket_drafts=rendered.ticket_drafts,
    )
    entries: list[JsonValue] = fields.drafts if isinstance(fields.drafts, list) else []
    if not isinstance(fields.drafts, list):
        writing.refused.append(Refused(0, "`drafts` is not a list"))
    for number, entry in enumerate(entries, start=1):
        if number > MAX_DRAFTS:
            writing.refused.append(Refused(number, f"over {MAX_DRAFTS} drafts a run"))
            continue
        try:
            _write(conn, writing, number, entry)
        except TextRefused as e:
            writing.refused.append(Refused(number, str(e)))
    conn.execute(
        "UPDATE run_replies SET refused = ? WHERE run_id = ?",
        (json.dumps([r.as_json() for r in writing.refused]), run_id),
    )
    log = logs.for_tick(int(run["tick_id"]))
    for r in writing.refused:
        log.info("draft refused", extra={"run_id": run_id, **r.as_json()})
    return writing.refused


@dataclass
class _Writing:
    """One run's drafts as they are written: its ticket, its PRs by URL, and what it wrote or refused so far."""

    run_id: int
    ticket_key: str
    basis: str
    prs: Mapping[str, str]
    ticket_drafts: bool
    refused: list[Refused] = field(default_factory=list)
    pr_comments: set[str] = field(default_factory=set)
    ticket: bool = False


def _run_prs(conn: sqlite3.Connection, run_id: int, key: str) -> dict[str, str]:
    """The repository of each PR the ticket's units hold, for the repositories run `run_id` covered.

    Returns:
        Each PR's URL, to its repository.
    """
    repos = {str(r["repo"]) for r in conn.execute("SELECT repo FROM run_slots WHERE run_id = ?", (run_id,))}
    return {str(u["pr_url"]): str(u["repo"]) for u in db.units(conn, key) if u["pr_url"] and u["repo"] in repos}


def _write(conn: sqlite3.Connection, writing: _Writing, number: int, entry: JsonValue) -> None:
    """Check one entry and write it as a draft with its first version.

    Raises:
        TextRefused: The entry is not one canopy keeps, saying why.
    """
    if not isinstance(entry, dict):
        raise TextRefused("it is not an object")
    on = entry.get("on")
    kind = next((k for k in DraftKind if k == on), None)
    if kind is None:
        raise TextRefused("its `on` is not thread, pr, or ticket")
    text = check_text(entry.get("text"), MAX_DRAFT_CHARS, lines=True)
    pr, comment, stance, issue = None, None, None, None
    match kind:
        case DraftKind.THREAD | DraftKind.PR:
            pr = _pr(writing.prs, entry.get("pr"))
            if kind is DraftKind.THREAD:
                comment = _comment(entry.get("comment"))
                did = entry.get("did")
                stance = next((s for s in DraftStance if s == did), None)
                if stance is None:
                    raise TextRefused("its `did` is not changed, declined, or answered")
            elif pr in writing.pr_comments:
                raise TextRefused(f"a second draft for {pr}'s own comment; a PR takes one")
            else:
                writing.pr_comments.add(pr)
        case DraftKind.TICKET:
            if not writing.ticket_drafts:
                raise TextRefused("no_post: this run was asked for no ticket's draft")
            if writing.ticket:
                raise TextRefused("a second draft for the ticket; a run takes one")
            issue = _url(entry.get("url"))
            writing.ticket = True
    status = DraftStatus.WAITING if kind is DraftKind.TICKET else DraftStatus.UNCHECKED
    now = db.now()
    cursor = conn.execute(
        "INSERT INTO drafts (run_id, number, ticket_key, kind, repo, pr_url, comment_id, issue_url, stance, status, "
        "basis, created_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
        (
            writing.run_id,
            number,
            writing.ticket_key,
            kind,
            None if pr is None else writing.prs[pr],
            pr,
            comment,
            issue,
            stance,
            status,
            writing.basis,
            now,
        ),
    )
    conn.execute(
        "INSERT INTO draft_versions (draft_id, version, body, author, created_at) VALUES (?, 1, ?, ?, ?)",
        (cursor.lastrowid, text, DraftAuthor.WORKER, now),
    )


def _pr(prs: Mapping[str, str], value: object) -> str:
    if not isinstance(value, str) or value not in prs:
        raise TextRefused("not_ours: its `pr` is not one of this run's PRs")
    return value


def _comment(value: object) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value <= 0:
        raise TextRefused("its `comment` is not a review comment's id")
    return value


def _url(value: object) -> str:
    if (
        not isinstance(value, str)
        or not value.startswith("https://")
        or len(value) > MAX_URL
        or any(c.isspace() or not c.isprintable() for c in value)
    ):
        raise TextRefused("its `url` is not the ticket's https:// URL")
    return value


def of_run(conn: sqlite3.Connection, run_id: int) -> list[records.Draft]:
    """Return run `run_id`'s drafts, by number.

    Returns:
        The drafts, whatever their status.
    """
    return records.fetch_all(conn, records.Draft, "SELECT * FROM drafts WHERE run_id = ? ORDER BY number", (run_id,))


def text_of(conn: sqlite3.Connection, draft_id: int) -> records.DraftVersion:
    """Return draft `draft_id`'s text as it stands: its latest version.

    Returns:
        The version.

    Raises:
        LookupError: The draft has no version, which `record_run` never writes.
    """
    found = records.fetch_one(
        conn,
        records.DraftVersion,
        "SELECT * FROM draft_versions WHERE draft_id = ? ORDER BY version DESC LIMIT 1",
        (draft_id,),
    )
    if found is None:
        raise LookupError(f"draft {draft_id} has no text")
    return found


def refused_of(rendered: records.RunReplies) -> list[Refused]:
    """Return the drafts `_run` refused of a run, as recorded with it.

    Returns:
        Each refusal, in the order recorded.
    """
    raw: object = json.loads(rendered.refused)
    entries: Sequence[object] = raw if isinstance(raw, list) else []
    return [
        Refused(int(e["number"]), str(e["why"]))
        for e in entries
        if isinstance(e, dict) and isinstance(e.get("number"), int)
    ]
