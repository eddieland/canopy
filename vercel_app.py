"""Vercel's entrypoint for the public demo of the web UI over mock data (canopy.serve.demo, D122).

`[tool.vercel] entrypoint` in pyproject.toml names this file's `app`, which Vercel imports once per instance. It
serves fixtures only; nothing here ever reads an operator's journal.
"""

import os
import tempfile
from pathlib import Path

from canopy.serve import demo

# Not cleaned up: the journal lives as long as the instance serving it, and goes with it.
app = demo.create(os.environ, Path(tempfile.mkdtemp(prefix="canopy-demo-")))
