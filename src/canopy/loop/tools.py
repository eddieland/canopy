"""The overseer's verbs (DESIGN §6, §27): each one a request that holds its bounds, and a function that does it.

A request is a pydantic model (D026) that refuses an unknown field and is the verb's MCP schema. It validates what
the overseer passes in, keys, reasons, phases, cursor ids, and free text, which later reach branch names, argv, and
prompts, and the rules across its fields. The MCP server (`loop.mcp`) builds a request from a tool call's arguments and
calls its verb.

A verb returns an `Outcome`: its tool's text, and a result, a model whose fields say what it did and whose schema is its
tool's output schema. A request that does not validate, a guard's refusal, and a call outside a running tick, which is
`Refused`, are each a tool error, its text saying why.

This module holds what every verb shares, the bounds, the `Request` and `Result` bases, and the running tick, and the
ticket's verbs:
dispatch, decide, attention, and ticket-set. A feature's own verbs are in a module of their own, the
reviews' in `loop.review_tools` and the chores' in `loop.chore_tools`.
"""

from __future__ import annotations

import os
import re
from collections.abc import Callable, Collection, Iterable, Mapping, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import TYPE_CHECKING, Annotated, Literal, Self

from pydantic import (
    AfterValidator,
    BaseModel,
    BeforeValidator,
    ConfigDict,
    Field,
    StrictBool,
    StrictInt,
    WithJsonSchema,
    model_validator,
)
from pydantic_core import PydanticUndefined

from canopy.core import config, contract, conversation, db, kept_items, memory, recorded_runs, vocab
from canopy.core.vocab import RecordedStatus, ResumeReason, RunKind, TickStatus
from canopy.infra import logs
from canopy.loop import attention, claims, harness, harness_dispatches
from canopy.reviews import findings
from canopy.runs import dispatch, policy

if TYPE_CHECKING:
    import sqlite3

    from pydantic.config import JsonDict

    from canopy.core import records
    from canopy.core.context import Context

#: A ticket key; keys reach branch names, lease holders, paths, and argv (DESIGN §17).
KEY_RE = dispatch.KEY_RE
#: An attention item's reason, the `attention:<reason>` action it is recorded as.
REASON_RE = re.compile(r"[a-z][a-z0-9_]*")
#: A cursor's id: it is rendered into prompts, so it is kept short and plain.
CURSOR_VALUE_RE = re.compile(r"[A-Za-z0-9][A-Za-z0-9_.:/-]{0,199}")
#: The most free text the overseer writes to the journal in one field.
MAX_TEXT = 2000
#: A ticket's title is a name, shown beside its key and in its runs' session titles (DESIGN §13).
MAX_TITLE = 80
#: The longest PR URL the overseer may name.
MAX_PR_URL = 300
#: What `decide` records.
DECIDE_ACTIONS = ("wait", "skip", "done")
#: The guard that refuses what the overseer records about a ticket the harness decided (DESIGN §37).
DECIDED = "decided"
#: The guard that refuses an attention item of a reason the harness raises from its causes (DESIGN §37).
RAISED = "raised"
#: The guard that refuses an item the overseer keeps that names nothing that could end it (DESIGN §37).
UNNAMED = "unnamed"
#: The phases the overseer sets. `split` is retired (M46): old tickets may still hold it, and nothing sets it.
SETTABLE_PHASES = tuple(p.value for p in vocab.Phase if p is not vocab.Phase.SPLIT)


#: What a verb's result says of the recorded run it returns (DESIGN §40).
RECORDED_DESCRIPTION = (
    "The recorded run, which the tick starts once your run ends, under its guards again; none in a dry run."
)
#: What a verb's text says of a run it recorded.
STARTS_AFTER = "it starts once your run ends, if its guards still allow it"


class Refused(Exception):  # noqa: N818  (a refusal is an outcome the overseer is told about, not an error)
    """A guard refused the call, or it came from outside a running tick. Its text is the tool error's."""


# The bounds of what the overseer passes in, each as a check the click parameter types share.


def valid_key(value: str) -> bool:
    """Keys reach branch names, lease holders, paths, and argv (DESIGN §17).

    Returns:
        True when `value` matches `KEY_RE` in full.
    """
    return KEY_RE.fullmatch(value) is not None


def truncate(value: str) -> str:
    """Bound free text the overseer writes to the journal.

    Returns:
        `value` unchanged when it fits in `MAX_TEXT`, else cut to it and ended with "...".
    """
    return value if len(value) <= MAX_TEXT else value[: MAX_TEXT - 3] + "..."


def clean_text(value: str) -> str:
    """Free text the overseer writes into the journal: stripped, non-empty, bounded.

    Returns:
        `value` stripped, and cut to `MAX_TEXT`.

    Raises:
        ValueError: Nothing is left once it is stripped.
    """
    stripped = value.strip()
    if not stripped:
        raise ValueError("must not be empty")
    return truncate(stripped)


def clean_title(value: str) -> str:
    """A ticket's title: one line, control characters dropped, whitespace collapsed, non-empty, and cut.

    Returns:
        The title as one line of at most `MAX_TITLE` characters.

    Raises:
        ValueError: Nothing printable is left.
    """
    line = " ".join("".join(c if c.isprintable() else " " for c in value).split())
    if not line:
        raise ValueError("must not be empty")
    return line if len(line) <= MAX_TITLE else line[: MAX_TITLE - 3] + "..."


def pr_url(value: str) -> str:
    """A PR's URL as the overseer passes it: a plain https:// URL, at most `MAX_PR_URL` characters (DESIGN §21).

    It reaches the journal's `pr` column, the state block, and the web UI's links.

    Returns:
        `value`, unchanged.

    Raises:
        ValueError: It is not a plain https:// URL that short.
    """
    if not contract.plain_url(value, MAX_PR_URL):
        raise ValueError(f"must be a plain https:// URL of at most {MAX_PR_URL} characters")
    return value


