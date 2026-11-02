"""The loop's tables: its ticks and what each one ran, decided, and asked for.

Each tick, its overseer's runs, the decisions it recorded, the runs it was asked for, what it derived in shadow,
and garbage collection's passes (DESIGN §6, §26, §30, §40).
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import ClassVar, LiteralString

from canopy.core.orm import Row

# Imported for real, not under TYPE_CHECKING: `typing.get_type_hints` resolves a row type's fields when it is
# read.
from canopy.core.vocab import (
    Decider,
    GcPassStatus,
    OverseerRunStatus,
    Phase,
    RecordedKind,
    RecordedStatus,
    RunKind,
    TickStatus,
)


@dataclass(frozen=True)
class Tick(Row):
    """A tick (DESIGN §6): how it ended, what its overseer cost, what it read, and what the loop knew when it ran it."""

    TABLE: ClassVar[LiteralString] = "ticks"

    id: int
    started_at: str
    ended_at: str | None
    dry_run: bool
    status: TickStatus
    summary: str | None
    session_id: str | None
    cost_usd: float | None
    tokens_input: int | None
    tokens_output: int | None
    tokens_reasoning: int | None
    tokens_cache_read: int | None
    tokens_cache_write: int | None
    # The newest message, and the time, the tick had read up to; None before it read the journal.
    message_id: int | None
    read_at: str | None
    # Set by `canopy loop` alone (`db.set_tick_loop`): whether the tick was idle, and what started it.
    idle: bool | None
    woken_by: str | None
    tokens_peak_context: int | None
    # Whether the tick's state block told the overseer to run the tracker query; None on a tick from before that was
    # recorded, each of which was told to.
    query_due: bool | None
    tokens_first_call: int | None
    tokens_first_cache_write: int | None
    definitions_digest: str | None
    # The version of canopy that ran the tick; None on a tick from before that was recorded.
    canopy_version: str | None
    #: Whether it ran its overseer: False when halted or when nothing was left to it (DESIGN §39); None on a tick from
    #: before that was recorded, or one that ended before it got that far.
    overseer_ran: bool | None
    #: What its first model call read from the cache; None where `tokens_first_call` is, and on a run from before
    #: canopy kept it.
    tokens_first_cache_read: int | None
    #: The model canopy chose for its overseer, from `runtime.models` (DESIGN §13), as it asked the runtime for it;
    #: None when it chose none, when the overseer did not run, and on a tick from before canopy recorded it.
    model: str | None
    #: Its overseer's latest tool call: the tool, what it did on one line, and when canopy read it (DESIGN §8); None
    #: before the first, for a template that prints no events, and on a tick from before canopy kept it.
    activity_tool: str | None
    activity: str | None
    activity_at: str | None


@dataclass(frozen=True)
class OverseerRun(Row):
    """A tick's run of the overseer (DESIGN §40): the subject it was given, how it ended, its session, and its cost."""

    TABLE: ClassVar[LiteralString] = "overseer_runs"

    id: int
    tick_id: int
    #: The subject it was given; None for the whole state block, as every run is until a tick runs one per subject.
    subject: str | None
    started_at: str
    ended_at: str | None
    status: OverseerRunStatus
    #: Why it failed, or the duties it left undone; None for one running, `ok`, or abandoned while it ran.
    failure: str | None
    session_id: str | None
    #: The model canopy asked the runtime for (DESIGN §13), as `ticks.model`; what served it is `run_models`' under
    #: its tick.
    model: str | None
    cost_usd: float | None
    tokens_input: int | None
    tokens_output: int | None
    tokens_reasoning: int | None
    tokens_cache_read: int | None
    tokens_cache_write: int | None
    tokens_peak_context: int | None
    tokens_first_call: int | None
    tokens_first_cache_write: int | None
    tokens_first_cache_read: int | None


@dataclass(frozen=True)
class Decision(Row):
    """A decision a tick recorded (DESIGN §6): the overseer's, a guard's refusal, or the harness's own (§37)."""

    TABLE: ClassVar[LiteralString] = "decisions"

    id: int
    tick_id: int
    ticket_key: str | None
    action: str
    rationale: str
    created_at: str
    repo: str | None
    chore: str | None
    pr: str | None
    #: Who made it; None on a decision recorded before the journal said (TRUST_MODEL T5).
    decider: Decider | None
    #: Whether it is an attention item the overseer keeps, recorded once and held until what it names ends it (§37).
    kept: bool
    #: The journal number (§35) of what a kept item names; None for one about its ticket alone, and any other decision.
    item: int | None
    #: The kind of run a refused dispatch asked for; None on any other decision, and on a refusal recorded before 0118.
    kind: RunKind | None


@dataclass(frozen=True)
class RecordedRun(Row):
    """A run the overseer asked for, recorded at the ask and spawned by the tick after its run (DESIGN §40)."""

    TABLE: ClassVar[LiteralString] = "recorded_runs"

    id: int
    tick_id: int
    kind: RecordedKind
    #: The verb's request as the overseer made it, JSON, which the spawn makes again.
    request: str
    #: What it holds while it waits: its ticket, a review's PR and persona, a chore's name.
    ticket_key: str | None
    pr_url: str | None
    persona: str | None
    chore: str | None
    status: RecordedStatus
    #: The run it started as, in its kind's table; None until it starts.
    run_id: int | None
    recorded_at: str
    closed_at: str | None


@dataclass(frozen=True)
class Derivation(Row):
    """One subject a tick derived in code, in shadow (DESIGN §30): a ticket's own phases, or a unit's."""

    TABLE: ClassVar[LiteralString] = "derivations"

    id: int
    tick_id: int
    ticket_key: str
    #: The unit's repository; None on the ticket's own row.
    repo: str | None
    #: Whether the ticket is a candidate (DESIGN §17); None on a unit's row and a stale one.
    candidate: bool | None
    #: Whether the tracker said the ticket is closed; None on a unit's row and a stale one.
    closed: bool | None
    #: Every phase of §7's table that held, as a JSON list; empty when none did, or the subject is stale.
    phases: str
    #: The stale or missing observation the subject depends on; None when it was derived.
    stale: str | None
    #: The phase the journal held for the subject when the tick closed: the overseer's.
    overseer_phase: Phase | None


@dataclass(frozen=True)
class GcPass(Row):
    """One pass of garbage collection (DESIGN §26): the retention it ran with, and what it removed."""

    TABLE: ClassVar[LiteralString] = "gc_passes"

    id: int
    #: The tick it ran in; None for a pass run by hand.
    tick_id: int | None
    started_at: str
    ended_at: str
    status: GcPassStatus
    run_files_days: int
    tick_files_days: int
    #: The end before which a run's files went, and an `ok` tick's; None when that kind is kept forever.
    run_cutoff: str | None
    tick_cutoff: str | None
    #: The files and the journal's rows it removed, and their bytes, by the kind `canopy gc --dry-run` names, as a JSON
    #: object of `{"files", "bytes"}` or `{"rows", "bytes"}`.
    removed: str
    #: The files it found past retention but could not remove.
    failures: int
    #: What it raised; None for an `ok` pass.
    error: str | None
