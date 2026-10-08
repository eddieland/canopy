"""How a server is set up: where it listens, the path prefix it serves under, and whether it serves mock data."""

from __future__ import annotations

import ipaddress
import re
from pathlib import Path

from pydantic import BaseModel, ConfigDict, Field, field_validator

# Host names that mean loopback. The Host and Origin checks (guard.py) accept these and nothing else.
LOOPBACK_NAMES = frozenset({"localhost", "127.0.0.1", "::1"})

# A prefix the UI is reached under through a proxy: `/canopy`, `/a/b`. Restricted to characters that need no escaping
# in a URL or an HTML attribute, since spa.py writes it into index.html's <base href>.
_BASE_PATH = re.compile(r"(/[A-Za-z0-9._~-]+)*")


class ServeOptions(BaseModel):
    """A server's settings. Frozen: one server, one set."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    host: str = "127.0.0.1"
    port: int = Field(default=8765, ge=1, le=65535)
    # Empty for the root, otherwise starting with `/` and with no trailing `/`.
    base_path: str = ""
    # Serve the fixtures in mock.py instead of the journal. The sessions and leases endpoints have no real source yet.
    mock: bool = False
    # Seconds between mock events on the stream; None sends none, which keeps screenshots stable.
    mock_event_seconds: float | None = Field(default=3.0, gt=0)
    # The built UI (index.html and assets/). None serves a page saying it is not built.
    ui_dir: Path | None = None

    @field_validator("host")
    @classmethod
    def _loopback_only(cls, value: str) -> str:
        # T8 also allows a private address, behind the listener secret. Until the secret exists, loopback only.
        if value in LOOPBACK_NAMES:
            return value
        try:
            address = ipaddress.ip_address(value)
        except ValueError:
            raise ValueError(f"host {value!r} is not a loopback address") from None
        if not address.is_loopback:
            raise ValueError(f"host {value!r} is not a loopback address")
        return value

    @field_validator("base_path")
    @classmethod
    def _valid_base_path(cls, value: str) -> str:
        if not _BASE_PATH.fullmatch(value) or any(part in {".", ".."} for part in value.split("/")):
            raise ValueError(f"base path {value!r} must be empty or like /canopy, with no trailing slash")
        return value
