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

__all__ = ["Version", "deprecation", "one", "pick", "two"]


class Version(IntEnum):
    """The major version of the runtime canopy runs, as config's `runtime.version` names it."""

    #: OpenCode 1, which the operator asks for. Deprecated: it is to be dropped (`deprecation`).
    ONE = 1
    #: The default: OpenCode 2.
    TWO = 2


def deprecation(version: Version) -> str | None:
    """Return what to tell the operator of `version` if it is deprecated, or None if it is not."""
    match version:
        case Version.ONE:
            return (
                "runtime.version 1 is deprecated, and a later release drops it: remove `version = 1` from [runtime] "
                "to run version 2 (2.1.4 or later), the default"
            )
        case Version.TWO:
            return None
        case _:
            assert_never(version)


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
