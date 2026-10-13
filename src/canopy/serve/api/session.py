"""Signing in and out with the listener secret (auth.py). The only routes that need no session."""

from __future__ import annotations

import asyncio
from typing import TYPE_CHECKING

from fastapi import APIRouter, HTTPException, Request, Response

from canopy.infra import logs
from canopy.serve.auth import FAILED_SIGN_IN_SECONDS, OPEN_TOKEN, SESSION_SECONDS
from canopy.serve.schema import Session, SignIn

if TYPE_CHECKING:
    from canopy.serve.auth import Sessions


def router(sessions: Sessions) -> APIRouter:
    """Return the session's routes, signing in with `sessions`."""
    api = APIRouter()
    log = logs.for_tick(None)

    @api.get("/session", operation_id="getSession")
    def session(request: Request) -> Session:
        if sessions.open:
            return Session(signed_in=True, token=OPEN_TOKEN)
        signed = sessions.of(request)
        if signed is None:
            return Session(signed_in=False)
        return Session(signed_in=True, token=sessions.token(signed))

    @api.post("/session", operation_id="signIn", responses={401: {"description": "Not the listener secret."}})
    async def sign_in(body: SignIn, response: Response) -> Session:
        if not sessions.secret_matches(body.secret):
            log.warning("web UI sign-in refused: not the listener secret")
            await asyncio.sleep(FAILED_SIGN_IN_SECONDS)
            raise HTTPException(status_code=401, detail="that is not the listener secret")
        if sessions.open:
            return Session(signed_in=True, token=OPEN_TOKEN)
        value = sessions.issue()
        response.set_cookie(
            sessions.cookie_name,
            value,
            max_age=SESSION_SECONDS,
            path=sessions.cookie_path,
            httponly=True,
            samesite="strict",
        )
        signed = sessions.check(value)
        log.info("web UI signed in")
        return Session(signed_in=True, token=sessions.token(signed) if signed is not None else None)

    @api.delete("/session", operation_id="signOut")
    def sign_out(response: Response) -> Session:
        response.delete_cookie(sessions.cookie_name, path=sessions.cookie_path, httponly=True, samesite="strict")
        return Session(signed_in=sessions.open, token=OPEN_TOKEN if sessions.open else None)

    return api
