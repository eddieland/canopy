"""Dictation for the web UI's fields (DESIGN §22): the operator's recording, made text by their own command.

The page records the operator, makes the recording a 16 kHz mono WAV, and sends it here. canopy checks it is exactly
that, at most `MAX_SECONDS` long, writes it to an operator-only temporary directory, and runs `serve.dictation_cmd`
on it through the process seam, with a timeout, one recording at a time. What the command prints is the text, its
control characters dropped and its whitespace collapsed, which the page puts in the field for the operator to read
before they send it: nothing canopy hears is sent, recorded, or kept, and the recording is deleted once the command
ends (TRUST_MODEL T8).

A speech model hears names it was never taught as words it knows, so the command may take `{vocabulary}`: the
workspace's repositories, then the keys and titles of the tickets canopy is working on, most recently changed first,
bounded to what a model such as Whisper reads as its prompt.
"""

from __future__ import annotations

import io
import tempfile
import wave
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING

from canopy.core import config, conversation, records
from canopy.infra import procs, text

if TYPE_CHECKING:
    import sqlite3
    from collections.abc import Iterable

#: The sample rate the page records at, which speech models take without resampling.
SAMPLE_RATE = 16_000
#: The longest recording canopy transcribes, in seconds: a long message, and a bounded body.
MAX_SECONDS = 300
#: The largest body the dictation route takes: `MAX_SECONDS` of 16-bit mono samples, and room for the WAV's header.
MAX_AUDIO_BYTES = MAX_SECONDS * SAMPLE_RATE * 2 + 4096
#: Seconds the command may take before it is killed: a large model on a CPU reads a long recording in less.
TIMEOUT_SECONDS = 180
#: The most text a transcription gives the field: far more than `MAX_SECONDS` of speech holds.
MAX_TEXT = 20_000
#: The longest `{vocabulary}`: Whisper reads at most 224 tokens of its prompt, and a word is a token or two.
MAX_VOCABULARY = 600
#: How many tickets' keys and titles the vocabulary names, before its bound cuts it.
VOCABULARY_TICKETS = 30
#: How much of the command's stderr a failure quotes.
_STDERR_CHARS = 300


@dataclass(frozen=True)
class Dictation:
    """What a recording came to: its text, and how long it was."""

    #: What the command heard, as one paragraph; empty when it heard nothing.
    text: str
    #: The recording's length, in seconds.
    seconds: float


def transcribe(runner: procs.Runner, template: str, audio: bytes, vocabulary: str) -> Dictation:
    """Check `audio`, then run the dictation command `template` on it with `vocabulary`, and return what it printed.

    Returns:
        The text and the recording's length.

    Raises:
        Refused: `off` with no command; `bad_audio` for a body that is not a 16 kHz mono 16-bit PCM WAV of at most
            `MAX_SECONDS`; `failed` for a command that is missing, cannot start, or exits other than 0; `timed_out`
            for one that ran past `TIMEOUT_SECONDS`.
    """
    if not template:
        raise conversation.Refused("off", "no dictation command is set: serve.dictation_cmd in your private config")
    seconds = _checked(audio)
    with tempfile.TemporaryDirectory(prefix="canopy-dictation-") as held:
        path = Path(held) / "recording.wav"
        path.write_bytes(audio)
        argv = config.render_dictation(template, path, vocabulary)
        try:
            result = runner.run(argv, cwd=Path(held), timeout=TIMEOUT_SECONDS)
        except procs.CommandNotFoundError:
            raise conversation.Refused("failed", f"{argv[0]} is not on the loop's PATH") from None
        except procs.ProcError as e:
            raise conversation.Refused("failed", f"{argv[0]} did not start: {e}") from None
    if result.timed_out:
        raise conversation.Refused("timed_out", f"{argv[0]} took longer than {TIMEOUT_SECONDS} seconds")
    if not result.ok:
        said = text.one_line(result.stderr[-_STDERR_CHARS:]) or "and printed nothing on stderr"
        raise conversation.Refused("failed", f"{argv[0]} exited {result.returncode}: {said}")
    return Dictation(text=_flat(result.stdout)[:MAX_TEXT], seconds=seconds)


def vocabulary(conn: sqlite3.Connection, repos: Iterable[str]) -> str:
    """The words canopy expects to hear: the repositories, then the keys and titles of tickets not done.

    Returns:
        The words as one line of at most `MAX_VOCABULARY` characters, cut at a word, never starting with `-`, so even
        as a word of its own it is never read as an option.
    """
    tickets = (
        records.select(records.Ticket)
        .where("done = 0 AND forgotten_at IS NULL")
        .order_by("changed_at DESC, key")
        .limit(VOCABULARY_TICKETS)
        .all(conn)
    )
    pieces = [", ".join(repos), *(f"{t.key} {t.title}" if t.title else t.key for t in tickets)]
    words = _flat(". ".join(p for p in pieces if p)).lstrip("-").strip()
    if len(words) <= MAX_VOCABULARY:
        return words
    return words[:MAX_VOCABULARY].rsplit(" ", 1)[0]


def _checked(audio: bytes) -> float:
    """Check that `audio` is the WAV the page sends.

    Returns:
        Its length, in seconds.

    Raises:
        Refused: `bad_audio`, saying what is wrong with it.
    """
    try:
        with wave.open(io.BytesIO(audio)) as found:
            shape = (found.getnchannels(), found.getsampwidth(), found.getframerate(), found.getcomptype())
            frames = found.getnframes()
    except (wave.Error, EOFError) as e:
        raise conversation.Refused("bad_audio", f"not a PCM WAV recording: {e}") from None
    if shape != (1, 2, SAMPLE_RATE, "NONE"):
        raise conversation.Refused("bad_audio", f"must be 16-bit mono PCM at {SAMPLE_RATE} Hz")
    seconds = frames / SAMPLE_RATE
    if frames == 0:
        raise conversation.Refused("bad_audio", "the recording is empty")
    if seconds > MAX_SECONDS:
        raise conversation.Refused("bad_audio", f"the recording is {seconds:.0f} seconds; at most {MAX_SECONDS}")
    return seconds


def _flat(said: str) -> str:
    # One paragraph: a model prints a line per segment it heard, which are a sentence's pieces, not its paragraphs.
    return " ".join("".join(c if c.isprintable() else " " for c in said).split())