def cursor(name: str, cursor_id: str) -> tuple[str, str]:
    """A cursor, `name` advanced to `cursor_id`; the id is later rendered into prompts, so it is kept short and plain.

    Returns:
        The pair, unchanged.

    Raises:
        ValueError: `name` is no cursor, or `cursor_id` is not one of its ids.
    """
    if name not in db.CURSOR_COLUMNS:
        raise ValueError(f"cursor must be NAME=ID with NAME one of {', '.join(db.CURSOR_COLUMNS)}")
    if not CURSOR_VALUE_RE.fullmatch(cursor_id):
        raise ValueError(f"invalid cursor id {cursor_id!r}")
    # A message cursor is a journal message id (DESIGN §22); a comment, review, or ci cursor a journal number (§35).
    if not _digits(cursor_id):
        what = "a message id, a number" if name == "message" else "an item's journal number, as the state block shows"
        raise ValueError(f"a {name} cursor is {what}; got {cursor_id!r}")
    return name, cursor_id


def _digits(value: str) -> bool:
    return value.isascii() and value.isdigit()


def matching(pattern: re.Pattern[str], what: str) -> AfterValidator:
    """Refuse a string that does not match `pattern` in full.

    Returns:
        A validator that passes a matching string through and names `what` it should have been otherwise.
    """

    def check(value: str) -> str:
        if not pattern.fullmatch(value):
            raise ValueError(f"invalid {what} {value!r}: must match {pattern.pattern}")
        return value

    return AfterValidator(check)


def one_of(what: str, values: Sequence[str]) -> AfterValidator:
    """Refuse a string that is not one of `values`.

    Returns:
        A validator that passes one of them through and names the choices otherwise.
    """

    def check(value: str) -> str:
        if value not in values:
            raise ValueError(f"invalid {what} {value!r}: choose from {', '.join(values)}")
        return value

    return AfterValidator(check)


def _cursors(pairs: Mapping[str, str]) -> Mapping[str, str]:
    for name, cursor_id in pairs.items():
        cursor(name, cursor_id)
    return pairs


def _null_left_out(empty: Callable[[], object], shown: object = PydanticUndefined) -> BeforeValidator:
    """Take a field's `null` as the field left out, as the fields that default to None do: a model sends either.

    Returns:
        A validator that puts `empty()` in place of None, its schema `shown` when given, else the field's own.
    """
    return BeforeValidator(lambda value: empty() if value is None else value, json_schema_input_type=shown)


def _known_kind(value: object) -> object:
    """Refuse a kind that is no run kind, naming only those dispatched.

    A retired kind passes, to be refused naming what replaced it, a refusal the decisions record.

    Returns:
        `value`, unchanged.

    Raises:
        ValueError: It is no run kind.
    """
    if not (isinstance(value, str) and value in tuple(RunKind)):
        raise ValueError(f"choose from {', '.join(policy.DISPATCH_KINDS)}")
    return value


def required(*names: str) -> Callable[[JsonDict], None]:
    """List `names` in a request's schema as required, though the request takes them left out.

    A field left out is a guard's refusal, which the decisions record; the schema still tells the
    model to name it.

    Returns:
        What adds them to the schema's `required`.
    """

    def add(schema: JsonDict) -> None:
        listed = schema.get("required")
        schema["required"] = [*(listed if isinstance(listed, list) else []), *names]
        properties = schema.get("properties")
        for name in names:
            field = properties.get(name) if isinstance(properties, dict) else None
            if isinstance(field, dict):
                field.pop("default", None)

    return add


#: A cursor's name: comment and message are a ticket's, review and ci a unit's.
CursorName = Literal["comment", "message", "review", "ci"]
#: A ticket key, such as PROJ-123.
Key = Annotated[str, matching(KEY_RE, "ticket key"), Field(description="A ticket key, such as PROJ-123.")]
#: A repository's name in the workspace's map.
Repo = Annotated[
    str,
    matching(config.REPO_NAME_RE, "repository name"),
    Field(description="A repository's name in the map."),
]
#: Free text for the journal, stripped and cut to `MAX_TEXT`.
Text = Annotated[str, AfterValidator(clean_text)]
#: A PR's plain https:// URL.
PrUrl = Annotated[str, AfterValidator(pr_url), Field(description="The PR's https:// URL.")]
#: The cursors a call advances, by name: comment and message are a ticket's, review and ci a unit's.
Cursors = Annotated[
    Mapping[CursorName, str],
    _null_left_out(dict, Mapping[CursorName, str] | None),
    AfterValidator(_cursors),
    Field(
        description="Cursors to advance past what you handled, by name, each the number of the newest item handled as "
        "the state block shows it. comment and message are the ticket's; review and ci a unit's, one repository's.",
    ),
]


class Request(BaseModel):
    """The base of every verb's request, whose fields are the verb's MCP schema."""

    # An unknown field is refused: a misspelled one would otherwise be dropped without a word. A number is taken for a
    # string, as a tracker's ids are often sent: a comment's id, a check run's.
    model_config = ConfigDict(extra="forbid", frozen=True, defer_build=True, coerce_numbers_to_str=True)


class Result(BaseModel):
    """The base of every verb's result: its fields are the tool's structured content, its schema the output schema."""

    model_config = ConfigDict(extra="forbid", frozen=True, defer_build=True)


@dataclass(frozen=True)
class Outcome[R: BaseModel]:
    """What a verb did, as its tool returns it."""

    #: The tool's text, what the model reads.
    text: str
    #: The same as fields: the tool's structured content.
    result: R


# The verbs, each its request, its result, then its function.


