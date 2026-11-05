"""Dictation through the web UI (DESIGN §22, TRUST_MODEL T8): a recording made text by the operator's own command.

canopy checks the recording is the WAV the page sends, runs `serve.dictation_cmd` on it with the words it expects to
hear, and gives back what the command printed, keeping nothing.
"""

import dataclasses
import io
import wave
from pathlib import Path
from unittest import mock

import pytest

from canopy.core import db, records
from canopy.core.context import Context
from canopy.loop import reread, tick_now, web
from canopy.serve import dictation, guard
from tests.canopy.web_helpers import refused, signed_in_client, signed_in_to
from tests.conftest import executable

SPOKEN = "  Ship the importer\n by tenant, PROJ-7 first.\n"


def recording(seconds: float = 1.0, *, channels: int = 1, rate: int = dictation.SAMPLE_RATE) -> bytes:
    """A silent WAV of `seconds`, 16-bit PCM, as the page records it unless told otherwise."""
    out = io.BytesIO()
    with wave.open(out, "wb") as w:
        w.setnchannels(channels)
        w.setsampwidth(2)
        w.setframerate(rate)
        w.writeframes(b"\0\0" * channels * int(seconds * rate))
    return out.getvalue()


def stt(tmp_path: Path, body: str = f"printf '{SPOKEN}'") -> Path:
    """A speech-to-text command that records its arguments and a copy of what it heard beside it, then runs `body`."""
    return executable(
        tmp_path / "stt",
        f'#!/bin/sh\nprintf "%s\\n" "$@" > "{tmp_path}/args"\ncp "$2" "{tmp_path}/heard.wav"\n{body}\n',
    )


def dictating(ctx: Context, template: str) -> Context:
    """`ctx`, its config's `serve.dictation_cmd` set to `template`."""
    serve = ctx.config.serve.model_copy(update={"dictation_cmd": template})
    return dataclasses.replace(ctx, config=ctx.config.model_copy(update={"serve": serve}))


def test_a_recording_is_made_text_by_the_operator_s_command(ctx: Context, tmp_path: Path) -> None:
    db.set_ticket(ctx.conn, "PROJ-7", ctx.repo, title="Shard the importer")
    c, headers = signed_in_client(dictating(ctx, f"{stt(tmp_path)} -f {{audio}} --prompt {{vocabulary}}"))
    assert c.get("/api/meta").json()["dictation"] is True
    sent = recording(2.5)
    answered = c.post("/api/dictation", content=sent, headers={**headers, "content-type": "audio/wav"})
    assert answered.status_code == 200, answered.text
    assert answered.json() == {"text": "Ship the importer by tenant, PROJ-7 first.", "seconds": 2.5}
    flag, audio, prompt, vocabulary = (tmp_path / "args").read_text().splitlines()
    assert (flag, prompt, vocabulary) == ("-f", "--prompt", "repo. PROJ-7 Shard the importer")
    assert (tmp_path / "heard.wav").read_bytes() == sent
    assert not Path(audio).exists(), "the recording is deleted once the command ends"


def test_without_a_command_no_field_offers_dictation(ctx: Context) -> None:
    c, headers = signed_in_client(ctx)
    assert c.get("/api/meta").json()["dictation"] is False
    off = refused(c.post("/api/dictation", content=recording(), headers=headers))
    assert off == "off: no dictation command is set: serve.dictation_cmd in your private config"


@pytest.mark.parametrize(
    ("sent", "reason"),
    [
        (b"RIFF....WAVEfmt ", "not a PCM WAV recording"),
        (recording(channels=2), "must be 16-bit mono PCM at 16000 Hz"),
        (recording(rate=44_100), "must be 16-bit mono PCM at 16000 Hz"),
        (recording(0), "the recording is empty"),
        (recording(3), "the recording is 3 seconds; at most 2"),
    ],
)
def test_a_body_that_is_not_the_page_s_recording_is_refused_before_the_command_runs(
    ctx: Context,
    tmp_path: Path,
    sent: bytes,
    reason: str,
) -> None:
    c, headers = signed_in_client(dictating(ctx, f"{stt(tmp_path)} -f {{audio}}"))
    with mock.patch.object(dictation, "MAX_SECONDS", 2):
        assert refused(c.post("/api/dictation", content=sent, headers=headers)).startswith(f"bad_audio: {reason}")
    assert not (tmp_path / "args").exists()


