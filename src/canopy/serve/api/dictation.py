"""Dictation (DESIGN §22): a recording of the operator, made text by `serve.dictation_cmd` (TRUST_MODEL T8).

The body is the recording's bytes, a 16 kHz mono 16-bit PCM WAV, which the guard bounds above `MAX_SECONDS` of it
(guard.py). It writes nothing to the journal: the text goes back to the page alone, which puts it in the field the
operator recorded into, for them to read before they send anything. One recording is transcribed at a time.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from fastapi import APIRouter, Request
from starlette.concurrency import run_in_threadpool

from canopy.core import conversation
from canopy.infra import logs
from canopy.serve import dictation
from canopy.serve.api.deps import BackendDep
from canopy.serve.api.refs import REFUSED, RefusedError
from canopy.serve.guard import DICTATION_PATH
from canopy.serve.schema.dictation import Dictated

if TYPE_CHECKING:
    from canopy.serve.backend import Backend

TAG = "dictation"
router = APIRouter(tags=[TAG])
_log = logs.for_tick(None)

# The body is the recording's bytes, not JSON, which would grow it by a third.
_BODY: dict[str, Any] = {
    "requestBody": {
        "required": True,
        "description": f"The recording: a WAV of 16-bit mono PCM at {dictation.SAMPLE_RATE} Hz, at most "
        f"{dictation.MAX_SECONDS} seconds.",
        "content": {"audio/wav": {"schema": {"type": "string", "format": "binary"}}},
    },
}


@router.post(
    DICTATION_PATH,
    operation_id="dictate",
    summary="Transcribe a recording",
    responses=REFUSED,
    openapi_extra=_BODY,
)
async def dictate(request: Request, backend: BackendDep) -> Dictated:
    """Run `serve.dictation_cmd` on the recording, and return the text it printed. Nothing is sent or kept.

    Refused `off` with no command set, `bad_audio` for a body that is not the WAV above, `busy` while another
    recording is being transcribed, `failed` for a command that is missing or exits other than 0, and `timed_out` for
    one that runs past its timeout.
    """
    return await run_in_threadpool(_dictate, backend, await request.body())


def _dictate(backend: Backend, audio: bytes) -> Dictated:
    """Transcribe `audio` with the config the loop runs on now, unless another recording is being transcribed.

    Returns:
        What the command heard.

    Raises:
        RefusedError: a guard refused it, or the command failed.
    """
    if not backend.dictating.acquire(blocking=False):
        raise RefusedError(conversation.Refused("busy", "another recording is being transcribed")) from None
    try:
        with backend.open() as ctx:
            vocabulary = dictation.vocabulary(ctx.conn, (r.name for r in ctx.ws.repos))
            template = ctx.config.serve.dictation_cmd
            runner = ctx.runner
        found = dictation.transcribe(runner, template, audio, vocabulary)
    except conversation.Refused as r:
        # The guard alone: a failure's reason quotes the command's stderr, where a speech tool may echo what it heard.
        _log.warning("dictation refused", extra={"guard": r.guard})
        raise RefusedError(r) from None
    finally:
        backend.dictating.release()
    # Never the text: it is the operator's words, which the journal and the log keep only once they are sent.
    _log.info("operator dictated", extra={"seconds": round(found.seconds, 1), "characters": len(found.text)})
    return Dictated(text=found.text, seconds=found.seconds)