class Dispatch(Request):
    """A worker started on a ticket."""

    # `repos` left out is the dispatch guard's refusal, which the decisions record, so the request takes it.
    model_config = ConfigDict(json_schema_extra=required("repos"))

    #: The ticket.
    key: Key
    #: What the worker does. `fix-ci` and `split` are taken only to be refused naming what replaced them, a refusal
    #: the decisions record, so the schema does not offer them.
    kind: Annotated[
        RunKind,
        BeforeValidator(_known_kind),
        WithJsonSchema({"type": "string", "enum": list(policy.DISPATCH_KINDS)}),
        Field(
            description="What the worker does: implement builds the ticket; resume carries on its PR for the reasons "
            "named; plan writes a plan before its first implement; feedback-plan plans the answer to what came back "
            "on a unit's PR, before the resume that acts on it.",
        ),
    ]
    #: The queue label read on the ticket just now; none for a ticket the operator started.
    label: Annotated[
        str | None,
        Field(
            description="The configured queue label you read on the ticket just now. Required for a public ticket; "
            "a ticket the operator started needs none.",
        ),
    ] = None
    #: The repositories the run works in, a unit each; several for a joint run.
    repos: Annotated[
        tuple[Repo, ...],
        _null_left_out(tuple),
        Field(description="The repositories the run works in, one unit each; several for a joint run. Required."),
    ] = ()
    #: implement only: the short name of the work, in its branch.
    slug: Annotated[
        Annotated[str, matching(dispatch.SLUG_RE, "slug")] | None,
        Field(description=f"implement only: short name for the work; default {dispatch.DEFAULT_SLUG!r}."),
    ] = None
    #: Another ticket's branch to stack on.
    base: Annotated[str | None, Field(description="Stack on another ticket's branch, whose PR is open and green.")] = (
        None
    )
    #: resume only: the canopy review run whose findings the worker addresses.
    review_run: Annotated[
        StrictInt | None,
        Field(ge=1, description="resume only: the review run whose findings the worker addresses."),
    ] = None
    #: resume only, and required for it: why it runs.
    reasons: Annotated[
        tuple[ResumeReason, ...],
        _null_left_out(tuple, tuple[ResumeReason, ...] | None),
        Field(
            description="resume only, and required for it: why it runs, each once. ci: failed checks; review: review "
            "feedback or a canopy review's findings; reply: an authorized reply or the operator's message; conflict: "
            "the PR conflicts with its base; no_pr: the branch is pushed and has no PR; retarget: the PR's blocker "
            "merged, so it targets the base branch again.",
        ),
    ] = ()
    #: What the worker should read or do: links, comment ids, check names. Never quoted text.
    context: Annotated[
        Text | None,
        Field(description="What the worker should read or do. Never quoted ticket or PR text."),
    ] = None
    #: The cursors to advance, only if the worker starts; a resume's reasons move theirs to the newest item shown.
    cursors: Annotated[
        Cursors,
        Field(
            description="Cursors to advance, only if the worker starts, by name, each the number of the newest item "
            "handled as the state block shows it. A resume moves each cursor of its reasons it leaves out to the "
            "newest item of that kind the state block shows, short of one it may not cover: pass one only to stop "
            "shorter. comment and message are the ticket's; review and ci a unit's, one repository's.",
        ),
    ] = Field(default_factory=dict)

    @model_validator(mode="after")
    def _one_unit(self) -> Self:
        unit_cursors = [name for name in self.cursors if name in db.UNIT_CURSORS]
        if unit_cursors and len(set(self.repos)) > 1:
            raise ValueError(
                f"cursors: a {unit_cursors[0]} cursor belongs to one unit, so repos names one; advance it "
                "after with ticket-set and its repo",
            )
        return self


class Dispatched(Result):
    """A worker recorded for a ticket, which the tick starts after the overseer, or a dry run's its guards allow."""

    #: The ticket.
    key: Annotated[str, Field(description="The ticket.")]
    #: What the worker does.
    kind: Annotated[RunKind, Field(description="What the worker does.")]
    #: Whether this was a dry run, which records nothing.
    dry_run: Annotated[bool, Field(description="Whether this was a dry run, which records nothing.")]
    #: The recorded run, which the tick starts once the overseer's run ends; none in a dry run.
    recorded: Annotated[int | None, Field(description=RECORDED_DESCRIPTION)]
    #: The branch it works on; empty for a plan, which works on none.
    branch: Annotated[str, Field(description="The branch it works on; empty for a plan, which works on none.")]
    #: The repositories it works in, a unit each.
    repos: Annotated[tuple[str, ...], Field(description="The repositories it works in, a unit each.")]


def dispatch_run(ctx: Context, request: Dispatch) -> Outcome[Dispatched]:
    """Record a worker for a ticket, if its guards allow one now, for the tick to start after the overseer (§40).

    In a dry run, check the guards and record nothing (D036). The tick starts the recorded run once the overseer's run
    has ended (`spawn_dispatch`); until then it is the ticket's one run, and holds a worker.

    Returns:
        The tool's text, the run recorded or what a dry run would have started, and the same as fields.

    Raises:
        Refused: Outside a running tick, or a guard refused the dispatch, which is recorded.
    """
    current = running_tick(ctx)
    key, kind, repos, reasons = request.key, request.kind, request.repos, request.reasons
    tick_id = current.id
    _refuse_decided(ctx, tick_id, key, "dispatch")
    log = logs.for_tick(tick_id)
    db.touch_ticket(ctx.conn, key, ctx.repo)
    now = datetime.now(UTC)
    # A resume's reasons move their cursors to the newest item the block showed, unless it passed one (DESIGN §37).
    cursors = claims.default_cursors(
        ctx,
        current,
        now,
        key=key,
        kind=kind,
        repos=repos,
        reasons=reasons,
        cursors=dict[str, str](request.cursors.items()),
        review_run=request.review_run,
    )
    cursor_pairs: list[tuple[str, str]] = list(cursors.items())
    handles = _handles(cursor_pairs, request.review_run)
    # The workers the harness's runs to come hold ahead of this one, in §7's order (DESIGN §37).
    reserved = harness_dispatches.reserved(ctx, tick_id, kind, reasons)
    try:
        dispatch.check_kind(kind)
        _review_findings(ctx.conn, key, kind, repos, request.review_run)
        # The claims, checked against what the connectors observed, before §8's other guards (DESIGN §35).
        claims.check(
            ctx,
            tick_id,
            now,
            key=key,
            kind=kind,
            label=request.label,
            repos=repos,
            reasons=reasons,
            cursors=cursors,
            review_run=request.review_run,
            base=request.base,
        )
        # A dry run checks the same guards, so its plan holds the refusals a live tick would get (D036).
        if current.dry_run:
            plan = dispatch.check(
                ctx,
                tick_id=tick_id,
                key=key,
                kind=kind,
                label=request.label,
                slug=request.slug,
                base=request.base,
                repos=repos,
                reasons=reasons,
                cursors=handles,
                reserved=reserved,
            )
            recorded = None
        else:
            recorded = dispatch.record(
                ctx,
                tick_id=tick_id,
                key=key,
                kind=kind,
                label=request.label,
                slug=request.slug,
                base=request.base,
                # With its default cursors, so the spawn moves what the block showed at the ask (DESIGN §37, §40).
                request=request.model_copy(update={"cursors": cursors}).model_dump(mode="json"),
                repos=repos,
                reasons=reasons,
                cursors=handles,
                reserved=reserved,
            )
            plan = recorded.plan
    except dispatch.Refusal as r:
        _dispatch_refused(ctx, tick_id, key, kind, r)
        raise Refused(f"dispatch refused ({r.guard}): {r.reason}; the refusal was recorded") from None
    branch, repo_names = plan.branch, plan.repos
    authorized = _authorized(plan.label, starts=plan.starts)
    in_repo = f" in {', '.join(repo_names)}"
    work = _work(key, kind, branch, request.base, repo_names)
    requested = f"; review run {request.review_run}" if request.review_run is not None else ""
    requested += f"; {_for(reasons)}" if reasons else ""
    if recorded is None:
        extras = [
            *(f"cursor {name}={value}" for name, value in cursor_pairs),
            f"context={request.context}" if request.context else "",
        ]
        rationale = truncate(
            "; ".join(
                e
                for e in [
                    _would(kind, work, in_repo),
                    authorized,
                    f"review run {request.review_run}" if request.review_run is not None else "",
                    _for(reasons) if reasons else "",
                    *extras,
                ]
                if e
            ),
        )
        db.record_decision(ctx.conn, tick_id, key, f"dispatch:{kind}", rationale)
        log.info("dry-run dispatch recorded", extra={"ticket": key, "kind": kind})
        return Outcome(
            f"dry run: recorded dispatch {kind} for {key}; nothing was started",
            Dispatched(key=key, kind=kind, dry_run=True, recorded=None, branch=branch, repos=repo_names),
        )
    # The decision is recorded as the run starts, or with its refusal then: cursors move only once it starts.
    log.info("dispatch recorded", extra={"ticket": key, "kind": kind, "recorded_run_id": recorded.recorded_id})
    return Outcome(
        f"recorded dispatch {kind} for {key} as recorded run {recorded.recorded_id}: {work}{in_repo}; "
        f"{authorized}{requested}; {STARTS_AFTER}",
        Dispatched(
            key=key,
            kind=kind,
            dry_run=False,
            recorded=recorded.recorded_id,
            branch=branch,
            repos=repo_names,
        ),
    )


