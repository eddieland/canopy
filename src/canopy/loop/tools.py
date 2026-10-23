"""The overseer's verbs (DESIGN §6, §27): each one a request that holds its bounds, and a function that does it.

A request is a pydantic model (D026) that refuses an unknown field and is the verb's MCP schema. It validates what
the overseer passes in, keys, reasons, phases, cursor ids, and free text, which later reach branch names, argv, and
prompts, and the rules across its fields. The `canopy` commands and the MCP server (`loop.mcp`) both build a request
and call its verb, so a tool and its command cannot drift apart.

A verb returns an `Outcome`: the text its command prints, and a result, a model whose fields say what it did and whose
schema is its tool's output schema. A request that does not validate is what the command calls misuse, exit 2; a
guard's refusal, or a call outside a running tick, is `Refused`, exit 1. Either way the text is the same.

This module holds what every verb shares, the bounds, the `Request` and `Result` bases, and the running tick, and the
ticket's verbs:
dispatch, decide, queried, attention, ticket set, and mirror. A feature's own verbs are in a module of their own, the
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
    ValidationError,
    WithJsonSchema,
    model_validator,
)
from pydantic_core import PydanticUndefined

from canopy.core import config, contract, conversation, db, memory, vocab
from canopy.core.vocab import ResumeReason, RunKind, TickStatus
from canopy.infra import logs
from canopy.loop import attention, claims, duties, harness, harness_dispatches
from canopy.reviews import findings, grants
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
#: A review cursor is a time, the one form every kind of review feedback shares (DESIGN §7).
REVIEW_CURSOR_RE = re.compile(r"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z")
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
#: The phases the overseer sets. `split` is retired (M46): old tickets may still hold it, and nothing sets it.
SETTABLE_PHASES = tuple(p.value for p in vocab.Phase if p is not vocab.Phase.SPLIT)


class Refused(Exception):  # noqa: N818  (a refusal is an outcome the overseer is told about, not an error)
    """A guard refused the call, or it came from outside a running tick. Its text is what the command prints."""


def explain(error: ValidationError) -> str:
    """Say what was wrong with a request, as the overseer reads it from a tool's error or a command's usage error.

    It names each field and what was wrong with it, never pydantic's copy of the input; a check echoes a value only for
    short, bounded fields, never a body: a mirrored comment's body is the tracker's.

    Returns:
        One line per problem: a rule across fields as its own sentence, a field's as `field: problem`.
    """
    lines: list[str] = []
    for problem in error.errors(include_url=False, include_input=False):
        where = ".".join(str(part) for part in problem["loc"])
        cause = (problem.get("ctx") or {}).get("error")
        what = str(cause) if problem["type"] == "value_error" and cause is not None else problem["msg"]
        lines.append(f"{where}: {what}" if where else what)
    return "\n".join(lines)


# The bounds of what the overseer passes in, each as a check the click parameter types share.


def valid_key(value: str) -> bool:
    """Keys reach branch names, lease holders, paths, and argv (DESIGN §17).

    Returns:
        True when `value` matches `KEY_RE` in full.
    """
    return KEY_RE.fullmatch(value) is not None


def valid_review_cursor(value: str) -> bool:
    """A review cursor names a real moment in one fixed form, so cursors compare as strings (DESIGN §7).

    Returns:
        True when `value` is in the form `YYYY-MM-DDTHH:MM:SSZ` and names a real time.
    """
    if REVIEW_CURSOR_RE.fullmatch(value) is None:
        return False
    try:
        db.parse_time(value)
    except ValueError:
        return False
    return True


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
    # A message cursor is a journal message id (DESIGN §22).
    if name == "message" and not (cursor_id.isascii() and cursor_id.isdigit()):
        raise ValueError(f"a message cursor is a message id, a number; got {cursor_id!r}")
    if name == "review" and not valid_review_cursor(cursor_id):
        raise ValueError(
            f"a review cursor is the newest handled item's time in UTC, as YYYY-MM-DDTHH:MM:SSZ; got {cursor_id!r}",
        )
    return name, cursor_id


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

    A field left out is a guard's refusal, which the decisions record as the command's is; the schema still tells the
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
        description="Cursors to advance past what you handled, by name. comment and message are the ticket's; review "
        "(a UTC time, YYYY-MM-DDTHH:MM:SSZ) and ci a unit's, one repository's.",
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
class Outcome[R: Result]:
    """What a verb did, as its command prints it and as its tool returns it."""

    #: What the command prints, and the tool's text.
    text: str
    #: The same as fields: the tool's structured content.
    result: R


# The verbs, each its request, its result, then its function.


class Dispatch(Request):
    """A worker started on a ticket."""

    # `repos` left out is the dispatch guard's refusal, recorded as the command's is, so the request takes it.
    model_config = ConfigDict(json_schema_extra=required("repos"))

    #: The ticket.
    key: Key
    #: What the worker does. `fix-ci` and `split` are taken only to be refused naming what replaced them, a refusal
    #: the decisions record, so the schema does not offer them.
    kind: Annotated[
        RunKind,
        BeforeValidator(_known_kind),
        WithJsonSchema({"type": "string", "enum": list(policy.DISPATCH_KINDS)}),
        Field(description="What the worker does."),
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
        Field(description="resume only, and required for it: why it runs, each once."),
    ] = ()
    #: What the worker should read or do: links, comment ids, check names. Never quoted text.
    context: Annotated[
        Text | None,
        Field(description="What the worker should read or do. Never quoted ticket or PR text."),
    ] = None
    #: The cursors to advance, only if the worker starts.
    cursors: Cursors = Field(default_factory=dict)

    @model_validator(mode="after")
    def _one_unit(self) -> Self:
        unit_cursors = [name for name in self.cursors if name in db.UNIT_CURSORS]
        if unit_cursors and len(set(self.repos)) > 1:
            raise ValueError(
                f"cursors: a {unit_cursors[0]} cursor belongs to one unit, so repos (--repo) names one; advance it "
                f"after with ticket-set and its repo (`canopy ticket set {self.key} --repo NAME`)",
            )
        return self


class Dispatched(Result):
    """A worker started on a ticket, or in a dry run, one its guards would start."""

    #: The ticket.
    key: Annotated[str, Field(description="The ticket.")]
    #: What the worker does.
    kind: Annotated[RunKind, Field(description="What the worker does.")]
    #: Whether this was a dry run, which started nothing.
    dry_run: Annotated[bool, Field(description="Whether this was a dry run, which started nothing.")]
    #: The run that started; none in a dry run.
    run: Annotated[int | None, Field(description="The run that started; none in a dry run.")]
    #: The branch it works on; empty for a plan, which works on none.
    branch: Annotated[str, Field(description="The branch it works on; empty for a plan, which works on none.")]
    #: The repositories it works in, a unit each.
    repos: Annotated[tuple[str, ...], Field(description="The repositories it works in, a unit each.")]


def dispatch_run(ctx: Context, request: Dispatch) -> Outcome[Dispatched]:
    """Start a worker on a ticket, if its guards allow one now; in a dry run, check them and start nothing (D036).

    Returns:
        What the command prints, the run that started or what a dry run would have started, and the same as fields.

    Raises:
        Refused: Outside a running tick, or a guard refused the dispatch, which is recorded.
    """
    current = running_tick(ctx)
    key, kind, repos, reasons = request.key, request.kind, request.repos, request.reasons
    cursor_pairs: list[tuple[str, str]] = list(request.cursors.items())
    unit_cursors = [name for name, _ in cursor_pairs if name in db.UNIT_CURSORS]
    tick_id = current.id
    _refuse_decided(ctx, tick_id, key, "dispatch")
    log = logs.for_tick(tick_id)
    db.touch_ticket(ctx.conn, key, ctx.repo)
    handles = _handles(cursor_pairs, request.review_run)
    # The workers the harness's runs to come hold ahead of this one, in §7's order (DESIGN §37).
    reserved = harness_dispatches.reserved(ctx, tick_id, kind, reasons)
    try:
        dispatch.check_kind(kind)
        review = _review_findings(ctx.conn, key, kind, repos, request.review_run)
        # The claims, checked against what the connectors observed, before §8's other guards (DESIGN §35).
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
            branch, queue_label, repo_names, starts = plan.branch, plan.label, plan.repos, plan.starts
            started = None
        else:
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
                cursors=handles,
                reserved=reserved,
            )
            branch, queue_label, repo_names, starts = started.branch, started.label, started.repos, started.starts
    except dispatch.Refusal as r:
        db.record_decision(ctx.conn, tick_id, key, f"refused:{r.guard}", r.reason)
        if r.attention is not None:
            # The overseer wants work a guard forbids, and only a human can lift it: the attempt limit, a retired
            # prompt override, or a persona canopy cannot use (DESIGN §8, §14, §31). In a workspace of several, the
            # item is about the unit it holds.
            db.record_decision(ctx.conn, tick_id, key, f"{attention.ACTION_PREFIX}{r.attention}", r.reason, repo=r.repo)
        log.info("dispatch refused", extra={"ticket": key, "kind": kind, "guard": r.guard, "reason": r.reason})
        raise Refused(f"dispatch refused ({r.guard}): {r.reason}; the refusal was recorded") from None
    # `base` passed the guards, so it is the branch this run is stacked on. `queue_label` is the configured spelling, or
    # empty for a private ticket, which its start record authorizes (DESIGN §22). Under `tracker.private` the label
    # authorizes a ticket's first run, which starts it privately.
    authorized = f"label {queue_label}" if queue_label else "private: started by the operator"
    authorized += "; starts it privately (tracker.private)" if starts else ""
    in_repo = f" in {', '.join(repo_names)}"
    work = _work(key, kind, branch, request.base, repo_names)
    requested = f"; review run {request.review_run}" if request.review_run is not None else ""
    requested += f"; {_for(reasons)}" if reasons else ""
    if started is None:
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
            Dispatched(key=key, kind=kind, dry_run=True, run=None, branch=branch, repos=repo_names),
        )
    # Cursors advance only now, so what a refused dispatch was meant to handle is still new next tick.
    ticket_cursors = {name: value for name, value in cursor_pairs if name in db.TICKET_CURSORS}
    db.set_ticket(ctx.conn, key, ctx.repo, cursors=ticket_cursors)
    if unit_cursors:
        cursors = {name: value for name, value in cursor_pairs if name in db.UNIT_CURSORS}
        db.set_unit(ctx.conn, key, ctx.repo, repo_names[0], cursors=cursors)
    rationale = f"run {started.run_id}: {work}{_where(started)}; {authorized}{requested}"
    db.record_decision(ctx.conn, tick_id, key, f"dispatch:{kind}", rationale)
    log.info("dispatched", extra={"ticket": key, "kind": kind, "run_id": started.run_id, "pid": started.pid})
    return Outcome(
        f"dispatched {kind} for {key}: {rationale}",
        Dispatched(key=key, kind=kind, dry_run=False, run=started.run_id, branch=branch, repos=repo_names),
    )


class Decide(Request):
    """A decision about a ticket, or a tick-wide skip."""

    #: The ticket; none only for a tick-wide skip.
    key: Annotated[Key | None, Field(description="The ticket; omit it only for a tick-wide skip.")] = None
    #: What was decided.
    action: Literal["wait", "skip", "done"]
    #: Why, in the overseer's own words.
    rationale: Annotated[
        Text,
        Field(
            description="Why, in your own words. A skip with no key starts 'mcp_unavailable:' or "
            "'tracker_unsupported:'; a skip with a key may not.",
        ),
    ]

    @model_validator(mode="after")
    def _form(self) -> Self:
        key, action, rationale = self.key, self.action, self.rationale
        if key is None and action != "skip":
            raise ValueError(f"{action!r} needs a ticket key; only a tick-wide 'skip' may omit it")
        # A skip's form is checked, not left to the overseer's guess: a tick-wide reason under a made-up key skips
        # nothing and leaves the tick going on, and a ticket's skip without its key would close the whole tick
        # `skipped`.
        reasons = " or ".join(f"'{reason}: ...'" for reason in duties.TICK_WIDE_SKIPS)
        if key is None and not duties.tick_wide(rationale):
            raise ValueError(
                f"a skip with no key skips the whole tick, so its rationale is {reasons}; "
                "a skip about one ticket names its key",
            )
        if key is not None and action == "skip" and duties.tick_wide(rationale):
            raise ValueError(
                f"{rationale.split(':', 1)[0].strip()!r} skips the whole tick, so it names no key: leave key out "
                "(a decide of skip with only a rationale), only when the tick cannot go on; "
                "otherwise decide each ticket under its own key",
            )
        return self


class Decided(Result):
    """A decision recorded about a ticket, or about the whole tick."""

    #: The ticket; none for a tick-wide skip.
    key: Annotated[str | None, Field(description="The ticket; none for a tick-wide skip.")]
    #: What was decided.
    action: Annotated[Literal["wait", "skip", "done"], Field(description="What was decided.")]


def decide(ctx: Context, request: Decide) -> Outcome[Decided]:
    """Record a decision.

    Returns:
        What the command prints, and the same as fields.

    Raises:
        Refused: Outside a running tick, or about a ticket the harness decided this tick, which is recorded.
    """
    current = running_tick(ctx)
    if request.key is not None:
        _refuse_decided(ctx, current.id, request.key, "decide")
        db.touch_ticket(ctx.conn, request.key, ctx.repo)
    db.record_decision(ctx.conn, current.id, request.key, request.action, request.rationale)
    return Outcome(
        f"recorded {request.action} for {request.key or 'this tick'}",
        Decided(key=request.key, action=request.action),
    )


class Queried(Request):
    """That this tick ran the tracker query, naming each open ticket it returned."""

    #: Each open ticket the query returned; none when it returned none.
    keys: Annotated[
        tuple[Key, ...],
        Field(description="Each open ticket the query returned; none when it returned none."),
    ] = ()

    @model_validator(mode="after")
    def _fits(self) -> Self:
        found = list(dict.fromkeys(self.keys))
        if len(duties.queried_rationale(found)) > MAX_TEXT:
            raise ValueError(f"{len(found)} keys do not fit in one call: name them in several")
        return self


class QueryRecorded(Result):
    """The tracker query recorded, with the open tickets it returned."""

    #: Each open ticket named, once, in the order first named.
    keys: Annotated[tuple[str, ...], Field(description="Each open ticket named, once, in the order first named.")]


def queried(ctx: Context, request: Queried) -> Outcome[QueryRecorded]:
    """Record the tracker query, and each ticket it returned, which is owed a decision this tick.

    Returns:
        What the command prints, and the same as fields.

    Raises:
        Refused: Outside a running tick.
    """
    current = running_tick(ctx)
    found = duties.record_queried(ctx.conn, current.id, ctx.repo, request.keys)
    return Outcome(
        f"recorded the query: {found} open ticket(s)",
        QueryRecorded(keys=tuple(dict.fromkeys(request.keys))),
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

    @model_validator(mode="after")
    def _about(self) -> Self:
        if self.key is None and self.pr is None:
            raise ValueError("key or pr is required (KEY, or --pr): an item is about a ticket, or a PR with no ticket")
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
        What the command prints, and the same as fields.

    Raises:
        Refused: Outside a running tick, `repo` is not a repository in this workspace, or the item is about a ticket
            the harness decided this tick, which is recorded.
    """
    current = running_tick(ctx)
    key, pr, detail = request.key, request.pr, request.detail
    unit = _unit(ctx, request.repo)
    if key is not None:
        _refuse_decided(ctx, current.id, key, "attention")
        db.touch_ticket(ctx.conn, key, ctx.repo)
    if request.reason == "review_limit" and pr is not None:
        # However the overseer words it, the item names what lifts the limit (DESIGN §21).
        detail = f"{detail}; {grants.hint(pr)}"
    action = f"{attention.ACTION_PREFIX}{request.reason}"
    db.record_decision(ctx.conn, current.id, key, action, detail, repo=unit, pr=pr)
    return Outcome(
        f"recorded attention {request.reason} for {attention.subject(key or f'{attention.PR_PREFIX}{pr}', unit)}",
        AttentionRecorded(reason=request.reason, key=key, repo=unit, pr=pr),
    )


