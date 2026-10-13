"""The loop's pause (DESIGN §6), `canopy pause` and `canopy resume`, and asking it to read its config again.

The loop reads both at every step of its wait.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from fastapi import APIRouter

from canopy.core import config, conversation, pause
from canopy.infra import logs
from canopy.serve import views
from canopy.serve.api.refs import REFUSED, WEB, refusal
from canopy.serve.schema import ConfigReload, LoopState, PauseChanged

if TYPE_CHECKING:
    from canopy.serve.backend import Backend


def router(backend: Backend) -> APIRouter:
    """Return the loop's routes, reading and writing through `backend`."""
    api = APIRouter()
    log = logs.for_tick(None)

    @api.get("/loop", operation_id="getLoop")
    def loop() -> LoopState:
        with backend.open() as ctx:
            return views.loop_state(ctx)

    @api.post("/loop/pause", operation_id="pauseLoop")
    def pause_loop() -> PauseChanged:
        with backend.open() as ctx:
            already = pause.pause(ctx.conn, channel=WEB)
            state = views.loop_state(ctx)
        if not already:
            log.info("loop paused", extra={"channel": WEB})
        return PauseChanged(already=already, loop=state)

    @api.post("/loop/resume", operation_id="resumeLoop")
    def resume_loop() -> PauseChanged:
        with backend.open() as ctx:
            already = pause.resume(ctx.conn)
            state = views.loop_state(ctx)
        if not already:
            log.info("loop resumed", extra={"channel": WEB})
        return PauseChanged(already=already, loop=state)

    @api.post("/loop/reload", operation_id="reloadConfig", responses=REFUSED)
    def reload_config() -> ConfigReload:
        with backend.open() as ctx:
            try:
                found = backend.reload(ctx)
            except config.ConfigError as e:
                raise refusal(conversation.Refused("config_invalid", str(e))) from None
        log.info("config reload asked for", extra={"channel": WEB, "changed": list(found.changed)})
        return ConfigReload(changed=list(found.changed), restart=list(found.restart), after_tick=found.after_tick)

    return api