def spawn_dispatch(ctx: Context, recorded: records.RecordedRun) -> None:
    """Start the worker `recorded` names, as its tick does once the overseer's run has ended (DESIGN §40).

    Every guard is checked again, and a refusal is recorded as the overseer's dispatch's would be; the run's decision
    is recorded as it starts, its cursors moved then, so what a refused one was meant to handle is still new next tick.
    """
    request = Dispatch.model_validate(recorded_runs.request_of(recorded))
    tick_id = recorded.tick_id
    key, kind, repos, reasons = request.key, request.kind, request.repos, request.reasons
    cursor_pairs: list[tuple[str, str]] = list(request.cursors.items())
    unit_cursors = [name for name, _ in cursor_pairs if name in db.UNIT_CURSORS]
    log = logs.for_tick(tick_id)
    try:
        review = _review_findings(ctx.conn, key, kind, repos, request.review_run)
        # The claims again too: an observation fresh at the ask may have aged past its bound since (DESIGN §35, §40).
        claims.check(
            ctx,
            tick_id,
            datetime.now(UTC),
            key=key,
            kind=kind,
            label=request.label,
            repos=repos,
            reasons=reasons,
            cursors=dict(cursor_pairs),
            review_run=request.review_run,
            base=request.base,
        )
        started = dispatch.start(
            ctx,
            tick_id=tick_id,
            key=key,
            kind=kind,
            label=request.label,
            slug=request.slug,
            base=request.base,
            context=request.context,
            repos=repos,
            review=review,
            reasons=reasons,
            cursors=_handles(cursor_pairs, request.review_run),
            spawning=recorded.id,
        )
    except dispatch.Refusal as r:
        recorded_runs.close(ctx.conn, recorded.id, RecordedStatus.REFUSED)
        _dispatch_refused(ctx, tick_id, key, kind, r)
        return
    recorded_runs.close(ctx.conn, recorded.id, RecordedStatus.STARTED, run_id=started.run_id)
    # Cursors advance only now, so what a refused dispatch was meant to handle is still new next tick.
    ticket_cursors = {name: value for name, value in cursor_pairs if name in db.TICKET_CURSORS}
    db.set_ticket(ctx.conn, key, ctx.repo, cursors=ticket_cursors)
    if unit_cursors:
        cursors = {name: value for name, value in cursor_pairs if name in db.UNIT_CURSORS}
        db.set_unit(ctx.conn, key, ctx.repo, started.repos[0], cursors=cursors)
    # `base` passed the guards, so it is the branch this run is stacked on.
    work = _work(key, kind, started.branch, request.base, started.repos)
    requested = f"; review run {request.review_run}" if request.review_run is not None else ""
    requested += f"; {_for(reasons)}" if reasons else ""
    authorized = _authorized(started.label, starts=started.starts)
    rationale = f"run {started.run_id}: {work}{_where(started)}; {authorized}{requested}"
    db.record_decision(ctx.conn, tick_id, key, f"dispatch:{kind}", rationale)
    log.info(
        "dispatched",
        extra={
            "ticket": key,
            "kind": kind,
            "run_id": started.run_id,
            "pid": started.pid,
            "recorded_run_id": recorded.id,
        },
    )


def _dispatch_refused(ctx: Context, tick_id: int, key: str, kind: str, r: dispatch.Refusal) -> None:
    """Record a guard's refusal of a dispatch, at the ask or at the spawn, and the attention item it raises, if any."""
    db.record_decision(ctx.conn, tick_id, key, f"refused:{r.guard}", r.reason)
    if r.attention is not None:
        # The overseer wants work a guard forbids, and only a human can lift it: the attempt limit, a retired
        # prompt override, or a persona canopy cannot use (DESIGN §8, §14, §31). In a workspace of several, the
        # item is about the unit it holds.
        db.record_decision(ctx.conn, tick_id, key, f"{attention.ACTION_PREFIX}{r.attention}", r.reason, repo=r.repo)
    logs.for_tick(tick_id).info(
        "dispatch refused",
        extra={"ticket": key, "kind": kind, "guard": r.guard, "reason": r.reason},
    )


def _authorized(label: str, *, starts: bool) -> str:
    """What a dispatch's decision says authorized it: the queue label, or the operator's start (DESIGN §22).

    `label` is the configured spelling, or empty for a private ticket, which its start record authorizes. Under
    `tracker.private` the label authorizes a ticket's first run, which starts it privately.

    Returns:
        The words, for the decision's rationale.
    """
    authorized = f"label {label}" if label else "private: started by the operator"
    return authorized + ("; starts it privately (tracker.private)" if starts else "")


