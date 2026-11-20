"""canopy's own codemods: the rewrites only its code has a use for, which brash runs with its own.

brash (https://github.com/eddieland/brash) holds the codemods any project can use, and `make fmt` and `make lint` run
it. A codemod that reads canopy's source, as `vocab-members` reads the vocabularies, is a module here, registered
under `[tool.brash.codemods]` in `pyproject.toml`. It is a dev tool: canopy neither ships nor runs it.
"""
