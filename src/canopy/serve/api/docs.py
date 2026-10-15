"""The API's own docs: its OpenAPI schema, and a Swagger UI page over it, behind the session like every other route.

FastAPI's stock page loads Swagger UI from a CDN; this one loads the copy the UI's build carries in `api-docs/`
(vite.config.ts), so it makes no request to another origin, and carries a CSP as index.html does. Its writes carry the
session's token, as the UI's do, so "Try it out" works on every route. Neither route is in the schema.
"""

from __future__ import annotations

import json
from typing import Any

from fastapi import APIRouter, Request
from fastapi.responses import HTMLResponse, JSONResponse

from canopy.serve.api.deps import SpaDep
from canopy.serve.spa import content_security_policy

router = APIRouter(include_in_schema=False)


@router.get("/openapi.json")
def openapi(request: Request) -> JSONResponse:
    """The app's OpenAPI schema, as `python -m canopy.serve openapi` prints it."""
    schema: dict[str, Any] = request.app.openapi()
    return JSONResponse(schema)


@router.get("/docs")
def docs(spa: SpaDep) -> HTMLResponse:
    """A Swagger UI page over the schema."""
    html = _page(spa.base_path)
    headers = {"Cache-Control": "no-cache", "Content-Security-Policy": content_security_policy(html)}
    return HTMLResponse(html, headers=headers)


def _page(base: str) -> str:
    # base_path is validated to need no escaping (options.py), and json.dumps quotes it for the script.
    urls = json.dumps({"openapi": f"{base}/api/openapi.json", "session": f"{base}/api/session"})
    return f"""<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<title>canopy API</title>
<link rel="icon" type="image/svg+xml" href="{base}/favicon.svg">
<link rel="stylesheet" href="{base}/api-docs/swagger-ui.css">
</head>
<body>
<div id="swagger-ui"></div>
<script src="{base}/api-docs/swagger-ui-bundle.js"></script>
<script>
const urls = {urls};
let token;
SwaggerUIBundle({{
    url: urls.openapi,
    dom_id: "#swagger-ui",
    presets: [SwaggerUIBundle.presets.apis],
    layout: "BaseLayout",
    deepLinking: true,
    validatorUrl: null,
    // A write needs the session's token as well as its cookie (auth.py).
    requestInterceptor: async (request) => {{
        if (!["GET", "HEAD"].includes((request.method ?? "GET").toUpperCase())) {{
            token ??= (await (await fetch(urls.session)).json()).token;
            request.headers["X-Canopy-Token"] = token;
        }}
        return request;
    }},
}});
</script>
</body>
</html>
"""
