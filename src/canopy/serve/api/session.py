"""Signing in and out with the listener secret (auth.py). The only routes that need no session."""

from __future__ import annotations

import asyncio

from fastapi import APIRouter, HTTPException, Request, Response

from canopy.infra import logs
from canopy.serve.api.deps import SessionsDep
from canopy.serve.auth import FAILED_SIGN_IN_SECONDS, OPEN_TOKEN, SESSION_SECONDS, SIGNED_IN
from canopy.serve.schema import ErrorResponse, Session, SignIn

TAG = "session"
router = APIRouter(tags=[TAG])
_log = logs.for_tick(None)


@router.get("/session", operation_id="getSession", summary="Get the session")
def session(request: Request, sessions: SessionsDep) -> Session:
    """Whether this browser is signed in, and if so the token its writes must carry as `X-Canopy-Token`."""
    if sessions.open:
        return Session(signed_in=True, token=OPEN_TOKEN)
    signed = sessions.of(request)
    if signed is None:
        return Session(signed_in=False)
    return Session(signed_in=True, token=sessions.token(signed))


@router.post(
    "/session",
    operation_id="signIn",
    summary="Sign in",
    responses={401: {"model": ErrorResponse, "description": "Not the listener secret."}},
)
async def sign_in(body: SignIn, request: Request, response: Response, sessions: SessionsDep) -> Session:
    """Sign in with the listener secret: a right one sets the session cookie for 30 days, and returns its token.

    A wrong one is answered after a second; guesses sent at once are not slowed, so the secret must be random.
    """
    if not sessions.secret_matches(body.secret):
        _log.warning("web UI sign-in refused: not the listener secret")
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
    setattr(request.state, SIGNED_IN, signed)
    _log.info("web UI signed in")
    return Session(signed_in=True, token=sessions.token(signed) if signed is not None else None)


@router.delete("/session", operation_id="signOut", summary="Sign out")
def sign_out(response: Response, sessions: SessionsDep) -> Session:
    """Clear the session cookie in this browser. Other browsers stay signed in until the secret changes."""
    response.delete_cookie(sessions.cookie_name, path=sessions.cookie_path, httponly=True, samesite="strict")
    return Session(signed_in=sessions.open, token=OPEN_TOKEN if sessions.open else None)
