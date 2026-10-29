"""A running agent's card: where its work stands, in its own words, while it runs (DESIGN §41).

A worker, a planner, or a reviewer says where its work stands by calling canopy's `status` tool, each call its whole
card: a summary, what it does now, what is done with the proof of each, what is next, what is in its way, for a long
job its steps, each with a status and a stage, from which canopy says how much is done, and a question it works around
while the operator decides, with lettered options and the one it recommends. The
harness reads the call from the events the agent prints, as it reads the agent's spend, holds it to the tool's own
input, and records it on the run, with how many tool calls the agent had made by then; a call that does not validate,
or that ended in an error, records nothing. So nothing the agent writes reaches the journal but what canopy observes it
print (TRUST_MODEL T1). The card is shown to the operator, and given to no agent.

The run keeps its last card once it ends. A card is as old as the time and the tool calls since it was recorded. A step
is as old as the first card on which it was working: one working longer than the run's last fifth is shown stuck. A
question is as old as the first card that asked it, and keeps the operator's answer, one of its letters, while the
cards after it ask it still.

The answer reaches the running agent through a file canopy writes in the run's answers directory, which the run is
told of in `CANOPY_ANSWERS` and, sandboxed, may read but not write: canopy's plugin reads it on each tool call and tells
the agent once (`.agents/plugins/canopy.js`). An unsandboxed run could write it, as it could any of the operator's
files; what it wrote could only name one of its own options.
"""

from __future__ import annotations

import contextlib
import json
import os
import re
import shutil
import sqlite3
import sys
import threading
from collections.abc import Mapping
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import TYPE_CHECKING, Annotated, Literal

from pydantic import (
    AfterValidator,
    BaseModel,
    BeforeValidator,
    ConfigDict,
    Field,
    StrictStr,
    ValidationError,
    model_validator,
)

from canopy.core import db, items, records, sql
from canopy.core.vocab import ReviewRunStatus, RunStatus
from canopy.infra import text
from canopy.runtime import servers

if TYPE_CHECKING:
    from canopy.runtime.report import Called

#: The server of the `status` tool, as a run's inline config names it, and the tool: the agent sees it as
#: `canopy_run_status`.
SERVER = "canopy_run"
TOOL = "status"
#: How the runtime starts the server: this interpreter's canopy, which `-P` keeps off the working directory's modules
#: (TRUST_MODEL T7).
SERVER_COMMAND = (sys.executable, "-P", "-m", "canopy", "_mcp", "--status")
#: A run's CANOPY_RUN_ID that names a run keeping a card: a worker's or a planner's id, or a review's, `review-7`.
RUN_ID_RE = re.compile(r"(?:review-)?[0-9]{1,18}")
#: The variable that names a run's answers directory, and the file in it that holds the operator's latest answer.
ANSWERS_ENV = "CANOPY_ANSWERS"
ANSWER_FILE = "answer.json"
#: The run tables whose runs keep a card: a worker's and a planner's, and a review's.
type CardTable = Literal["runs", "review_runs"]
#: Each card table's status of a run still running.
_RUNNING: Mapping[CardTable, RunStatus | ReviewRunStatus] = {
    "runs": RunStatus.RUNNING,
    "review_runs": ReviewRunStatus.RUNNING,
}

#: How long the summary and what is in the way may be, and every other line, in characters.
MAX_SUMMARY = 400
MAX_LINE = 200
#: How many steps `done` and `next` may each hold, and how many `steps` may.
MAX_STEPS = 20
MAX_PLAN_STEPS = 40
#: A step's status, on the card's `steps`.
type StepStatus = Literal["not_started", "working", "blocked", "done", "skipped"]
#: The share of a run's time limit a step may stay working before it is shown stuck: its last fifth's length.
STUCK_SHARE = 5
#: How many tool calls, or minutes, a running run may go with no update to its card before the card is shown stale.
#: canopy's plugin asks the agent for one at the same count of calls (`.agents/plugins/canopy.js`, DESIGN §41).
STALE_CALLS = 20
STALE_MINUTES = 10
#: The letters a question's options go by, in order, and so how many it may have.
type Letter = Literal["A", "B", "C", "D", "E"]
LETTERS: tuple[Letter, ...] = ("A", "B", "C", "D", "E")


