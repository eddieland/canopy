"""The `canopy` console script and `python -m canopy`: `canopy --version` answered without loading the CLI.

Every tick runs `canopy --version` to check the overseer can start `canopy` (DESIGN §6). The CLI's imports, click, the
config, and pydantic, are most of a start's cost, so the check pays only for an interpreter and a metadata read. Any
other arguments go to `canopy.cli.main`.
"""

import sys
from importlib.metadata import version


def main() -> int:
    """Print canopy's version for `--version` alone, as click's version option does; otherwise run the CLI.

    Returns:
        The process exit code.
    """
    if sys.argv[1:] == ["--version"]:
        sys.stdout.write(f"canopy {version('canopy')}\n")
        return 0
    # Imported here: it is what `--version` skips.
    from canopy.cli.main import main as run  # noqa: PLC0415

    return run()