class Decide(Request):
    """A decision about a ticket."""

    #: The ticket.
    key: Annotated[Key, Field(description="The ticket.")]
    #: What was decided.
    action: Annotated[
        Literal["wait", "skip", "done"],
        Field(
            description="wait: nothing to do until something changes, such as checks still running; skip: the loop "
            "leaves the ticket alone, such as one not labeled, or one you would act on but may not; done: its work is "
            "over, such as a closed ticket.",
        ),
    ]
    #: Why, in the overseer's own words.
    rationale: Annotated[Text, Field(description="Why, in your own words.")]


class Decisions(Request):
    """One or more decisions, recorded together or not at all."""

    #: Each decision, in the order it is recorded.
    decisions: Annotated[
        tuple[Decide, ...],
        # Its one item is checked below, not by `min_length`, which would also refuse a call whose only item is wrong.
        Field(
            json_schema_extra={"minItems": 1},
            description="Each decision, one per ticket, recorded together or not at all.",
        ),
    ]

    @model_validator(mode="after")
    def _batch(self) -> Self:
        if not self.decisions:
            raise ValueError("name at least one decision")
        keys = [d.key for d in self.decisions]
        if twice := sorted({key for key in keys if keys.count(key) > 1}):
            raise ValueError(f"decide each ticket once in a call: {', '.join(twice)} decided twice")
        return self


class Decision(Result):
    """A decision recorded about a ticket."""

    #: The ticket.
    key: Annotated[str, Field(description="The ticket.")]
    #: What was decided.
    action: Annotated[Literal["wait", "skip", "done"], Field(description="What was decided.")]


class Decided(Result):
    """The decisions a call recorded."""

    #: Each decision recorded, in the order given.
    decisions: Annotated[tuple[Decision, ...], Field(description="Each decision recorded, in the order given.")]


def decide(ctx: Context, request: Decisions) -> Outcome[Decided]:
    """Record decisions, all of them or none.

    Returns:
        The tool's text, and the same as fields.

    Raises:
        Refused: Outside a running tick, or about a ticket the harness decided this tick, whose refusal is recorded and
            leaves every decision of the call unrecorded.
    """
    current = running_tick(ctx)
    keys = [d.key for d in request.decisions]
    if refused := [r for key in keys if (r := _decided_by_harness(ctx, current.id, key, "decide")) is not None]:
        recorded = "the refusal was recorded" if len(refused) == 1 else "the refusals were recorded"
        unrecorded = "" if len(request.decisions) == 1 else ", and nothing else in the call: decide the rest again"
        raise Refused(f"decide refused ({DECIDED}): {'; '.join(refused)}; {recorded}{unrecorded}")
    with db.transaction(ctx.conn):
        for d in request.decisions:
            db.touch_ticket(ctx.conn, d.key, ctx.repo)
            db.record_decision(ctx.conn, current.id, d.key, d.action, d.rationale)
    return Outcome(
        "\n".join(f"recorded {d.action} for {d.key}" for d in request.decisions),
        Decided(decisions=tuple(Decision(key=d.key, action=d.action) for d in request.decisions)),
    )


class Attention(Request):
    """An attention item about a ticket, or about a PR the loop reviews."""

    #: The ticket; none for a PR with no ticket, named by `pr`.
    key: Annotated[Key | None, Field(description="The ticket; omit it for a PR with no ticket, named by pr.")] = None
    #: Why the operator is needed, as a word.
    reason: Annotated[str, matching(REASON_RE, "reason"), Field(description="Why, as lowercase_with_underscores.")]
    #: What the operator needs to know.
    detail: Annotated[Text, Field(description="What the operator needs to know, shown on the attention list.")]
    #: The repository of the ticket's unit the item is about, in a workspace of several.
    repo: Annotated[Repo | None, Field(description="The repository of the unit the item is about.")] = None
    #: A PR the loop reviews.
    pr: Annotated[
        PrUrl | None,
        Field(description="A PR the loop reviews; in place of key for a PR with no ticket."),
    ] = None
    #: The journal number of what a `needs_author` waits on, or of the check run a `notice_rerun` holds.
    item: Annotated[
        StrictInt | None,
        Field(
            ge=1,
            description="needs_author and notice_rerun: the number, as the state block shows it, of the comment, "
            "review item, or review run a needs_author waits on, or of the check run a notice_rerun holds.",
        ),
    ] = None

    @model_validator(mode="after")
    def _about(self) -> Self:
        if self.key is None and self.pr is None:
            raise ValueError("key or pr is required: an item is about a ticket, or a PR with no ticket")
        if self.item is not None and self.reason not in kept_items.NAMING:
            raise ValueError("item is only for needs_author and notice_rerun: what one waits on, or the check it holds")
        return self


class AttentionRecorded(Result):
    """An attention item recorded."""

    #: Why the operator is needed.
    reason: Annotated[str, Field(description="Why the operator is needed.")]
    #: The ticket; none for a PR with no ticket.
    key: Annotated[str | None, Field(description="The ticket; none for a PR with no ticket.")]
    #: The repository of the ticket's unit it is about, if it names one.
    repo: Annotated[str | None, Field(description="The repository of the unit it is about, if it names one.")]
    #: The PR it is about, if it names one.
    pr: Annotated[str | None, Field(description="The PR it is about, if it names one.")]


def attend(ctx: Context, request: Attention) -> Outcome[AttentionRecorded]:
    """Record an attention item.

    Returns:
        The tool's text, and the same as fields.

    One the overseer keeps (`kept_items.KEPT`) is recorded once, naming what it is about, and held until that ends it
    (DESIGN §37).

    Raises:
        Refused: Outside a running tick, `repo` is not a repository in this workspace, the item is about a ticket the
            harness decided this tick, its reason is one the harness raises from its causes, or it is one the overseer
            keeps and names nothing that could end it, each of which is recorded.
    """
    current = running_tick(ctx)
    key, pr, detail = request.key, request.pr, request.detail
    unit = _unit(ctx, request.repo)
    if key is not None:
        _refuse_decided(ctx, current.id, key, "attention")
        db.touch_ticket(ctx.conn, key, ctx.repo)
    _refuse_raised(ctx, current.id, request.reason, key=key, repo=unit, pr=pr)
    kept = request.reason in kept_items.KEPT
    if kept:
        _refuse_unnamed(ctx, current.id, request, repo=unit)
    action = f"{attention.ACTION_PREFIX}{request.reason}"
    db.record_decision(ctx.conn, current.id, key, action, detail, repo=unit, pr=pr, kept=kept, item=request.item)
    return Outcome(
        f"recorded attention {request.reason} for {attention.subject(key or f'{attention.PR_PREFIX}{pr}', unit)}"
        + ("; the harness holds it until what it names ends it" if kept else ""),
        AttentionRecorded(reason=request.reason, key=key, repo=unit, pr=pr),
    )