def _line(value: str) -> str:
    """One line of a card: control characters made spaces, whitespace collapsed, and not empty.

    Returns:
        The line.

    Raises:
        ValueError: Nothing printable is left.
    """
    line = " ".join("".join(c if c.isprintable() else " " for c in value).split())
    if not line:
        raise ValueError("must not be empty")
    return line


#: A line of a card: plain text, held to `MAX_LINE` characters before its whitespace is collapsed.
Line = Annotated[StrictStr, Field(max_length=MAX_LINE), AfterValidator(_line)]


def _one_or_more(value: object) -> object:
    """A lone line where a card's list of lines goes, as a list of one: an agent with one step left often sends so.

    Returns:
        The value, or a lone string as a one-item tuple.
    """
    return (value,) if isinstance(value, str) else value


class Done(BaseModel):
    """A finished step, with what shows it is done."""

    model_config = ConfigDict(extra="forbid", frozen=True, defer_build=True)

    step: Line = Field(description="What was done.")
    proof: Line = Field(description='What shows it, such as "tests pass: 42/42", "pushed abc123", or "not pushed".')


class Step(BaseModel):
    """One step of a long job, with where it stands."""

    model_config = ConfigDict(extra="forbid", frozen=True, defer_build=True)

    title: Line = Field(description="The step, as its plan names it when there is one.")
    status: StepStatus = Field(description="Where it stands.")
    stage: Line | None = Field(
        default=None,
        description="The stage it belongs to, such as the plan's section, or what part of it is under way; or omit it.",
    )


class Question(BaseModel):
    """A decision the agent asks the operator for, with lettered options, which it works around while it waits."""

    model_config = ConfigDict(extra="forbid", frozen=True, defer_build=True)

    ask: Annotated[StrictStr, Field(max_length=MAX_SUMMARY), AfterValidator(_line)] = Field(
        description="What you need the operator to decide, in a sentence or two.",
    )
    options: tuple[Line, ...] = Field(
        min_length=2,
        max_length=len(LETTERS),
        description="The choices, in order: the first is A, the next B, and so on.",
    )
    recommend: Letter = Field(description="The letter of the option you recommend, and work toward meanwhile.")

    @model_validator(mode="after")
    def _recommends_an_option(self) -> Question:
        if LETTERS.index(self.recommend) >= len(self.options):
            raise ValueError(f"recommend names no option: there are {len(self.options)}")
        return self

    def option(self, letter: Letter) -> str | None:
        """The option `letter` names.

        Returns:
            The option, or None when the question has fewer.
        """
        at = LETTERS.index(letter)
        return self.options[at] if at < len(self.options) else None


class Card(BaseModel):
    """The input of a `status` call, an update of the agent's whole progress: each call replaces the one before."""

    model_config = ConfigDict(extra="forbid", frozen=True, defer_build=True)

    summary: Annotated[StrictStr, Field(max_length=MAX_SUMMARY), AfterValidator(_line)] = Field(
        description="Where the work stands, in one or two sentences, for someone who skipped the transcript.",
    )
    now: Line = Field(description="What you are doing this moment.")
    done: tuple[Done, ...] = Field(
        default=(),
        max_length=MAX_STEPS,
        description="The steps finished so far, in order, each with its proof.",
    )
    next: Annotated[tuple[Line, ...], BeforeValidator(_one_or_more)] = Field(
        default=(),
        max_length=MAX_STEPS,
        description="What is left, in order.",
    )
    stuck: Annotated[StrictStr, Field(max_length=MAX_SUMMARY), AfterValidator(_line)] | None = Field(
        default=None,
        description="What is in your way that you are working around, such as CI down or a flaky test; else omit it.",
    )
    steps: tuple[Step, ...] = Field(
        default=(),
        max_length=MAX_PLAN_STEPS,
        description="For a long job, every step in order, each with its status: the approved plan's when there is one.",
    )
    question: Question | None = Field(
        default=None,
        description="A decision you need from the operator and can work around meanwhile; keep it in each update until "
        "you have the answer or no longer need it, else omit it.",
    )


