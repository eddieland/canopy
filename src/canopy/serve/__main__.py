"""`python -m canopy.serve`: the development server over mock data, or the OpenAPI schema (canopy.cli.devserver)."""

import sys

from canopy.cli.devserver import main

sys.exit(main())
