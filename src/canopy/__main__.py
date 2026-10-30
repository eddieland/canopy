"""`python -m canopy`: how a tick starts `canopy _run`, and the runtime `canopy _mcp`, without depending on PATH."""

import sys

from canopy.cli.launcher import main

sys.exit(main())
