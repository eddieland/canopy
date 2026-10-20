"""Signing in with the listener secret (TRUST_MODEL T8, DESIGN §22).

The sign-in page sends the secret once. A right one gets a session cookie: its issue time and a random nonce, signed
with the secret, so the server keeps no sessions, a session outlives a loop restart, and a new secret ends them all. The
per-session token is a second signature over the same time and nonce, with a different label; a page reads it from
`GET /api/session` and sends it on every write.

`Sessions(None, ...)` signs nobody in and checks nothing: only `python -m canopy.serve --mock` builds one, over fixture
data, on loopback.
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import secrets
import time
from collections.abc import Callable
from dataclasses import dataclass

from fastapi import HTTPException, Request

from canopy.serve.guard import allowed_origin

COOKIE_PREFIX = "canopy_session_"
TOKEN_HEADER = "x-canopy-token"  # noqa: S105  (a header name, not a credential)
SESSION_SECONDS = 30 * 24 * 3600
# A wrong secret is answered after this long. It slows one client guessing in turn, not many guessing at once, so what
# stops guessing is a secret no one can predict: `canopy secret` writes 32 random bytes. `secret.read` refuses fewer
# than 32 characters, but cannot tell a predictable one, so a secret the operator writes by hand must be random too.
FAILED_SIGN_IN_SECONDS = 1.0
# What `GET /api/session` gives a page when nobody signs in (mock data only).
OPEN_TOKEN = "open"  # noqa: S105  (not a credential: the open server checks none)
_VERSION = "v1"
#: The methods that read; any other is a write, which needs the session's token (`Sessions.require`).
READ_METHODS = frozenset({"GET", "HEAD"})
#: Where a write the server lets through leaves, in the request's state, the session it was let through as, and a
#: sign-in the session it issued: None on an open server, which signs nobody in. audit.py records what it finds there.
AUTHORIZED = "canopy_authorized"


@dataclass(frozen=True)
class Signed:
    """A session cookie that checked out: when it was issued, and its nonce."""

    issued: int
    nonce: str

    @property
    def fingerprint(self) -> str:
        """A name for the session the journal may keep (audit.py): it tells one session from another, and signs nothing.

        Returns:
            The first 16 hex digits of the sha256 of its issue time and nonce.
        """
        return hashlib.sha256(f"{self.issued}\0{self.nonce}".encode()).hexdigest()[:16]


class Sessions:
    """Signs and checks one server's session cookies and tokens with the listener secret."""

    def __init__(
        self,
        secret: str | None,
        *,
        port: int,
        base_path: str,
        hosts: frozenset[str],
        clock: Callable[[], float] = time.time,
    ) -> None:
        """Sign with `secret`, or with None, sign nobody in. The cookie is named for `port` and scoped to `base_path`.

        A browser sends a host's cookies to every port, so two servers on one host need cookies of different names.
        A write's Origin must name one of `hosts`.
        """
        self._key = secret.encode() if secret is not None else None
        self._hosts = hosts
        self.cookie_name = f"{COOKIE_PREFIX}{port}"
        self.cookie_path = f"{base_path}/"
        self._clock = clock

    @property
    def open(self) -> bool:
        """Whether this server signs nobody in and checks no session (mock data only)."""
        return self._key is None

    def secret_matches(self, given: str) -> bool:
        """Whether `given` is the listener secret, compared in constant time.

        Returns:
            True if it is. An open server takes any secret.
        """
        if self._key is None:
            return True
        return hmac.compare_digest(hashlib.sha256(given.encode()).digest(), hashlib.sha256(self._key).digest())

    def issue(self) -> str:
        """A new session cookie's value.

        Returns:
            The format version, the issue time, a random nonce, and their signature, joined by dots.
        """
        issued = int(self._clock())
        nonce = secrets.token_urlsafe(16)
        return f"{_VERSION}.{issued}.{nonce}.{self._sign('session', issued, nonce)}"

    def check(self, value: str | None) -> Signed | None:
        """The session a cookie value names, or None if it is missing, malformed, forged, or older than 30 days.

        Returns:
            When the session was issued, and its nonce. Always None on an open server.
        """
        if value is None or self._key is None:
            return None
        parts = value.split(".")
        if len(parts) != 4 or parts[0] != _VERSION or not parts[1].isascii() or not parts[1].isdigit():  # noqa: PLR2004
            return None
        issued, nonce, mac = int(parts[1]), parts[2], parts[3]
        if not hmac.compare_digest(mac, self._sign("session", issued, nonce)):
            return None
        if not 0 <= self._clock() - issued < SESSION_SECONDS:
            return None
        return Signed(issued, nonce)

    def token(self, session: Signed) -> str:
        """The token `session`'s writes carry.

        Returns:
            A signature over the session's issue time and nonce, under a label of its own, in URL-safe base64.
        """
        return self._sign("write", session.issued, session.nonce)

    def _sign(self, label: str, issued: int, nonce: str) -> str:
        if self._key is None:
            raise RuntimeError("an open server signs nothing")
        digest = hmac.new(self._key, f"{label}\0{issued}\0{nonce}".encode(), hashlib.sha256).digest()
        return base64.urlsafe_b64encode(digest).decode().rstrip("=")

    def of(self, request: Request) -> Signed | None:
        """The session `request`'s cookie names, if it is a valid one.

        Returns:
            The session, or None without a valid cookie.
        """
        return self.check(request.cookies.get(self.cookie_name))

    def require(self, request: Request) -> None:
        """A FastAPI dependency: refuse a request without a session, and a write without its token and an Origin.

        A write it lets through leaves its session in the request's state under `AUTHORIZED`, for audit.py.

        Raises:
            HTTPException: 401 without a valid session; 403 for a write without the session's token or an Origin
                header naming an allowed host. The guard has already refused a foreign Origin (guard.py).
        """
        if self.open:
            if request.method not in READ_METHODS:
                setattr(request.state, AUTHORIZED, None)
            return
        session = self.of(request)
        if session is None:
            raise HTTPException(status_code=401, detail="sign in with the listener secret")
        if request.method in READ_METHODS:
            return
        given = request.headers.get(TOKEN_HEADER, "")
        if not hmac.compare_digest(given.encode(), self.token(session).encode()):
            raise HTTPException(status_code=403, detail="this write lacks the session's token")
        origin = request.headers.get("origin")
        if origin is None or not allowed_origin(origin, self._hosts):
            raise HTTPException(status_code=403, detail="a write must come from this server's own page")
        setattr(request.state, AUTHORIZED, session)
