"""`python -m canopy.serve`: the development server over mock data, or the OpenAPI schema (canopy.cli.devserver)."""

import sys

from canopy.cli.devserver import main

# Guarded, unlike canopy's own `__main__`: tests/canopy/test_models.py imports every module of canopy.
if __name__ == "__main__":
    sys.exit(main())
