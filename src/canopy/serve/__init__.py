"""The web UI's server (DESIGN §22, D073, D079): the JSON and SSE API, and the built single-page app.

The only package that imports the web stack (fastapi, starlette, uvicorn). Not yet run by `canopy loop`: that waits on
TRUST_MODEL T8's listener secret (ROADMAP M20). Until then `python -m canopy.serve` runs it for development and tests.
"""
