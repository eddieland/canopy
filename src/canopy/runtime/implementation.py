"""The runtimes canopy can run, bound in one place (D009): the implementation behind each of the surface's modules.

Nothing but this module imports an implementation, so a new runtime, or a new major version of this one, is a package
beside the others with the same modules, bound here, and the definitions and default templates it reads. Config's
`runtime.version` chooses which one runs (`Version`), and the surface passes each call to it (`pick`): one at a time,
with no adapter interface between them (AGENTS.md, Do not build).
"""

from __future__ import annotations

from enum import IntEnum
from typing import assert_never

from canopy.runtime import opencode as one
from canopy.runtime import opencode2 as two

__all__ = ["Version", "one", "pick", "two"]


class Version(IntEnum):
    """The major version of the runtime canopy runs, as config's `runtime.version` names it."""

    #: The default: OpenCode 1.
    ONE = 1
    #: OpenCode 2, which the operator asks for.
    TWO = 2


def pick[T](version: Version, first: T, second: T) -> T:
    """Return what `version` runs: `first` for `Version.ONE`, `second` for `Version.TWO`.

    The two are the same module of each implementation, so the type checker holds a call on the result to both.
    """
    match version:
        case Version.ONE:
            return first
        case Version.TWO:
            return second
        case _:
            assert_never(version)
