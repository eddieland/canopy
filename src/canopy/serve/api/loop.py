"""The loop's pause (DESIGN §6), `canopy pause` and `canopy resume`, and asking it to read its config again.

The loop reads both at every step of its wait.
"""

from __future__ import annotations

from fastapi import APIRouter

from canopy.core import config, conversation, pause
from canopy.infra import logs
from canopy.serve import views
from canopy.serve.api.deps import BackendDep
from canopy.serve.api.refs import REFUSED, WEB, RefusedError
from canopy.serve.schema import ConfigReload, LoopState, PauseChanged

TAG = "loop"
router = APIRouter(tags=[TAG])
_log = logs.for_tick(None)


@router.get("/loop", operation_id="getLoop", summary="Get the loop's state")
def loop(backend: BackendDep) -> LoopState:
    """Whether the loop is paused: since when, and through which channel, or not."""
    with backend.open() as ctx:
        return views.loop_state(ctx)


@router.post("/loop/pause", operation_id="pauseLoop", summary="Pause the loop")
def pause_loop(backend: BackendDep) -> PauseChanged:
    """`canopy pause`: no tick starts until the operator resumes the loop. A tick running now finishes."""
    with backend.open() as ctx:
        already = pause.pause(ctx.conn, channel=WEB)
        state = views.loop_state(ctx)
    if not already:
        _log.info("loop paused", extra={"channel": WEB})
    return PauseChanged(already=already, loop=state)


@router.post("/loop/resume", operation_id="resumeLoop", summary="Resume the loop")
def resume_loop(backend: BackendDep) -> PauseChanged:
    """`canopy resume`: ticks start again."""
    with backend.open() as ctx:
        already = pause.resume(ctx.conn)
        state = views.loop_state(ctx)
    if not already:
        _log.info("loop resumed", extra={"channel": WEB})
    return PauseChanged(already=already, loop=state)


@router.post("/loop/reload", operation_id="reloadConfig", summary="Reload the config", responses=REFUSED)
def reload_config(backend: BackendDep) -> ConfigReload:
    """Ask the loop to read its config again, as SIGHUP does. It writes nothing.

    A config that does not validate is refused `config_invalid`, and the loop keeps the one it runs on.
    """
    with backend.open() as ctx:
        try:
            found = backend.reload(ctx)
        except config.ConfigError as e:
            raise RefusedError(conversation.Refused("config_invalid", str(e))) from None
    _log.info("config reload asked for", extra={"channel": WEB, "changed": list(found.changed)})
    return ConfigReload(changed=list(found.changed), restart=list(found.restart), after_tick=found.after_tick)