@dataclass(frozen=True)
class Standing:
    """A run's card as it stands, with how old it is."""

    #: The card; None when the run has recorded none.
    card: Card | None
    #: When it was recorded; None with no card.
    at: datetime | None
    #: The tool calls the agent ended since: since the run started, with no card.
    calls_since: int
    #: When each of the card's working steps was first seen working, by title.
    working_since: Mapping[str, datetime] = field(default_factory=dict)
    #: When the card's question was first asked; None with no question.
    asked_at: datetime | None = None
    #: The operator's answer to it, and when they gave it; None while it waits on them.
    answer: Letter | None = None
    answered_at: datetime | None = None


@dataclass(frozen=True)
class Answered:
    """The operator's answer to a running run's question, as recorded."""

    #: The question it answers, and when it was first asked.
    question: Question
    asked_at: datetime
    #: The letter, and the option it names.
    letter: Letter
    option: str
    #: Whether the question already had this answer, so nothing new was recorded.
    already: bool
    #: Whether it was written where the agent hears it on its next tool call: false once the agent has ended.
    heard: bool


def tool_name() -> str:
    """The name the agent, and the definitions' rules, know the tool by.

    Returns:
        `canopy_run_status`.
    """
    return servers.tool_name(SERVER, TOOL)


def read_call(called: Called) -> Card | None:
    """The card a tool call the agent made says, if it is a `status` call that completed and validates.

    Returns:
        The card, or None for any other call, a refused one, or one whose input is not a card.
    """
    if called.tool != tool_name() or not called.completed:
        return None
    try:
        return Card.model_validate(called.input)
    except ValidationError:
        return None


def record_call(conn: sqlite3.Connection, table: CardTable, run_id: int, card: Card | None) -> None:
    """Count one tool call the running run `run_id` of `table` ended, and record `card` as its card if given.

    Each of the card's working steps keeps the time it was first seen working on an earlier card, if it was working
    on the last; one newly working starts now. A question the last card asked too keeps when it was asked and its
    answer; any other starts now, with none. Nothing changes for a run not running.
    """
    running = sql.update(table).where("id = ? AND status = ?", run_id, _RUNNING[table])
    counted = running.set_to("tool_calls = tool_calls + 1")
    with db.transaction(conn):
        if card is not None:
            at = db.now()
            row = sql.execute(
                conn,
                sql.select("card_json, card_asked_at, card_working_since").from_(table).where("id = ?", run_id),
            ).fetchone()
            # Every assignment reads the row as it was, so the card's count is the calls made with this one.
            counted = counted.set(card_json=card.model_dump_json(), card_at=at).set_to("card_calls = tool_calls + 1")
            counted = counted.set(card_working_since=_working_since(row, card, at))
            if not _asks_still(row, card):
                asked = at if card.question is not None else None
                counted = counted.set(card_asked_at=asked, card_answer=None, card_answered_at=None)
        sql.execute(conn, counted)


def record_answer(conn: sqlite3.Connection, table: CardTable, run_id: int, letter: Letter, asked_at: datetime) -> bool:
    """Record `letter` as the operator's answer to the question the running run `run_id` of `table` asked at `asked_at`.

    Returns:
        Whether it was recorded: False once the run has ended, or its card asks no question asked then.
    """
    answered = (
        sql.update(table)
        .where("id = ? AND status = ? AND card_asked_at = ?", run_id, _RUNNING[table], db.format_time(asked_at))
        .set(card_answer=letter, card_answered_at=db.now())
    )
    with db.transaction(conn):
        return sql.execute(conn, answered).rowcount == 1


