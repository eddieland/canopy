"""The API's type for dictation (DESIGN §22): what the operator's own command heard in a recording.

Built on `schema.Model`, as every API type is (schema/__init__.py).
"""

from __future__ import annotations

from canopy.serve.schema import Model


class Dictated(Model):
    """What the dictation command heard, for the page to put in the field the operator recorded into."""

    text: str
    """What it heard, as one paragraph: empty when it heard nothing. Nothing sends it; the operator reads it first."""
    seconds: float
    """How long the recording was, in seconds."""
