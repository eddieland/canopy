"""The codemods canopy's code is held to, by the name the command line takes.

A new codemod is a module beside this one holding a `command.Command`, and a line here: `make fmt` then applies
it and `make lint` fails on a file it would change, so it must leave alone a file it has already rewritten.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Final

from canopy_codemods.doc_comments import DocComments
from canopy_codemods.final_constants import FinalConstants
from canopy_codemods.general_params import GeneralParams
from canopy_codemods.type_aliases import TypeAliases

if TYPE_CHECKING:
    from collections.abc import Mapping

    from canopy_codemods.command import Command

#: Each codemod by name, in the order they run on a file.
CODEMODS: Final[Mapping[str, type[Command]]] = {
    "final-constants": FinalConstants,
    "type-aliases": TypeAliases,
    "doc-comments": DocComments,
    "general-params": GeneralParams,
}
