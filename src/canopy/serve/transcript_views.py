"""An agent's session and its output as the API sends them (DESIGN §22): a transcript, and the raw output's tail.

Runs, chore runs, reviews, and ticks all show theirs through these. The text is an agent's, read back from the file it
was printed to: the transcript as its entries, the raw output without control characters, and the UI renders it as
text.
"""

from __future__ import annotations

import os
from types import MappingProxyType
from typing import TYPE_CHECKING

from canopy.core import gc_passes
from canopy.runtime import entries, transcript
from canopy.serve.schema.transcript import (
    RawOutput,
    Transcript,
    TranscriptEntry,
    TranscriptError,
    TranscriptPrompt,
    TranscriptStep,
    TranscriptText,
    TranscriptTokens,
    TranscriptTool,
)

if TYPE_CHECKING:
    import sqlite3
    from collections.abc import Mapping
    from pathlib import Path

#: No reply's model: a run one model served, or one whose replies canopy has not read.
_NO_MODELS: Mapping[str, str] = MappingProxyType({})


def session_transcript(
    path: Path,
    session: object,
    removed_after_days: int | None = None,
    models: Mapping[str, str] = _NO_MODELS,
) -> Transcript:
    """The events of the session the journal recorded, read back from the file they were printed to (DESIGN §22).

    `removed_after_days` is how long retention kept the file and its prompt, when it removed them (`removed_after`).
    `models` is the model of each reply of a run more than one model served, by its message (`run_models.replies_of`),
    which names the model of each model call.

    Returns:
        The entries read, with status `no_session` when the journal recorded no session, or `no_log` when the file is
        missing or not a regular file; and the prompt kept beside the file, whatever the status.
    """
    kept = transcript.prompt(transcript.prompt_path(path))
    prompt = TranscriptPrompt(text=kept.text, truncated=kept.truncated) if kept is not None else None
    if not isinstance(session, str) or not session:
        return Transcript(status="no_session", prompt=prompt, removed_after_days=removed_after_days)
    found = transcript.read(path, session)
    if found is None:
        return Transcript(status="no_log", session_id=session, prompt=prompt, removed_after_days=removed_after_days)
    return Transcript(
        status="read",
        session_id=session,
        entries=[transcript_entry(e, models) for e in found.entries],
        truncated=found.truncated,
        unreadable=found.unreadable,
        prompt=prompt,
    )


def transcript_entry(entry: entries.Entry, models: Mapping[str, str] = _NO_MODELS) -> TranscriptEntry:
    """One entry of a transcript as the API sends it, a model call's naming its model when `models` has its reply.

    Returns:
        The model for the entry's kind: text, a tool call, a step, or an error.
    """
    match entry:
        case entries.Text():
            return TranscriptText(
                at=entry.at,
                text=entry.text,
                reasoning=entry.reasoning,
                cut=entry.cut,
                call=entry.call,
            )
        case entries.ToolCall():
            return TranscriptTool(
                at=entry.at,
                tool=entry.tool,
                status=entry.status,
                title=entry.title,
                input=entry.input,
                output=entry.output,
                duration_ms=entry.duration_ms,
                cut=entry.cut,
                call=entry.call,
            )
        case entries.Step():
            t = entry.tokens
            return TranscriptStep(
                at=entry.at,
                reason=entry.reason,
                cost_usd=entry.cost_usd,
                tokens=t.total if t is not None else None,
                split=TranscriptTokens(**vars(t)) if t is not None else None,
                call=entry.call,
                model=models.get(entry.message) if entry.message is not None else None,
            )
        case entries.Error():
            return TranscriptError(at=entry.at, name=entry.name, message=entry.message, call=entry.call)


def raw_output(path: Path, removed_after_days: int | None = None) -> RawOutput:
    """The end of a log or output file as written (DESIGN §22).

    `removed_after_days` is how long retention kept the file, when it removed it (`removed_after`).

    Returns:
        The tail, without control characters, or a `no_output` status when the file is missing or not a regular file.
    """
    found = transcript.tail(path)
    if found is None:
        return RawOutput(status="no_output", removed_after_days=removed_after_days)
    return RawOutput(status="read", text=found.text, size=found.size, truncated=found.truncated)


def removed_after(conn: sqlite3.Connection, path: Path, ended_at: str | None, rule: gc_passes.Rule) -> int | None:
    """How many days retention kept the file at `path`, of a row that ended at `ended_at`, if a pass removed it.

    Returns:
        The days `rule` kept it, or None when the file is there, or no pass has reached the row's end (DESIGN §26).
    """
    if os.path.lexists(path):
        return None
    return gc_passes.removed_after(conn, ended_at, rule)