class TicketSet(Request):
    """A ticket's phase, cursors, done flag, or title, or a unit's phase and cursors."""

    #: The ticket.
    key: Key
    #: The unit a phase about a PR, and the review and ci cursors, are for.
    repo: Annotated[
        Repo | None,
        Field(description="The unit a phase about a PR, and the review and ci cursors, are for."),
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

    @model_validator(mode="after")
    def _units(self) -> Self:
        unit_pairs = [name for name in self.cursors if name in db.UNIT_CURSORS]
        unit_phase = self.phase if self.phase in vocab.UNIT_PHASES else None
        if self.repo is None and (unit_pairs or unit_phase is not None):
            what = f"a {unit_pairs[0]} cursor" if unit_pairs else f"the {unit_phase} phase"
            raise ValueError(f"repo is required (--repo): {what} belongs to one unit")
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


def ticket_set(ctx: Context, request: TicketSet) -> Outcome[TicketUpdated]:
    """Record a ticket's phase, cursors, done flag, or title, or a unit's phase and cursors.

    The comment cursor, the done flag, and the ticket's own phases are the ticket's. The review and ci cursors and the
    phases about a PR, `pushed_no_pr` to `merged`, are a unit's, one per repository the ticket has a PR in. It runs
    outside a tick too, where the operator runs it and its cursors are not checked.

    Returns:
        What the command prints, naming what a dry run did not do, and the same as fields.

    Raises:
        Refused: CANOPY_TICK_ID names no running tick, `repo` is not a repository in this workspace, or inside a tick
            the harness decided the ticket in, or a cursor names no item observed or passes one the state block left
            out, each of which is recorded.
    """
    key, phase, done = request.key, request.phase, request.done
    cursor_pairs: list[tuple[str, str]] = list(request.cursors.items())
    unit_pairs = [(name, value) for name, value in cursor_pairs if name in db.UNIT_CURSORS]
    unit_phase = phase if phase in vocab.UNIT_PHASES else None
    unit = _unit(ctx, request.repo)
    current = current_tick(ctx)
    if current is not None:
        _refuse_decided(ctx, current.id, key, "ticket set")
        if cursor_pairs:
            _check_cursors(ctx, current.id, key, unit, dict(cursor_pairs))
    # A dry run must not advance cursors or mark a ticket done: the first live tick would then miss everything the dry
    # runs saw, or never see the ticket at all.
    dry_run = current is not None and current.dry_run
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
        title=request.title,
    )
    if done and not dry_run:
        # A done ticket's notes are invalidated: its work merged or was closed (DESIGN §28, Retention).
        memory.end_ticket_notes(ctx.conn, key, "ticket done")
    unit_cursors: dict[str, str] = {} if dry_run else dict(unit_pairs)
    if unit is not None and (unit_phase is not None or unit_cursors):
        db.set_unit(ctx.conn, key, ctx.repo, unit, phase=unit_phase, cursors=unit_cursors)
    note = f"; dry run, {' and '.join(ignored)}" if ignored else ""
    return Outcome(
        f"updated {key if request.repo is None else attention.subject(key, unit)}{note}",
        TicketUpdated(
            key=key,
            repo=unit,
            phase=phase,
            cursors=() if dry_run else tuple(request.cursors),
            done=done and not dry_run,
            dry_run=dry_run,
        ),
    )


