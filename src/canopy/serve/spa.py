"""Serves the built single-page app: hashed assets, other files at the build's root, and index.html for routes.

index.html carries its build's id, which `GET /api/meta` reports too, so a page loaded before an upgrade can tell it
is out of date and offer a reload.

The fallback to index.html is for the app's own routes only. It never answers under the API prefix, never for a
path with a file extension (a missing asset is a 404, not a page that fails to parse as a script), and never for
anything but GET and HEAD.
"""

from __future__ import annotations

import base64
import hashlib
import re
from pathlib import Path, PurePosixPath
from typing import TYPE_CHECKING, Final

from starlette.responses import FileResponse, HTMLResponse, JSONResponse, Response

if TYPE_CHECKING:
    from starlette.requests import Request

# Vite puts content-hashed files here; a name changes whenever its content does, so they can be cached forever.
_ASSETS: Final = "assets"
_IMMUTABLE: Final = "public, max-age=31536000, immutable"
# index.html names the current assets, so the browser must revalidate it on every load or an upgrade shows a stale UI.
_NO_CACHE: Final = "no-cache"
# The name of the meta tag in index.html that holds its build's id (SinglePageApp.build); the UI reads it there.
BUILD_META: Final = "canopy-build"
_INLINE_SCRIPT: Final = re.compile(r"<script(?![^>]*\bsrc=)[^>]*>(.*?)</script>", re.DOTALL)

_NOT_BUILT: Final = """<!doctype html>
<html lang="en"><head><meta charset="utf-8"><title>canopy</title></head>
<body><p>canopy's web UI is not built into this installation. Build it with <code>make ui-build</code>, or
reinstall canopy with Node 22.12+ and npm on PATH.</p></body></html>
"""


def content_security_policy(html: str) -> str:
    """Return a CSP for `html` that allows its inline scripts by hash, and nothing from another origin."""
    hashes = " ".join(
        f"'sha256-{base64.b64encode(hashlib.sha256(m.group(1).encode()).digest()).decode()}'"
        for m in _INLINE_SCRIPT.finditer(html)
    )
    return "; ".join(
        (
            "default-src 'self'",
            f"script-src 'self' {hashes}".rstrip(),
            # Radix and React set style attributes; Tailwind's CSS is a file.
            "style-src 'self' 'unsafe-inline'",
            "img-src 'self' data:",
            "font-src 'self'",
            "connect-src 'self'",
            "base-uri 'self'",
            "form-action 'self'",
            "frame-ancestors 'none'",
        ),
    )


class SinglePageApp:
    """The build in `ui_dir`, served under `base_path`. A None `ui_dir` serves a page saying it is not built."""

    def __init__(self, ui_dir: Path | None, *, base_path: str) -> None:
        """Serve the build in `ui_dir` (or a placeholder) with every URL under `base_path`."""
        self.ui_dir = ui_dir.resolve() if ui_dir is not None else None
        self.base_path = base_path

    async def respond(self, request: Request) -> Response:
        """Answer a GET or HEAD for `{base_path}/{path}`. A Starlette endpoint, so FastAPI injects nothing.

        Returns:
            A 404 under `api/`, a 503 placeholder page when the UI is not built, the file for an asset or a path with
            an extension (404 if there is none), and index.html for any other path.
        """
        path = str(request.path_params.get("path", ""))
        parts = PurePosixPath(path).parts
        if parts[:1] == ("api",):
            return JSONResponse({"detail": "Not Found"}, status_code=404)
        ui_dir = self.ui_dir
        if ui_dir is None or not (ui_dir / "index.html").is_file():
            return HTMLResponse(_NOT_BUILT, status_code=503, headers={"Cache-Control": _NO_CACHE})
        if parts[:1] == (_ASSETS,) or PurePosixPath(path).suffix:
            return _file(ui_dir, parts)
        return self._index(ui_dir)

    def build(self) -> str | None:
        """Return the id of the build served now, or None when the UI is not built.

        Returns:
            A digest of index.html as it is on disk, which names every hashed asset, so it changes with any of them.
        """
        if self.ui_dir is None:
            return None
        # Read without checking first: an upgrade may replace the file between a check and the read.
        try:
            return _build_id((self.ui_dir / "index.html").read_bytes())
        except OSError:
            return None

    def _index(self, ui_dir: Path) -> Response:
        raw = (ui_dir / "index.html").read_bytes()
        html = raw.decode("utf-8")
        # One build serves under any prefix: the app's URLs are relative and resolve against this, and the router
        # reads its basepath from document.baseURI. base_path is validated to need no escaping (options.py). The
        # build's id is hex, so it needs none either.
        base = f'<base href="{self.base_path}/" />'
        build = f'<meta name="{BUILD_META}" content="{_build_id(raw)}" />'
        html = html.replace("<head>", f"<head>\n    {base}\n    {build}", 1)
        headers = {"Cache-Control": _NO_CACHE, "Content-Security-Policy": content_security_policy(html)}
        return HTMLResponse(html, headers=headers)


def _build_id(index: bytes) -> str:
    return hashlib.sha256(index).hexdigest()[:16]


def _file(ui_dir: Path, parts: tuple[str, ...]) -> Response:
    target = ui_dir.joinpath(*parts).resolve()
    if ".." in parts or not target.is_relative_to(ui_dir) or not target.is_file() or target.name == "index.html":
        return Response("Not Found", status_code=404, media_type="text/plain")
    cache = _IMMUTABLE if parts[:1] == (_ASSETS,) else _NO_CACHE
    return FileResponse(target, headers={"Cache-Control": cache})
