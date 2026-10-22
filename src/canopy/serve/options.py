"""How a server is set up: where it listens, the path prefix it serves under, and whether it serves mock data."""

from __future__ import annotations

import ipaddress
import re
from pathlib import Path
from typing import Annotated, Self

from pydantic import AfterValidator, BaseModel, ConfigDict, Field, model_validator

from canopy.core.config import LOOPBACK_NAMES, check_base_path, listen_address

#: A DNS name as a Host header carries it, without a port: `canopy-demo.vercel.app`.
_HOST_NAME_RE = re.compile(r"[a-z0-9]([a-z0-9-]*[a-z0-9])?(\.[a-z0-9]([a-z0-9-]*[a-z0-9])?)*")
#: How long an event stream stays open by default. A port forwarder can keep its side of a stream open after the page
#: has gone (#1299), so the server never hears the page leave: the lifetime ends such a stream, and its polling, on
#: its own, while an open page just opens the next one at once.
STREAM_SECONDS = 300.0


class ServeOptions(BaseModel):
    """A server's settings. Frozen: one server, one set."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    #: Loopback, or a private address (TRUST_MODEL T8): `serve.bind`.
    host: Annotated[str, AfterValidator(listen_address)] = "127.0.0.1"
    port: int = Field(default=8765, ge=1, le=65535)
    #: Empty for the root, otherwise starting with `/` and with no trailing `/`.
    base_path: Annotated[str, AfterValidator(check_base_path)] = ""
    #: Serve a journal seeded from fixtures (mock.py), shown as `mock` in the UI's header.
    mock: bool = False
    #: Seconds between the mock journal's changes, which the stream then shows; None makes none, for stable screenshots.
    mock_event_seconds: float | None = Field(default=3.0, gt=0)
    #: The built UI (index.html and assets/). None serves a page saying it is not built.
    ui_dir: Path | None = None
    #: Seconds an event stream stays open before the server ends it and the browser opens another: shorter for a host
    #: that cuts a long request (demo.py).
    stream_seconds: float = Field(default=STREAM_SECONDS, gt=0)
    #: Public names the Host and Origin checks allow too, for the demo a host such as Vercel runs (demo.py). Mock data
    #: only (D122): the operator's journal is never served under a public name.
    public_hosts: frozenset[str] = frozenset()

    @model_validator(mode="after")
    def _public_only_for_mock(self) -> Self:
        if self.public_hosts and not self.mock:
            raise ValueError("only mock data is served under a public name (D122)")
        bad = sorted(name for name in self.public_hosts if not _HOST_NAME_RE.fullmatch(name))
        if bad:
            raise ValueError(f"not a lowercase host name without a port: {', '.join(bad)}")
        return self

    @property
    def hosts(self) -> frozenset[str]:
        """The names the Host and Origin checks allow: loopback, the bind address, and any public names."""
        return LOOPBACK_NAMES | {self.host} | self.public_hosts

    @property
    def loopback(self) -> bool:
        """Whether the server binds a loopback address."""
        return self.host in LOOPBACK_NAMES or ipaddress.ip_address(self.host).is_loopback

    def url(self) -> str:
        """The UI's address, for the operator to open.

        Returns:
            `http://HOST:PORT/` under `base_path`, an IPv6 host in brackets.
        """
        host = f"[{self.host}]" if ":" in self.host else self.host
        return f"http://{host}:{self.port}{self.base_path}/"