class TicketSet(Request):
    """A ticket's phase, cursors, done flag, or title, or a unit's phase and cursors."""

    #: The ticket.
    key: Key
    #: The unit a phase about a PR, and the review and ci cursors, are for; left out, the ticket's one unit.
    repo: Annotated[
        Repo | None,
        Field(
            description="The unit a phase about a PR, and the review and ci cursors, are for. Left out, the ticket's "
            "one unit, or the workspace's one repository while the ticket has none.",
        ),
    ] = None
    #: The ticket's phase, or a unit's with `repo`.
    phase: Annotated[
        Annotated[
            str,
            one_of("phase", SETTABLE_PHASES),
            WithJsonSchema({"type": "string", "enum": list(SETTABLE_PHASES)}),
        ]
        | None,
        Field(description="The ticket's phase, or a unit's with repo: pushed_no_pr to merged are about a PR."),
    ] = None
    #: The cursors to advance past what was handled. A dry run advances none.
    cursors: Cursors = Field(default_factory=dict)
    #: Mark the ticket done in the journal. A dry run does not.
    done: Annotated[
        StrictBool,
        _null_left_out(lambda: False, StrictBool | None),
        Field(description="Mark the ticket done in the journal. A dry run does not."),
    ] = False
    #: A short name for the ticket, from its own title.
    title: Annotated[
        Annotated[str, AfterValidator(clean_title)] | None,
        Field(description="A short name for the ticket, from its own title: shown beside its key."),
    ] = None


class TicketSets(Request):
    """One or more tickets' or units' settings, recorded together or not at all."""

    #: Each ticket's, or unit's, settings, in the order they are recorded.
    tickets: Annotated[
        tuple[TicketSet, ...],
        # Its one item is checked below, not by `min_length`, which would also refuse a call whose only item is wrong.
        Field(
            json_schema_extra={"minItems": 1},
            description="Each ticket's settings, or a unit's with repo, recorded together or not at all.",
        ),
    ]

    @model_validator(mode="after")
    def _batch(self) -> Self:
        if not self.tickets:
            raise ValueError("name at least one ticket")
        named = [(t.key, t.repo) for t in self.tickets]
        if twice := sorted({attention.subject(*n) for n in named if named.count(n) > 1}):
            raise ValueError(f"set each ticket, or unit, once in a call: {', '.join(twice)} set twice")
        return self


class TicketUpdated(Result):
    """What was recorded of a ticket, or of one of its units."""

    #: The ticket.
    key: Annotated[str, Field(description="The ticket.")]
    #: The unit's repository, when the call named one.
    repo: Annotated[str | None, Field(description="The unit's repository, when the call named one.")]
    #: The phase set, if one was.
    phase: Annotated[str | None, Field(description="The phase set, if one was.")]
    #: The cursors advanced; a dry run advances none.
    cursors: Annotated[tuple[CursorName, ...], Field(description="The cursors advanced; a dry run advances none.")]
    #: Whether the ticket was marked done; a dry run marks none.
    done: Annotated[bool, Field(description="Whether the ticket was marked done; a dry run marks none.")]
    #: Whether this was in a dry run.
    dry_run: Annotated[bool, Field(description="Whether this was in a dry run.")]


class TicketsUpdated(Result):
    """What a call recorded of each ticket, or unit, it named."""

    #: Each ticket or unit updated, in the order given.
    tickets: Annotated[
        tuple[TicketUpdated, ...],
        Field(description="Each ticket or unit updated, in the order given."),
    ]


def ticket_set(ctx: Context, request: TicketSets) -> Outcome[TicketsUpdated]:
    """Record tickets' phases, cursors, done flags, or titles, or units' phases and cursors, all of them or none.

    The comment cursor, the done flag, and the ticket's own phases are the ticket's. The review and ci cursors and the
    phases about a PR, `pushed_no_pr` to `merged`, are a unit's, one per repository the ticket has a PR in; a setting
    that sets one and names no `repo` is about the ticket's one unit. Every setting is checked before any is recorded.

    Returns:
        The tool's text, a line for each setting, naming what a dry run did not do, and the same as fields.

    Raises:
        Refused: CANOPY_TICK_ID names no running tick, or a setting is refused: its `repo` is not a repository in this
            workspace, it sets a unit's phase or cursor with no `repo` and the ticket has no one unit, it is inside a
            tick the harness decided the ticket in, or a cursor names no item observed or passes one the state block
            left out, each of which is recorded. Nothing else in the call is then recorded.
    """
    current = running_tick(ctx)
    several = len(request.tickets) > 1
    checked: list[_Checked] = []
    refusals: list[str] = []
    # Every setting is checked, so one call names every refusal, and each refusal names its ticket among several.
    for setting in request.tickets:
        try:
            checked.append(_check_setting(ctx, current, setting))
        except Refused as e:
            refusals.append(f"{attention.subject(setting.key, setting.repo)}: {e}" if several else str(e))
    if refusals:
        rest = "\nnothing else in the call was recorded: set the rest again" if several else ""
        raise Refused("\n".join(refusals) + rest)
    # A dry run must not advance cursors or mark a ticket done: the first live tick would then miss everything the dry
    # runs saw, or never see the ticket at all.
    dry_run = current.dry_run
    with db.transaction(ctx.conn):
        outcomes = [_record_setting(ctx, c, dry_run=dry_run) for c in checked]
    return Outcome(
        "\n".join(o.text for o in outcomes),
        TicketsUpdated(tickets=tuple(o.result for o in outcomes)),
    )


@dataclass(frozen=True)
class _Checked:
    """A ticket's or unit's setting that passed its checks, with what they resolved, to record with the rest."""

    #: The setting as the call gave it.
    setting: TicketSet
    #: The unit its unit's phase and cursors are for, if it names or sets one.
    unit: str | None
    #: The phase, when it is a unit's.
    unit_phase: str | None


