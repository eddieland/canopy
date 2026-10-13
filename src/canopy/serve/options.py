"""How a server is set up: where it listens, the path prefix it serves under, and whether it serves mock data."""

from __future__ import annotations

import ipaddress
from pathlib import Path
from typing import Annotated

from pydantic import AfterValidator, BaseModel, ConfigDict, Field

from canopy.core.config import LOOPBACK_NAMES, check_base_path, listen_address


class ServeOptions(BaseModel):
    """A server's settings. Frozen: one server, one set."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    # Loopback, or a private address (TRUST_MODEL T8): `serve.bind`.
    host: Annotated[str, AfterValidator(listen_address)] = "127.0.0.1"
    port: int = Field(default=8765, ge=1, le=65535)
    # Empty for the root, otherwise starting with `/` and with no trailing `/`.
    base_path: Annotated[str, AfterValidator(check_base_path)] = ""
    # Serve a journal seeded from fixtures (mock.py), shown as `mock` in the UI's header.
    mock: bool = False
    # Seconds between the mock journal's changes, which the stream then shows; None makes none, for stable screenshots.
    mock_event_seconds: float | None = Field(default=3.0, gt=0)
    # The built UI (index.html and assets/). None serves a page saying it is not built.
    ui_dir: Path | None = None

    @property
    def hosts(self) -> frozenset[str]:
        """The names the Host and Origin checks allow: loopback, and the bind address."""
        return LOOPBACK_NAMES | {self.host}

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