def _check_cursors(ctx: Context, tick_id: int, key: str, repo: str | None, cursors: Mapping[str, str]) -> None:
    """Check a `ticket set`'s cursors against what the connectors observed, as a dispatch's are (DESIGN §35).

    A dry run checks them too, so its plan holds the refusals a live tick would get (D036).

    Raises:
        Refused: A cursor names no item observed, or passes one the state block left out; the refusal is recorded.
    """
    db.touch_ticket(ctx.conn, key, ctx.repo)
    try:
        claims.check_cursors(ctx, tick_id, datetime.now(UTC), key=key, repo=repo, cursors=cursors)
    except dispatch.Refusal as r:
        db.record_decision(ctx.conn, tick_id, key, f"refused:{r.guard}", r.reason)
        logs.for_tick(tick_id).info("ticket set refused", extra={"ticket": key, "guard": r.guard, "reason": r.reason})
        raise Refused(f"ticket set refused ({r.guard}): {r.reason}; the refusal was recorded") from None


class Mirror(Request):
    """A tracker comment, copied into a ticket's conversation in the journal for the operator to read."""

    #: What the comment is on: a ticket key, REPO#N, or a PR's URL.
    ref: Annotated[str, Field(description="What the comment is on: a ticket key, REPO#N, or a PR's URL.")]
    #: The tracker's id of the comment.
    comment: Annotated[str, Field(description="The tracker's id of the comment.")]
    #: Its author's account id on the tracker.
    author: Annotated[str, Field(description="Its author's account id on the tracker.")]
    #: When the tracker says it was written.
    at: Annotated[str, Field(description="When the tracker says it was written, ISO 8601.")]
    #: Its text, cut to `conversation.MAX_MIRRORED` characters and marked truncated.
    body: Annotated[
        str,
        Field(description=f"Its text; cut to {conversation.MAX_MIRRORED} characters, and marked truncated."),
    ]