def _check_setting(ctx: Context, current: records.Tick, setting: TicketSet) -> _Checked:
    """Check one ticket's or unit's setting, recording nothing but a refusal.

    Returns:
        The setting, with the unit and phase its checks resolved.

    Raises:
        Refused: As `ticket_set` says, for this setting.
    """
    key, phase = setting.key, setting.phase
    cursors: dict[str, str] = dict(setting.cursors.items())
    unit_cursor = next((name for name in cursors if name in db.UNIT_CURSORS), None)
    unit_phase = phase if phase in vocab.UNIT_PHASES else None
    unit = _unit(ctx, setting.repo)
    if unit is None and (unit_cursor is not None or unit_phase is not None):
        unit = _only_unit(ctx, key, f"a {unit_cursor} cursor" if unit_cursor else f"the {unit_phase} phase")
    _refuse_decided(ctx, current.id, key, "ticket-set")
    if cursors:
        _check_cursors(ctx, current.id, key, unit, cursors)
    return _Checked(setting, unit, unit_phase)


def _record_setting(ctx: Context, checked: _Checked, *, dry_run: bool) -> Outcome[TicketUpdated]:
    """Record one checked setting, inside the call's transaction.

    Returns:
        The tool's text of it, and the same as fields.
    """
    setting, unit, unit_phase = checked.setting, checked.unit, checked.unit_phase
    key, phase, done = setting.key, setting.phase, setting.done
    cursor_pairs: list[tuple[str, str]] = list(setting.cursors.items())
    ignored = [
        *(["cursors not advanced"] if dry_run and cursor_pairs else []),
        *(["not marked done"] if dry_run and done else []),
    ]
    ticket_cursors = {} if dry_run else {n: v for n, v in cursor_pairs if n in db.TICKET_CURSORS}
    db.set_ticket(
        ctx.conn,
        key,
        ctx.repo,
        phase=None if phase is None or unit_phase is not None else vocab.Phase(phase),
        cursors=ticket_cursors,
        done=done and not dry_run,
        title=setting.title,
    )
    if done and not dry_run:
        # A done ticket's notes are invalidated: its work merged or was closed (DESIGN §28, Retention).
        memory.end_ticket_notes(ctx.conn, key, "ticket done")
    unit_cursors: dict[str, str] = {} if dry_run else {n: v for n, v in cursor_pairs if n in db.UNIT_CURSORS}
    if unit is not None and (unit_phase is not None or unit_cursors):
        db.set_unit(ctx.conn, key, ctx.repo, unit, phase=unit_phase, cursors=unit_cursors)
    note = f"; dry run, {' and '.join(ignored)}" if ignored else ""
    return Outcome(
        f"updated {key if unit is None else attention.subject(key, unit)}{note}",
        TicketUpdated(
            key=key,
            repo=unit,
            phase=phase,
            cursors=() if dry_run else tuple(setting.cursors),
            done=done and not dry_run,
            dry_run=dry_run,
        ),
    )


def _check_cursors(ctx: Context, tick_id: int, key: str, repo: str | None, cursors: Mapping[str, str]) -> None:
    """Check a `ticket-set`'s cursors against what the connectors observed, as a dispatch's are (DESIGN §35).

    A dry run checks them too, so its plan holds the refusals a live tick would get (D036).

    Raises:
        Refused: A cursor names no item observed, or passes one the state block left out; the refusal is recorded.
    """
    db.touch_ticket(ctx.conn, key, ctx.repo)
    try:
        claims.check_cursors(ctx, tick_id, datetime.now(UTC), key=key, repo=repo, cursors=cursors)
    except dispatch.Refusal as r:
        db.record_decision(ctx.conn, tick_id, key, f"refused:{r.guard}", r.reason)
        logs.for_tick(tick_id).info("ticket-set refused", extra={"ticket": key, "guard": r.guard, "reason": r.reason})
        raise Refused(f"ticket-set refused ({r.guard}): {r.reason}; the refusal was recorded") from None


# The running tick, which every verb needs (D020).


def current_tick(ctx: Context) -> records.Tick | None:
    """Return the tick this call runs inside, named by CANOPY_TICK_ID, or None outside a tick.

    Raises:
        Refused: CANOPY_TICK_ID is set but does not name a running tick.
    """
    raw = os.environ.get(conversation.TICK_ID_ENV)
    if not raw:
        return None
    row = db.get_tick(ctx.conn, int(raw)) if raw.isdigit() else None
    if row is None or row.status != TickStatus.RUNNING:
        raise Refused(f"{conversation.TICK_ID_ENV}={raw} does not name a running tick")
    return row


def running_tick(ctx: Context) -> records.Tick:
    """Return the tick this call runs inside; refuse outside a tick.

    Raises:
        Refused: CANOPY_TICK_ID is not set, or does not name a running tick.
    """
    row = current_tick(ctx)
    if row is None:
        raise Refused(
            f"no tick is running ({conversation.TICK_ID_ENV} is not set); the overseer's verbs run only inside one",
        )
    return row


def _refuse_decided(ctx: Context, tick_id: int, key: str, verb: str) -> None:
    """Refuse the overseer's `verb` about ticket `key` when the harness decided it in tick `tick_id` (DESIGN §37).

    The harness decided it before the overseer ran, or dispatches it after. The overseer was not shown the ticket, and
    the harness's decision stands: a steered overseer cannot overrule it (TRUST_MODEL T1). The refusal is recorded, as
    a guard's is.

    Raises:
        Refused: The harness decided the ticket this tick.
    """
    if (reason := _decided_by_harness(ctx, tick_id, key, verb)) is not None:
        raise Refused(f"{verb} refused ({DECIDED}): {reason}; the refusal was recorded")


def _decided_by_harness(ctx: Context, tick_id: int, key: str, verb: str) -> str | None:
    """Record the refusal of `verb` about `key` if the harness decided the ticket in tick `tick_id`.

    Returns:
        The refusal's reason, or None when the ticket is the overseer's to decide.
    """
    if harness.decided(ctx.conn, tick_id, key):
        where = "decided"
        shown = "harness"
    elif key in harness_dispatches.tickets(ctx, tick_id):
        where = "dispatches"
        shown = "dispatches_to_come"
    else:
        return None
    reason = f"the harness {where} {key} this tick (the state block's `{shown}`); record nothing about it"
    db.record_decision(ctx.conn, tick_id, key, attention.REFUSED_DECIDED, reason)
    logs.for_tick(tick_id).info("refused: decided by the harness", extra={"ticket": key, "verb": verb})
    return reason


