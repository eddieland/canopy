"""What a `slack` source read of the replies in the Slack sink's ticket threads (DESIGN §22, §30, ROADMAP M64).

The source is a command of the operator's config, `canopy-connect-slack`, run as every connector is (`observe.run`),
with `{"repo": ROOT, "operators": [ID, ...]}` on stdin: the workspace as canopy's messages to the sink name it, which
files the sink's threads, and the source's `operators`. It prints a `reply` line for each message one of them wrote in
a ticket's thread, nobody else's, and last
`{"kind": "end", "tickets": [...], "unread": [...]}`, naming the tickets whose threads it read whole and those it could
not.

Unlike the other sources, what it reads is no observation. A reply from one of the source's `operators`, on a ticket
canopy knows, is the operator's own message, recorded through `conversation.reply` as `canopy reply` records one, on
the channel `slack`, the message's `ts` its submission: the next run reads it again, and records nothing new
(TRUST_MODEL T1). Whose reply counts is checked here too, in code, against the operator's private config, whatever
the reader printed, so a reader of the operator's own that prints more widens nothing. Any other line records
nothing, not even as data: a reply from someone not listed, on a ticket canopy does not know, or one `reply` refuses,
such as one over its bound. Each is counted in the run's record by why, and a refused operator's reply is logged.

A run with no `end` line records nothing, as any connector's. A dry run records no message (D036): it counts the replies
it would have recorded.
"""

from __future__ import annotations

import json
import re
from collections import Counter
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Annotated, Literal, cast

from pydantic import BaseModel, ConfigDict, ValidationError

from canopy.core import conversation, db, observe
from canopy.core.config import SLACK_USER_RE
from canopy.core.vocab import ConnectorRunStatus

if TYPE_CHECKING:
    import sqlite3
    from collections.abc import Mapping, Sequence

    from canopy.core.config import Source
    from canopy.infra import logs, procs

#: The channel a reply read from Slack is recorded on (DESIGN §22).
CHANNEL = "slack"
#: How many unread tickets a run's `missed` names before it counts the rest.
_NAMED = 5
#: A Slack message's `ts`: seconds, a dot, and the microseconds that make it unique in its channel.
_TS = re.compile(r"\d{1,20}\.\d{1,20}")


def read(
    conn: sqlite3.Connection,
    runner: procs.Runner,
    source: Source,
    request: observe.Request,
    *,
    dry_run: bool,
    log: logs.TickAdapter,
) -> observe.Observed:
    """Run the `slack` source's connector for `request`, and record each listed operator's reply it read.

    Returns:
        How the run ended: `partial` when its `end` line names tickets whose threads it could not read.
    """
    ran = observe.run(runner, source, request, log=log)
    if isinstance(ran, observe.Observed):
        return ran
    found = _read(ran.stdout)
    if found.end is None:
        return observe.failed(log, ran.started_at, "it ended without its end line", ran.stderr, found.refused)
    recorded, refused = _record(conn, source.operators, found.replies, dry_run=dry_run, log=log)
    refused.update(found.refused)
    missed = _missed(found.end.unread)
    if missed is not None:
        log.warning("slack source read short", extra={"missed": missed})
    return observe.Observed(
        status=ConnectorRunStatus.OK if missed is None else ConnectorRunStatus.PARTIAL,
        started_at=ran.started_at,
        ended_at=db.now(),
        recorded=dict(recorded),
        refused=dict(refused),
        missed=missed,
        stderr=ran.stderr,
    )


def submission(ts: str) -> str:
    """A Slack message's `ts` as the submission id its reply is recorded under: `conversation.SUBMISSION_RE` has no dot.

    Returns:
        The id, the `ts` with its dot a dash.
    """
    return ts.replace(".", "-")


# What a line carries

_Key = Annotated[str, observe.text_of(conversation.MAX_KEY, conversation.KEY_RE)]
_Ts = Annotated[str, observe.text_of(41, _TS)]
_User = Annotated[str, observe.text_of(31, SLACK_USER_RE)]


class _Line(BaseModel):
    model_config = ConfigDict(extra="ignore", frozen=True, defer_build=True)


class _Reply(_Line):
    kind: Literal["reply"]
    ticket: _Key
    ts: _Ts
    user: _User
    # Bounded where it is recorded: `conversation.reply` refuses one over its bound, rather than cut the operator's
    # words.
    body: str


class _End(_Line):
    kind: Literal["end"]
    tickets: list[_Key] = []
    unread: list[_Key] = []


@dataclass
class _Output:
    """A reader's output as validated: its replies, in the order printed, its last `end` line, and what was refused."""

    replies: list[_Reply] = field(default_factory=list[_Reply])
    end: _End | None = None
    refused: Counter[str] = field(default_factory=Counter[str])


def _read(stdout: str) -> _Output:
    """Validate each line of the reader's output; a line of another kind, or not JSON, is skipped (DESIGN §30).

    Returns:
        The replies, the last `end` line, and what was refused.
    """
    found = _Output()
    for text in stdout.splitlines():
        if len(text) > observe.MAX_LINE:
            found.refused["unread"] += 1
            continue
        try:
            raw: object = json.loads(text)
        except json.JSONDecodeError:
            continue
        if isinstance(raw, dict):
            _take(found, cast("dict[str, object]", raw))
    return found


def _take(found: _Output, raw: Mapping[str, object]) -> None:
    kind = str(raw.get("kind"))
    if kind == "end":
        try:
            found.end = _End.model_validate(raw)
        except ValidationError:
            found.refused["end"] += 1
    elif kind == "reply":
        try:
            found.replies.append(_Reply.model_validate(raw))
        except ValidationError:
            found.refused["reply"] += 1


def _record(
    conn: sqlite3.Connection,
    operators: Sequence[str],
    replies: Sequence[_Reply],
    *,
    dry_run: bool,
    log: logs.TickAdapter,
) -> tuple[Counter[str], Counter[str]]:
    """Record each listed operator's reply as their message, each in its own transaction, as `canopy reply` does.

    Returns:
        What was recorded, by kind: `reply` for a new message, `already` for one recorded by an earlier run, and, in a
        dry run, `dry_run` for one it would have recorded. And what was not, by why: `unlisted` for someone not in
        `operators`, or the guard `reply` refused it by, such as `unknown` or `bad_body`.
    """
    recorded: Counter[str] = Counter()
    refused: Counter[str] = Counter()
    for line in replies:
        if line.user not in operators:
            refused["unlisted"] += 1
            continue
        if dry_run:
            recorded["dry_run"] += 1
            continue
        ref = conversation.Ref(conversation.TICKET, line.ticket)
        try:
            replied = conversation.reply(conn, ref, line.body, channel=CHANNEL, submission=submission(line.ts))
        except conversation.Refused as e:
            refused[e.guard] += 1
            log.warning("slack reply not recorded", extra={"ticket": line.ticket, "ts": line.ts, "guard": e.guard})
            continue
        recorded["reply" if replied.new else "already"] += 1
        if replied.new:
            log.info("slack reply recorded", extra={"ticket": line.ticket, "message_id": replied.message_id})
    return recorded, refused


def _missed(unread: Sequence[str]) -> str | None:
    """The harness's words for the tickets whose threads the reader could not read, or None.

    Returns:
        The words, naming at most `_NAMED` tickets.
    """
    if not unread:
        return None
    named = ", ".join(unread[:_NAMED])
    more = f" and {len(unread) - _NAMED} more" if len(unread) > _NAMED else ""
    return f"did not read the Slack threads of {named}{more}"
