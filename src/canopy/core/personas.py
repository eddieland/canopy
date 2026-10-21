"""Personas (DESIGN §31): the voice a planner, a reviewer, or a worker writes in, chosen by the operator alone.

A persona is a file, `<name>.md`, in the operator's `paths.personas` directory, which shadows one canopy ships of the
same name, or among those canopy ships. A run's persona is its agent's in `[personas]`, `canopy` unless the operator
chose another, fixed when the run starts. It is never fallen back from: a name with no file refuses the run
(`persona_missing`), and a file canopy would not put in a prompt refuses it too (`bad_persona`), since a run in a voice
nobody chose would read as the chosen one's. A persona is instructions in every run it reaches, so its file is bounded
as the standing instructions are, and holds none of the characters a lesson may not (DESIGN §28, Bounds).
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING, Literal

from canopy.core import memory_text
from canopy.core.config import DEFAULT_PERSONA, PERSONA_NAME_RE
from canopy.core.vocab import RunKind
from canopy.infra import resources

if TYPE_CHECKING:
    from collections.abc import Sequence

    from canopy.core.config import Config

#: The persona every agent writes in unless the operator chooses another: canopy's own voice.
DEFAULT = DEFAULT_PERSONA
#: A persona's file is its name with this suffix.
SUFFIX = ".md"
#: The most bytes a persona's file may hold: it is in every prompt it reaches, as the standing instructions are.
MAX_BYTES = 4096
#: An agent a persona reaches, each a key of `[personas]`. The overseer and chores have none.
Agent = Literal["worker", "planner", "reviewer"]
#: Every agent a persona reaches, in the order `[personas]` lists them.
AGENTS: tuple[Agent, ...] = ("worker", "planner", "reviewer")
#: The guard and attention reason of a run whose persona has no file.
MISSING = "persona_missing"
#: The guard and attention reason of a run whose persona's file canopy would not put in a prompt.
BAD = "bad_persona"


class PersonaError(Exception):
    """A run's persona cannot be used: `guard` is `MISSING` or `BAD`, and the message says why, naming the persona."""

    def __init__(self, guard: str, reason: str) -> None:
        """Name the guard and say why."""
        super().__init__(reason)
        self.guard = guard
        self.reason = reason


@dataclass(frozen=True)
class Persona:
    """A persona as a run gets it: its name, its text, and the digest of that text, which the run records."""

    name: str
    #: The file's text without its surrounding blank lines, as the prompt carries it.
    text: str
    #: The sha256 of `text`, in hex: a persona edited between two runs splits them.
    digest: str


@dataclass(frozen=True)
class Listed:
    """A persona as `canopy personas` lists it: where it comes from, the agents it is the default for, and its state."""

    name: str
    #: The file a run would read.
    path: Path
    #: Whether that file is the operator's; False for one canopy ships.
    yours: bool
    #: Whether the operator's file stands in place of one canopy ships of the same name.
    shadows: bool
    #: The agents whose `[personas]` names it, in `AGENTS`' order.
    defaults: Sequence[Agent]
    #: Why a run would refuse it, or None when it would render.
    error: str | None = None


def agent_of(kind: str) -> Agent | None:
    """Return the agent a worker run of `kind` is, for its persona (DESIGN §31).

    Returns:
        `worker` for an `implement` or a `resume`, public or private; `planner` for a plan; None for a kind no persona
        reaches, a feedback plan among them, whose prompt carries none.
    """
    if kind in (RunKind.IMPLEMENT, RunKind.RESUME):
        return "worker"
    if kind == RunKind.PLAN:
        return "planner"
    return None


def chosen(config: Config, agent: Agent) -> Persona:
    """Return the persona `agent`'s runs get now: the one `[personas]` names for it.

    Returns:
        The persona, read from its file.

    Raises:
        PersonaError: (`MISSING`) the name has no file, or (`BAD`) its file is one canopy would not put in a prompt.
    """
    name: str = getattr(config.personas, agent)
    try:
        return load(config, name)
    except PersonaError as e:
        raise PersonaError(e.guard, f"[personas] {agent}: {e.reason}") from e


def load(config: Config, name: str) -> Persona:
    """Return the persona `name`, from the operator's file of that name, else canopy's.

    Returns:
        The persona: its name, its text without surrounding blank lines, and that text's digest.

    Raises:
        PersonaError: (`MISSING`) neither has a file of that name, or (`BAD`) the file cannot be read, is not UTF-8,
            is over `MAX_BYTES`, or holds a character that hides text.
    """
    path = find(config, name)
    if path is None:
        raise PersonaError(MISSING, f"persona {name} has no file{_where(config)}")
    text = _read(name, path)
    return Persona(name, text, hashlib.sha256(text.encode()).hexdigest())


def find(config: Config, name: str) -> Path | None:
    """Return the file persona `name` is read from: the operator's of that name, else canopy's, else None.

    Returns:
        The file's path, or None when neither directory has one, or `name` is not a persona's name.
    """
    if PERSONA_NAME_RE.fullmatch(name) is None:
        return None
    for directory in (config.paths.personas, resources.personas_dir()):
        if directory is not None and (directory / f"{name}{SUFFIX}").is_file():
            return directory / f"{name}{SUFFIX}"
    return None


def listed(config: Config) -> list[Listed]:
    """Return every persona a run could get, by name: canopy's and the operator's, each read as a run would read it.

    Returns:
        Each persona once, by name, the operator's in place of canopy's of the same name.
    """
    shipped = _names(resources.personas_dir())
    yours = _names(config.paths.personas) if config.paths.personas is not None else set()
    found: list[Listed] = []
    for name in sorted(shipped | yours):
        path = find(config, name)
        if path is None:
            continue
        try:
            _read(name, path)
            error = None
        except PersonaError as e:
            error = e.reason
        defaults = tuple(a for a in AGENTS if getattr(config.personas, a) == name)
        found.append(Listed(name, path, name in yours, name in yours and name in shipped, defaults, error))
    return found


def _names(directory: Path) -> set[str]:
    # The persona names `directory` holds files for; a file whose name is no persona's is never read.
    if not directory.is_dir():
        return set()
    return {
        p.stem for p in directory.glob(f"*{SUFFIX}") if p.is_file() and PERSONA_NAME_RE.fullmatch(p.stem) is not None
    }


def _read(name: str, path: Path) -> str:
    """Return a persona's text, without surrounding blank lines, refusing a file canopy would not put in a prompt.

    Raises:
        PersonaError: (`BAD`) the file cannot be read, is not UTF-8, is over `MAX_BYTES`, or holds a character that
            hides text: one `memory_text.hidden_char` names, but a line feed or a tab.
    """
    try:
        data = path.read_bytes()
        text = data.decode("utf-8")
    except (OSError, UnicodeDecodeError) as e:
        raise PersonaError(BAD, f"persona {name} at {path} cannot be read: {e}") from e
    if len(data) > MAX_BYTES:
        raise PersonaError(BAD, f"persona {name} at {path} is {len(data)} bytes, over {MAX_BYTES}")
    hidden = next((c for c in text if memory_text.hidden_char(c) and c not in "\n\t"), None)
    if hidden is not None:
        raise PersonaError(BAD, f"persona {name} at {path} holds U+{ord(hidden):04X}, a character that hides text")
    return text.strip()


def _where(config: Config) -> str:
    # Where a persona's file was looked for, and what to do, to end a refusal's sentence.
    yours = f" in {config.paths.personas} or" if config.paths.personas is not None else ""
    return f"{yours} among canopy's own: add it, or name one `canopy personas` lists"