def _refuse_raised(
    ctx: Context,
    tick_id: int,
    reason: str,
    *,
    key: str | None,
    repo: str | None,
    pr: str | None,
) -> None:
    """Refuse the overseer an attention item of `reason` when the harness raises it from its causes (DESIGN §37).

    The harness raises it while its cause holds and ends it when the cause is gone, so the overseer neither records nor
    drops one (TRUST_MODEL T1). The refusal is recorded, as a guard's is, and counts as the ticket's decision.

    Raises:
        Refused: `reason` is one the harness raises.
    """
    if reason not in attention.FROM_CAUSES | attention.ONLY_FROM_CAUSES:
        return
    why = f"the harness raises {reason} itself while its cause holds, and ends it when the cause is gone"
    db.record_decision(ctx.conn, tick_id, key, f"refused:{RAISED}", why, repo=repo, pr=pr)
    logs.for_tick(tick_id).info("refused: raised by the harness", extra={"ticket": key, "reason": reason})
    raise Refused(f"attention refused ({RAISED}): {why}; the refusal was recorded")


def _refuse_unnamed(ctx: Context, tick_id: int, request: Attention, *, repo: str | None) -> None:
    """Refuse the overseer an item it keeps that names nothing that could end it (DESIGN §37, `core.kept_items`).

    The harness holds such an item until what it names ends it, so one naming nothing would never end. The refusal is
    recorded, as a guard's is, and counts as the ticket's decision.

    Raises:
        Refused: It names no ticket, a `notice_rerun` names no check run, or `item` is not one of its subject's.
    """
    why = kept_items.unnamed(ctx.conn, key=request.key, reason=request.reason, repo=repo, item=request.item)
    if why is None:
        return
    db.record_decision(ctx.conn, tick_id, request.key, f"refused:{UNNAMED}", why, repo=repo, pr=request.pr)
    logs.for_tick(tick_id).info("refused: names nothing", extra={"ticket": request.key, "reason": request.reason})
    raise Refused(f"attention refused ({UNNAMED}): {why}; the refusal was recorded")


# How the verbs above do their parts.


def _only_unit(ctx: Context, key: str, what: str) -> str:
    """Return the unit a `ticket-set` that names no repository is about: the ticket's one unit.

    A ticket with no unit yet has the workspace's one repository, if it has one.

    Raises:
        Refused: The ticket has several units, or none in a workspace of several repositories.
    """
    units = [u.repo for u in db.units(ctx.conn, key) if u.repo is not None]
    names = units or [r.name for r in ctx.workspace.repos]
    if len(names) == 1:
        return names[0]
    has = (
        f"{key} has units in {', '.join(units)}" if units else f"{key} has no unit yet: name one of {', '.join(names)}"
    )
    raise Refused(f"repo is required: {what} belongs to one unit, and {has}")


def _unit(ctx: Context, repo: str | None) -> str | None:
    """Return the repository `repo` names, checked against the map, or None if it names none.

    Raises:
        Refused: `repo` is not a repository in this workspace.
    """
    ws = ctx.workspace
    if repo is None:
        return None
    found = ws.repo(repo)
    if found is None:
        names = ", ".join(r.name for r in ws.repos) or "none yet"
        raise Refused(f"{repo!r} is not a repository in this workspace ({names})")
    return found.name


def _where(started: dispatch.Started) -> str:
    """Return where a dispatch's decision says the run works: its slots, and its desk."""
    where = " in " + ", ".join(f"{s.repo} at {s.slot_path}" for s in started.slots)
    return where + (f"; desk {started.desk}" if started.desk is not None else "")


def _would(kind: str, work: str, in_repo: str) -> str:
    """Return what a dry run's decision says the run would have done."""
    if kind in policy.TICKET_KINDS:
        return f"dry run: not dispatched; would {work}"
    if kind == policy.FEEDBACK_PLAN:
        return f"dry run: not dispatched; would {work}{in_repo}"
    return f"dry run: not dispatched; would work on {work}{in_repo}"


def _work(key: str, kind: str, branch: str, base: str | None, repos: Sequence[str]) -> str:
    """Return what a dispatch's decision says the run works on: its branch, or for a kind counted per ticket, its key.

    A plan works on no branch: it reads its repositories, and writes a plan. A feedback plan reads its branch, and
    writes the plan its `resume` waits on (DESIGN §32).
    """
    if kind == policy.FEEDBACK_PLAN:
        return f"plan the feedback on {branch}"
    if kind == policy.PLAN:
        return f"plan {key} over {', '.join(repos)}"
    return f"{branch} on {base}" if base is not None else branch


def _handles(cursor_pairs: Iterable[tuple[str, str]], review_run: int | None) -> frozenset[str]:
    """What the dispatch handles, each needing its reason (DESIGN §8).

    Returns:
        The cursors it moves, and `review_run` when it names one.
    """
    return frozenset(name for name, _ in cursor_pairs) | ({"review_run"} if review_run is not None else frozenset())


def _for(reasons: Collection[str]) -> str:
    """How a decision's rationale names a resume's reasons.

    Returns:
        `for` and the reasons, in the vocabulary's order.
    """
    return f"for {', '.join(r for r in ResumeReason if r in reasons)}"


def _review_findings(
    conn: sqlite3.Connection,
    key: str,
    kind: str,
    repos: Sequence[str],
    run_id: int | None,
) -> str | None:
    """Return the worker's `{{REVIEW_FINDINGS}}` for `review_run`, or None without it (DESIGN §21).

    Raises:
        dispatch.Refusal: `review_run` is given for a kind other than `resume`, or its review run is missing, of
            another ticket or repository, not `done`, or found nothing.
    """
    if run_id is None:
        return None
    if kind != RunKind.RESUME:
        raise dispatch.Refusal(
            "bad_review",
            "review_run names findings for a resume to address; it is for resume only",
        )
    try:
        return findings.for_worker(conn, run_id, key, repos)
    except findings.Unusable as e:
        raise dispatch.Refusal("bad_review", str(e)) from None