def answers_dir(state_dir: Path, run: str) -> Path:
    """The answers directory of the run CANOPY_RUN_ID names `run`, a worker's or a planner's id or a review's.

    Returns:
        `<state_dir>/runs/<id>.answers` or, for `review-<id>`, `<state_dir>/reviews/<id>.answers`: beside the run's
        own files, inside the state directory a sandbox denies, so a run reads its own and no other's (DESIGN §24).

    Raises:
        ValueError: `run` names no run that keeps a card.
    """
    if not RUN_ID_RE.fullmatch(run):
        raise ValueError(f"{run!r} names no run that keeps a card")
    review, _, run_id = run.rpartition("-")
    return state_dir / ("reviews" if review else "runs") / f"{int(run_id)}.answers"


def make_answers(path: Path) -> None:
    """Make a run's empty answers directory, the operator's alone to write, before its agent starts."""
    path.mkdir(mode=0o700, parents=True, exist_ok=True)


def remove_answers(path: Path) -> None:
    """Remove a run's answers directory, once its agent has ended; nothing when it is gone."""
    with contextlib.suppress(FileNotFoundError):
        shutil.rmtree(path)


def deliver(path: Path, answered: Answered) -> bool:
    """Write `answered` as the latest answer in the answers directory at `path`, for the running agent to read.

    The file is replaced whole, so a reader sees the answer before or after, never half of one: the question as it was
    asked, when, and the letter with the option it names.

    Returns:
        Whether it was written: False when the directory is gone, its run having ended.
    """
    data = {
        "asked": db.format_time(answered.asked_at),
        "ask": answered.question.ask,
        "letter": answered.letter,
        "option": answered.option,
    }
    # Its own name in each process and thread, so two writes at once never share the file one renames over the answer.
    staged = path / f".{ANSWER_FILE}.{os.getpid()}.{threading.get_ident()}"
    try:
        staged.write_text(json.dumps(data) + "\n", encoding="utf-8")
        staged.replace(path / ANSWER_FILE)
    except FileNotFoundError:
        return False
    finally:
        staged.unlink(missing_ok=True)
    return True


def of(row: sqlite3.Row | records.Row) -> Standing:
    """A run's card as its row records it, with how old it is.

    A card the journal holds that no longer reads as one, as after a change to its bounds, is shown as none.

    Returns:
        The card, when it was recorded, and the tool calls since.
    """
    values = records.columns(row)
    calls = int(values["tool_calls"] or 0)
    raw = values["card_json"]
    card = _parsed(str(raw)) if raw is not None else None
    if card is None or values["card_at"] is None:
        return Standing(None, None, calls)
    at = db.parse_time(str(values["card_at"]))
    since = _since(values["card_working_since"])
    calls_since = max(calls - int(values["card_calls"] or 0), 0)
    question = card.question
    asked = _time(values["card_asked_at"]) if question is not None else None
    if question is None or asked is None:
        return Standing(card, at, calls_since, since)
    answer = _letter(values["card_answer"], question)
    answered = _time(values["card_answered_at"]) if answer is not None else None
    return Standing(card, at, calls_since, since, asked, answer if answered is not None else None, answered)


def percent(card: Card) -> int | None:
    """How much of a card's steps is done: its `done` steps' share of those not skipped, rounded down.

    Returns:
        The percent, or None for a card with no steps, or whose every step is skipped.
    """
    counted = [s for s in card.steps if s.status != "skipped"]
    if not counted:
        return None
    return 100 * sum(s.status == "done" for s in counted) // len(counted)


def working_stage(card: Card) -> str | None:
    """The stage of a card's first working step.

    Returns:
        The stage, or None when no step is working or the first working one names none.
    """
    return next((s.stage for s in card.steps if s.status == "working"), None)


def stuck_at(standing: Standing, title: str, timeout_minutes: int) -> datetime | None:
    """When a working step is shown stuck: once it has been working longer than the run's last fifth.

    Returns:
        The time, or None for a step not working on the card.
    """
    since = standing.working_since.get(title)
    return since + timedelta(minutes=timeout_minutes / STUCK_SHARE) if since is not None else None