class CommentMirrored(Result):
    """A tracker comment, as the ticket's conversation in the journal holds it."""

    #: The journal's message that holds it.
    message: Annotated[int, Field(description="The journal's message that holds it.")]
    #: Whether this call recorded it, rather than finding it already recorded.
    new: Annotated[bool, Field(description="Whether this call recorded it, rather than finding it already recorded.")]
    #: Whether its body was cut.
    truncated: Annotated[bool, Field(description="Whether its body was cut.")]


def mirror(ctx: Context, request: Mirror) -> Outcome[CommentMirrored]:
    """Record a tracker comment in a ticket's conversation. Recording it again records nothing new.

    A mirrored comment is a copy for the operator to read, and authorizes nothing.

    Returns:
        What the command prints, and the same as fields.

    Raises:
        Refused: Outside a running tick, or a guard refused the comment, which is recorded.
    """
    current = running_tick(ctx)
    tick_id = current.id
    log = logs.for_tick(tick_id)
    ref, comment_id = request.ref, request.comment
    key: str | None = None
    try:
        subject = conversation.parse_ref(ref)
        key = subject.id if subject.kind == conversation.TICKET else None
        mirrored = conversation.mirror(
            ctx.conn,
            ctx.config,
            subject,
            tick_id=tick_id,
            dry_run=current.dry_run,
            repo=ctx.repo,
            comment_id=comment_id,
            author=request.author,
            at=request.at,
            body=request.body,
        )
    except conversation.Refused as r:
        if key is not None:
            db.touch_ticket(ctx.conn, key, ctx.repo)
        db.record_decision(ctx.conn, tick_id, key, f"refused:{r.guard}", r.reason)
        log.info("mirror refused", extra={"ticket": key, "comment": comment_id[:100], "guard": r.guard})
        raise Refused(f"mirror refused ({r.guard}): {r.reason}; the refusal was recorded") from None
    log.info(
        "comment mirrored",
        extra={"ticket": key, "comment": comment_id, "message_id": mirrored.message_id, "new": mirrored.new},
    )
    result = CommentMirrored(message=mirrored.message_id, new=mirrored.new, truncated=mirrored.truncated)
    if mirrored.new:
        cut = ", truncated" if mirrored.truncated else ""
        text = f"mirrored comment {comment_id} on {ref} as message {mirrored.message_id} ({mirrored.source}{cut})"
        return Outcome(text, result)
    text = f"comment {comment_id} on {ref} is already message {mirrored.message_id}; nothing new recorded"
    return Outcome(text, result)


# The running tick, which every verb but `ticket set` needs (D020).


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
    if harness.decided(ctx.conn, tick_id, key):
        where = "decided"
        shown = "harness"
    elif key in harness_dispatches.tickets(ctx, tick_id):
        where = "dispatches"
        shown = "dispatches_to_come"
    else:
        return
    reason = f"the harness {where} {key} this tick (the state block's `{shown}`); record nothing about it"
    db.record_decision(ctx.conn, tick_id, key, attention.REFUSED_DECIDED, reason)
    logs.for_tick(tick_id).info("refused: decided by the harness", extra={"ticket": key, "verb": verb})
    raise Refused(f"{verb} refused ({DECIDED}): {reason}; the refusal was recorded")


# How the verbs above do their parts.


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
            "review_run (--review-run) names findings for a resume to address; it is for resume only",
        )
    try:
        return findings.for_worker(conn, run_id, key, repos)
    except findings.Unusable as e:
        raise dispatch.Refusal("bad_review", str(e)) from None