def test_a_recording_may_be_larger_than_any_other_body_within_its_own_bound(ctx: Context, tmp_path: Path) -> None:
    c, headers = signed_in_client(dictating(ctx, f"{stt(tmp_path)} -f {{audio}}"))
    minute = recording(60)
    assert len(minute) > guard.MAX_BODY_BYTES
    assert c.post("/api/dictation", content=minute, headers=headers).json()["seconds"] == 60
    assert c.post("/api/tasks", content=minute, headers=headers).status_code == 413
    past = b"\0" * (dictation.MAX_AUDIO_BYTES + 1)
    assert c.post("/api/dictation", content=past, headers=headers).status_code == 413


def test_a_command_that_fails_is_refused_with_what_it_said(ctx: Context, tmp_path: Path) -> None:
    command = stt(tmp_path, "echo 'error: model file not found' >&2; exit 3")
    c, headers = signed_in_client(dictating(ctx, f"{command} -f {{audio}}"))
    said = refused(c.post("/api/dictation", content=recording(), headers=headers))
    assert said == f"failed: {command} exited 3: error: model file not found"
    c, headers = signed_in_client(dictating(ctx, "no-such-stt -f {audio}"))
    missing = refused(c.post("/api/dictation", content=recording(), headers=headers))
    assert missing == "failed: no-such-stt is not on the loop's PATH"


def test_a_command_that_runs_too_long_is_killed(ctx: Context, tmp_path: Path) -> None:
    c, headers = signed_in_client(dictating(ctx, f"{stt(tmp_path, 'sleep 30')} -f {{audio}}"))
    with mock.patch.object(dictation, "TIMEOUT_SECONDS", 0.5):
        slow = refused(c.post("/api/dictation", content=recording(), headers=headers))
    assert slow.startswith("timed_out: ")


def test_a_second_recording_is_refused_while_one_is_transcribed(ctx: Context, tmp_path: Path) -> None:
    backend = web.backend(dictating(ctx, f"{stt(tmp_path)} -f {{audio}}"), reread.Reload(), tick_now.TickNow())
    c, headers = signed_in_to(backend)
    with backend.dictating:
        busy = refused(c.post("/api/dictation", content=recording(), headers=headers))
    assert busy == "busy: another recording is being transcribed"
    assert c.post("/api/dictation", content=recording(), headers=headers).status_code == 200


def test_the_vocabulary_names_the_repositories_and_the_tickets_at_work_most_recent_first(ctx: Context) -> None:
    db.set_ticket(ctx.conn, "PROJ-1", ctx.repo, title="Older work")
    db.set_ticket(ctx.conn, "PROJ-2", ctx.repo, title="-rf the cache")
    db.set_ticket(ctx.conn, "PROJ-3", ctx.repo, title="Shipped", done=True)
    records.update(records.Ticket).set(changed_at="2026-01-01T00:00:00Z").where("key = ?", "PROJ-1").run(ctx.conn)
    assert dictation.vocabulary(ctx.conn, ["api", "web"]) == "api, web. PROJ-2 -rf the cache. PROJ-1 Older work"
    assert dictation.vocabulary(ctx.conn, []) == "PROJ-2 -rf the cache. PROJ-1 Older work"
    db.set_ticket(ctx.conn, "PROJ-4", ctx.repo, title="word " * 200)
    bounded = dictation.vocabulary(ctx.conn, ["api"])
    assert len(bounded) <= dictation.MAX_VOCABULARY
    assert bounded.endswith("word")


@pytest.mark.parametrize("key", ["-x", "- -x", "-- - -rf"])
def test_the_vocabulary_never_starts_with_a_hyphen_whatever_leads_it(ctx: Context, key: str) -> None:
    db.set_ticket(ctx.conn, key, ctx.repo, title="Odd key")
    words = dictation.vocabulary(ctx.conn, [])
    assert not words.startswith(("-", " ")), words
    assert words.endswith("Odd key")