def is_stale(standing: Standing, started_at: str, now: datetime | None = None) -> bool:
    """Whether a running run's card has gone `STALE_CALLS` tool calls or `STALE_MINUTES` without an update.

    A run with no card counts from its start.

    Returns:
        True when it is stale.
    """
    since = standing.at or db.parse_time(started_at)
    late = (now or datetime.now(UTC)) - since >= timedelta(minutes=STALE_MINUTES)
    return late or standing.calls_since >= STALE_CALLS


def doing(standing: Standing, started_at: str, now: datetime | None = None) -> str | None:
    """A running run's progress on one line, for `canopy status`: what it does now, and when it last updated it.

    Returns:
        `now: <now>  updated 3m ago, 4 calls since`, or `no update for 18m and 4 calls` when that is stale;
        `no progress yet, 12m and 30 calls in` for a run with none once that is stale; else None.
    """
    if standing.card is None or standing.at is None:
        if not is_stale(standing, started_at, now):
            return None
        return f"no progress yet, {items.age(started_at, now)} and {_calls(standing.calls_since)} in"
    doing = f"now: {text.one_line(standing.card.now)}{_progress(standing.card)}"
    return f"{doing}  {_updated(standing, started_at, now)}"


def asking(standing: Standing, ref: str, now: datetime | None = None) -> str | None:
    """A running run's question on one line, for `canopy status`, while it waits on the operator's answer.

    Returns:
        `asks you, 3m: <question>  canopy reply run:41 A-C (recommends B)`; None with no question, or one answered.
    """
    question = standing.card.question if standing.card is not None else None
    if question is None or standing.asked_at is None or standing.answer is not None:
        return None
    age = items.age(db.format_time(standing.asked_at), now)
    letters = f"{LETTERS[0]}-{LETTERS[len(question.options) - 1]}"
    return (
        f"asks you, {age}: {text.one_line(question.ask)}  canopy reply {ref} {letters} "
        f"(recommends {question.recommend})"
    )


def lines(
    standing: Standing,
    *,
    started_at: str,
    running: bool,
    timeout_minutes: int,
    ref: str,
    now: datetime | None = None,
) -> list[str]:
    """A run's whole progress, for `canopy show`: its last update's age, each field on a line, its question, its steps.

    A step of a running run is marked stuck once it has worked longer than the last fifth of `timeout_minutes`. A
    question names its options by letter, the one the agent recommends, and the operator's answer, or how to give one
    while the run runs, by `ref`, the run's reference.

    Returns:
        The lines, indented; one saying there is none yet for a run with no progress.
    """
    card = standing.card
    if card is None or standing.at is None:
        return ["  no progress yet"]
    if running:
        head = f"  progress, {_updated(standing, started_at, now)}"
    else:
        at = db.format_time(standing.at)
        head = f"  last progress, updated {at}, {_calls(standing.calls_since)} before the run ended"
    found = [head, f"    {card.summary}", f"    now: {card.now}"]
    found.extend(f"    done: {d.step} ({d.proof})" for d in card.done)
    found.extend(f"    next: {step}" for step in card.next)
    if card.stuck is not None:
        found.append(f"    stuck: {card.stuck}")
    if card.question is not None:
        found.extend(_question(standing, card.question, running=running, ref=ref, now=now))
    if card.steps:
        found.append(f"    steps:{_progress(card)}")
    moment = now or datetime.now(UTC)
    for step in card.steps:
        stage = f" ({step.stage})" if step.stage is not None else ""
        due = stuck_at(standing, step.title, timeout_minutes) if running else None
        late = "  stuck" if due is not None and moment >= due else ""
        found.append(f"      {_MARKS[step.status]} {step.title}{stage}{late}")
    return found


#: How `canopy show` marks a step by its status.
_MARKS: Mapping[StepStatus, str] = {
    "not_started": "[ ]",
    "working": "[>]",
    "blocked": "[!]",
    "done": "[x]",
    "skipped": "[-]",
}


