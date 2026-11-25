"""The environment every agent canopy starts runs with, and the operator's `setup_cmd` and `idle_cmd` (TRUST_MODEL T4).

A run inherits the environment of the process that started it, which is the loop's: whatever the operator's shell held
when they started it, such as an editor's integrated terminal. That can name the editor's askpass, which a push whose
credential helper has nothing asks over the editor's socket, waiting on a prompt in the operator's window; the editor's
own socket, through which `code` acts in that window; the operator's terminal, where a pinentry draws; and `EDITOR=vi`,
which a `git commit` with no `-m` starts with no terminal, its escape codes landing in a tool result.

So each such process gets `ENV` over what it inherits, before canopy's own variables, which a run's need wins over:
git and the tools beside it never prompt, page, or start an editor, and print no colour. And it starts without the
variables `unset` names in the inherited environment, which reach the operator's editor, terminal, or display.
`canopy desk` is the operator's own checkout, and none of this applies there.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Final

from canopy.core import hostgit

if TYPE_CHECKING:
    from collections.abc import Iterable

#: What every agent canopy starts, and the operator's commands in a slot, find set, whatever they inherit: git's no
#: prompt, askpass, or credential manager's window (`hostgit.ENV`), no editor, which `true` answers as an editor that
#: kept what it was given, no pager, no advice, and no terminal to colour or draw on.
ENV: Final = {
    **hostgit.ENV,
    "GCM_INTERACTIVE": "never",
    "GIT_EDITOR": "true",
    "GIT_SEQUENCE_EDITOR": "true",
    "GIT_MERGE_AUTOEDIT": "no",
    "GIT_PAGER": "cat",
    "PAGER": "cat",
    "GH_PAGER": "cat",
    "GH_PROMPT_DISABLED": "1",
    "GIT_ADVICE": "0",
    "NO_COLOR": "1",
    "TERM": "dumb",
}
#: The variables removed by name: the operator's terminal's colours and pinentry, the displays a pinentry or an askpass
#: draws a window on, and ssh's askpass.
_UNSET: Final = frozenset({"COLORTERM", "GPG_TTY", "DISPLAY", "WAYLAND_DISPLAY", "SSH_ASKPASS"})
#: The variables removed by the start of their name: an editor's, such as its socket, and the terminal program's.
_UNSET_PREFIXES: Final = ("VSCODE_", "TERM_PROGRAM")


def unset(environ: Iterable[str]) -> frozenset[str]:
    """The names of `environ`, the environment a run would inherit, removed from the run's.

    Returns:
        The names, for a runner's `unset`.
    """
    return frozenset(name for name in environ if name in _UNSET or name.startswith(_UNSET_PREFIXES))
