"""`python -m canopy`: how `canopy dispatch` starts `canopy _run` without depending on PATH."""

import sys

from canopy.cli.main import main

sys.exit(main())