def _question(standing: Standing, question: Question, *, running: bool, ref: str, now: datetime | None) -> list[str]:
    """A card's question, for `canopy show`: how old it is, the question, each option by letter, and its answer.

    Returns:
        The lines, indented under the card's.
    """
    asked = f", {items.age(db.format_time(standing.asked_at), now)} old" if standing.asked_at is not None else ""
    found = [f"    question{asked}: {question.ask}"]
    for letter, option in zip(LETTERS, question.options, strict=False):
        recommended = "  (recommended)" if letter == question.recommend else ""
        found.append(f"      {letter}  {option}{recommended}")
    if standing.answer is not None and standing.answered_at is not None:
        found.append(f"      answered {standing.answer}, {db.format_time(standing.answered_at)}")
    elif running:
        found.append(f"      waiting on you: canopy reply {ref} LETTER")
    else:
        found.append("      run ended before an answer")
    return found


def _progress(card: Card) -> str:
    """How much of a card's steps is done, and the working one's stage, to follow a line; empty with no steps.

    Returns:
        `  40% done, stage tests`, or less as the card says less.
    """
    done = percent(card)
    if done is None:
        return ""
    stage = working_stage(card)
    return f"  {done}% done" + (f", stage {text.one_line(stage)}" if stage is not None else "")


def _working_since(row: sqlite3.Row | None, card: Card, at: str) -> str | None:
    """Each working step of `card`, by title, with when it was first seen working: on the run's last card, else `at`.

    Returns:
        The times as JSON, or None when no step is working.
    """
    before = {title: db.format_time(when) for title, when in _since(row[2] if row is not None else None).items()}
    working = {s.title: before.get(s.title, at) for s in card.steps if s.status == "working"}
    return json.dumps(working) if working else None


def _asks_still(row: sqlite3.Row | None, card: Card) -> bool:
    """Whether `card` asks the very question the run's last card asked, as recorded with when it was asked.

    Returns:
        True when both ask the same question; False when either asks none, or they differ.
    """
    if row is None or card.question is None or row[0] is None or row[1] is None:
        return False
    last = _parsed(str(row[0]))
    return last is not None and last.question == card.question


def _time(raw: object) -> datetime | None:
    """A time a row holds, or None where it holds none, or none that reads as one.

    Returns:
        The time.
    """
    if not isinstance(raw, str):
        return None
    try:
        return db.parse_time(raw)
    except ValueError:
        return None


def _letter(raw: object, question: Question) -> Letter | None:
    """An answer a row holds, as one of `question`'s letters.

    Returns:
        The letter, or None where the row holds none, or one that names none of the question's options.
    """
    return next((letter for letter in LETTERS if raw == letter and question.option(letter) is not None), None)


def _since(raw: object) -> dict[str, datetime]:
    """The times a row's `card_working_since` holds, by step title.

    Returns:
        The times; none where it holds none, and none of those that do not read as one.
    """
    if not isinstance(raw, str):
        return {}
    try:
        found = json.loads(raw)
    except ValueError:
        return {}
    if not isinstance(found, dict):
        return {}
    times: dict[str, datetime] = {}
    for title, when in found.items():
        if isinstance(title, str) and isinstance(when, str):
            try:
                times[title] = db.parse_time(when)
            except ValueError:
                continue
    return times


def _updated(standing: Standing, started_at: str, now: datetime | None) -> str:
    """When a running run last updated its progress, said plainly when that is stale.

    Returns:
        `updated 3m ago, 4 calls since`; once stale, `no update for 18m and 4 calls` by time, else
        `no update in 26 tool calls`.
    """
    at = standing.at or db.parse_time(started_at)
    age = items.age(db.format_time(at), now)
    if (now or datetime.now(UTC)) - at >= timedelta(minutes=STALE_MINUTES):
        return f"no update for {age} and {_calls(standing.calls_since)}"
    if standing.calls_since >= STALE_CALLS:
        return f"no update in {standing.calls_since} tool calls"
    return f"updated {age} ago, {_calls(standing.calls_since)} since"


def _calls(count: int) -> str:
    return "1 call" if count == 1 else f"{count} calls"


def _parsed(raw: str) -> Card | None:
    try:
        return Card.model_validate_json(raw)
    except ValidationError:
        return None
