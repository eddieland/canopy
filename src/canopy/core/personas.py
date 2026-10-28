"""Personas (DESIGN §31): the voice a planner, a reviewer, or a worker writes in, chosen by the operator alone.

A persona is a file, `<name>.md`, in the operator's `paths.personas` directory, which shadows one canopy ships of the
same name, or among those canopy ships. A run's persona is the one the operator chose for its next run alone
(`choose_next`), else its ticket's override for its agent (`choose`), else its agent's in `[personas]`, `canopy` unless
the operator chose another, fixed when the run starts; only the operator chooses any of them. It is never fallen back
from: a name with no file refuses the run (`persona_missing`), and a file canopy would not put in a prompt refuses it
too (`bad_persona`), since a run in a voice nobody chose would read as the chosen one's.
A persona is instructions in every run it reaches, so its file is bounded as the standing instructions are, and holds
none of the characters a lesson may not (DESIGN §28, Bounds). Its file may open with a front matter naming its
`description` for the menus that list it; that is never instructions, so no prompt carries it.
"""

from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING, Final, Literal, NamedTuple

from canopy.core import conversation, db, memory_text, records, sql
from canopy.core.config import DEFAULT_PERSONA, PERSONA_NAME_RE
from canopy.core.vocab import OverrideKind, RunKind
from canopy.infra import resources

if TYPE_CHECKING:
    import sqlite3
    from collections.abc import Sequence

    from canopy.core.config import Config

#: The persona every agent writes in unless the operator chooses another: canopy's own voice.
DEFAULT: Final = DEFAULT_PERSONA
#: A persona's file is its name with this suffix.
SUFFIX: Final = ".md"
#: The most bytes a persona's file may hold: it is in every prompt it reaches, as the standing instructions are.
MAX_BYTES: Final = 4096
#: An agent a persona reaches, each a key of `[personas]`. The overseer and chores have none.
Agent = Literal["worker", "planner", "reviewer"]
#: Every agent a persona reaches, in the order `[personas]` lists them.
AGENTS: Final[tuple[Agent, ...]] = ("worker", "planner", "reviewer")
#: An agent whose next run alone may take a persona of its own: the runs `canopy start` and `canopy plan` ask for.
NextAgent = Literal["worker", "planner"]
#: Every agent whose next run alone may take a persona of its own.
NEXT_AGENTS: Final[tuple[NextAgent, ...]] = ("worker", "planner")
#: The guard and attention reason of a run whose persona has no file.
MISSING: Final = "persona_missing"
#: The guard and attention reason of a run whose persona's file canopy would not put in a prompt.
BAD: Final = "bad_persona"
#: The guard of an override naming a persona with no file: it is refused when set, not when a run starts.
UNKNOWN: Final = "unknown_persona"
#: Where an agent's next persona comes from: the ticket's override, `[personas]`, or canopy's own default.
Source = Literal["ticket", "config", "default"]
#: The most characters of a persona's description a menu shows beside its name; a longer one is cut at a word.
DESCRIPTION_CHARS: Final = 160
#: The one key a persona's front matter may hold.
DESCRIPTION_KEY: Final = "description"
#: A persona's front matter: a `---` line, its fields, and a `---` line, at the very start of its file, as a skill's.
_FRONT_MATTER: Final = re.compile(r"---[ \t]*\n(.*?)^---[ \t]*$\n?", re.DOTALL | re.MULTILINE)
#: The line a front matter opens with; a file that opens with it and never closes it is refused.
_OPENS: Final = re.compile(r"---[ \t]*(?:\n|$)")
#: One field of a front matter: its key, a colon, and its value on the same line.
_FIELD: Final = re.compile(r"([A-Za-z_][\w-]*):[ \t]*(.*)")
#: A value in quotes, single or double, which a front matter's value may be written in, as YAML's.
_QUOTED: Final = re.compile(r"(['\"])(.*)\1")


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
    #: The file's text without its front matter and its surrounding blank lines, as the prompt carries it.
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
    #: What it is: its front matter's `description`, else its text's opening sentence; None when it is refused.
    description: str | None = None


@dataclass(frozen=True)
class Next:
    """The persona one of a ticket's agents writes in at its next run, and where that choice comes from (DESIGN §31)."""

    agent: Agent
    #: The persona its runs write in: the ticket's override, `[personas]`'s, or canopy's.
    name: str
    source: Source
    #: Why that run would refuse its persona, or None when it would render.
    error: str | None = None
    #: The persona the operator chose for its next run alone, in place of `name`, or None when they chose none.
    once: str | None = None
    #: For the reviewer, every persona the ticket's PRs are reviewed in, one review each, from `[personas] reviewers`;
    #: none when it is unset or the ticket's override chooses one.
    several: Sequence[str] = ()


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


def for_run(conn: sqlite3.Connection, config: Config, agent: Agent, ticket: str | None) -> Persona:
    """Return the persona a run of `agent` for `ticket` gets now: its own, the ticket's override, or `[personas]`'s.

    A run for no ticket, such as a review of a coworker's PR, gets `[personas]`'s. The persona chosen for the next run
    alone is spent by the dispatch that records it (`spend_next`).

    Returns:
        The persona, read from its file.

    Raises:
        PersonaError: (`MISSING`) the name has no file, or (`BAD`) its file is one canopy would not put in a prompt.
    """
    once = next_run(conn, ticket, agent) if ticket is not None else None
    if once is not None:
        try:
            return load(config, once)
        except PersonaError as e:
            clear = f"; or clear it: canopy persona {ticket}{_flag(agent)} --next --clear"
            raise PersonaError(e.guard, f"{ticket}'s next {agent} run: {e.reason}{clear}") from e
    name = override(conn, ticket, agent) if ticket is not None else None
    if name is None:
        return chosen(config, agent)
    try:
        return load(config, name)
    except PersonaError as e:
        clear = f"; or clear it: canopy persona {ticket}{_flag(agent)} --clear"
        raise PersonaError(e.guard, f"{ticket}'s {agent} override: {e.reason}{clear}") from e


def override(conn: sqlite3.Connection, ticket: str, agent: Agent) -> str | None:
    """Return the persona the operator chose for `ticket`'s `agent`, or None when they chose none."""
    found = records.fetch_one(
        conn,
        records.TicketOverride,
        sql.select("*")
        .from_("ticket_overrides")
        .where("ticket_key = ? AND agent = ? AND kind = ?", ticket, agent, OverrideKind.PERSONA),
    )
    return found.value if found is not None else None


def reviewers_of(conn: sqlite3.Connection, config: Config, ticket: str) -> list[str]:
    """Return the personas each commit of `ticket`'s PRs is reviewed in, one review each (DESIGN §31).

    Returns:
        `[personas] reviewers`, in its order; none when it is unset, or the ticket's reviewer override chooses one,
        whose single review takes `for_run`'s persona.
    """
    if override(conn, ticket, "reviewer") is not None:
        return []
    return list(config.personas.reviewers)


def next_run(conn: sqlite3.Connection, ticket: str, agent: Agent) -> str | None:
    """Return the persona chosen for the next run alone of `ticket`'s `agent`, or None when none is."""
    found = records.fetch_one(
        conn,
        records.NextRunPersona,
        sql.select("*").from_("next_run_personas").where("ticket_key = ? AND agent = ?", ticket, agent),
    )
    return found.persona if found is not None else None


def next_for(conn: sqlite3.Connection, config: Config, ticket: str) -> list[Next]:
    """Return the persona each of `ticket`'s agents writes in at its next run, in `AGENTS`' order.

    Returns:
        A `Next` per agent: its persona's name, whether the ticket's override, `[personas]`, or canopy's default chose
        it, the persona chosen for its next run alone, if one is, and why that run would refuse the one it gets.
    """
    found: list[Next] = []
    for agent in AGENTS:
        mine = override(conn, ticket, agent)
        configured: str = getattr(config.personas, agent)
        name = mine if mine is not None else configured
        source: Source = "ticket" if mine is not None else "config" if configured != DEFAULT else "default"
        once = next_run(conn, ticket, agent)
        several: list[str] = reviewers_of(conn, config, ticket) if agent == "reviewer" else []
        error = None
        for used in several or [once or name]:
            try:
                load(config, used)
            except PersonaError as e:
                error = error or e.reason
        found.append(Next(agent, name, source, error, once, several))
    return found


def choose(
    conn: sqlite3.Connection,
    config: Config,
    ticket: str,
    agent: Agent,
    name: str | None,
    *,
    channel: str,
) -> Next:
    """Set `ticket`'s override for `agent` to persona `name`, or clear it with None (DESIGN §31). Operator only.

    It may be set before canopy has seen the ticket, and covers every run of that agent for the ticket until cleared.

    Returns:
        The persona the agent's next run for the ticket writes in now, and where it comes from.

    Raises:
        Refused: `inside_run` inside one of canopy's own ticks or runs, `unknown_persona` for a name with no file, or
            `bad_persona` for a file canopy would not put in a prompt.
    """
    conversation.check_operator()
    if name is not None:
        check(config, name)
    where = "ticket_key = ? AND agent = ? AND kind = ?"
    with db.transaction(conn):
        sql.execute(conn, sql.delete("ticket_overrides").where(where, ticket, agent, OverrideKind.PERSONA))
        if name is not None:
            sql.execute(
                conn,
                sql.insert(
                    "ticket_overrides",
                    ticket_key=ticket,
                    agent=agent,
                    kind=OverrideKind.PERSONA,
                    value=name,
                    channel=channel,
                    set_at=db.now(),
                ),
            )
    return next(n for n in next_for(conn, config, ticket) if n.agent == agent)


def choose_next(
    conn: sqlite3.Connection,
    config: Config,
    ticket: str,
    agent: NextAgent,
    name: str | None,
    *,
    channel: str,
) -> Next:
    """Set the persona of the next run alone of `ticket`'s `agent` to `name`, or clear it with None. Operator only.

    It takes the place of the ticket's override and `[personas]` for that run, whatever kind it is, and is spent when
    the run is recorded; a run already running keeps the persona it started with (DESIGN §31).

    Returns:
        The persona the agent's next run for the ticket writes in now, and where it comes from.

    Raises:
        Refused: `inside_run` inside one of canopy's own ticks or runs, `unknown_persona` for a name with no file, or
            `bad_persona` for a file canopy would not put in a prompt.
    """
    conversation.check_operator()
    if name is not None:
        check(config, name)
    with db.transaction(conn):
        sql.execute(conn, sql.delete("next_run_personas").where("ticket_key = ? AND agent = ?", ticket, agent))
        if name is not None:
            sql.execute(
                conn,
                sql.insert(
                    "next_run_personas",
                    ticket_key=ticket,
                    agent=agent,
                    persona=name,
                    channel=channel,
                    set_at=db.now(),
                ),
            )
    return next(n for n in next_for(conn, config, ticket) if n.agent == agent)


def spend_next(conn: sqlite3.Connection, ticket: str, agent: Agent, persona: str) -> None:
    """Spend the persona chosen for the next run alone of `ticket`'s `agent`, inside the transaction recording it.

    Only `persona`, the one the run was rendered in: one the operator chose since stays for the run after.
    """
    where = "ticket_key = ? AND agent = ? AND persona = ?"
    sql.execute(conn, sql.delete("next_run_personas").where(where, ticket, agent, persona))


def check(config: Config, name: str) -> None:
    """Refuse a persona the operator is choosing that a run could not use: it is refused when set, not when one starts.

    Raises:
        Refused: `unknown_persona` for a name with no file, or `bad_persona` for a file canopy would not put in a
            prompt.
    """
    try:
        load(config, name)
    except PersonaError as e:
        raise conversation.Refused(UNKNOWN if e.guard == MISSING else e.guard, e.reason) from e


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
    text = _read(name, path).text
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
            described, error = _read(name, path).description, None
        except PersonaError as e:
            described, error = None, e.reason
        defaults: tuple[Agent, ...] = tuple(
            a
            for a in AGENTS
            if getattr(config.personas, a) == name or (a == "reviewer" and name in config.personas.reviewers)
        )
        shadows = name in yours and name in shipped
        found.append(Listed(name, path, name in yours, shadows, defaults, error, described))
    return found


def description(text: str) -> str | None:
    """Return what a persona is, in its own words, for a menu to show beside its name: its text's opening sentence.

    This is the description of a persona whose front matter names none: its opening sentence most often says what it
    is (`Work like the lazy senior developer...`). Its first paragraph that is not a heading is read, its lines joined,
    up to the end of its first sentence, cut at a word to `DESCRIPTION_CHARS`.

    Returns:
        The sentence, or None for a text with no paragraph but headings.
    """
    paragraphs = (p.strip() for p in re.split(r"\n\s*\n", text))
    words = " ".join(next((p for p in paragraphs if p and not p.startswith("#")), "").split())
    if not words:
        return None
    end = re.search(r"[.!?](?=\s|$)", words)
    return _cut(words[: end.end()] if end is not None else words)


class _File(NamedTuple):
    # A persona's file as canopy reads it: the text a prompt carries, and what a menu shows beside its name.
    text: str
    description: str | None


def _cut(words: str) -> str:
    # `words` cut at a word to `DESCRIPTION_CHARS`, an ellipsis marking the cut.
    if len(words) <= DESCRIPTION_CHARS:
        return words
    cut = words[: DESCRIPTION_CHARS - 1].rsplit(" ", 1)[0]
    return f"{cut.rstrip(',;:')}…"


def _names(directory: Path) -> set[str]:
    # The persona names `directory` holds files for; a file whose name is no persona's is never read.
    if not directory.is_dir():
        return set()
    return {
        p.stem for p in directory.glob(f"*{SUFFIX}") if p.is_file() and PERSONA_NAME_RE.fullmatch(p.stem) is not None
    }


def _read(name: str, path: Path) -> _File:
    """Return a persona's text and description, refusing a file canopy would not put in a prompt.

    The text is the file's without its front matter and its surrounding blank lines; the description is the front
    matter's, else the text's opening sentence.

    Raises:
        PersonaError: (`BAD`) the file cannot be read, is not UTF-8, is over `MAX_BYTES`, holds a character that hides
            text: one `memory_text.hidden_char` names, but a line feed or a tab, or opens a front matter `_front`
            refuses.
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
    body, described = _front(f"persona {name} at {path}", text)
    body = body.strip()
    return _File(body, described if described is not None else description(body))


def _front(where: str, text: str) -> tuple[str, str | None]:
    """Split a persona's file into its text after any front matter and the `description` that front matter names.

    A front matter is a skill's: a `---` line first in the file, then `key: value` lines, then a `---` line. Only
    `description` is read, as plain text, YAML's way: on its line and any indented lines after it, joined by a space,
    quotes around it dropped, and cut to `DESCRIPTION_CHARS`. A blank line, or one that opens with `#`, is skipped.

    Returns:
        The text after the front matter, the whole file's when it has none, and its description, or None when it
        names none.

    Raises:
        PersonaError: (`BAD`) a front matter that never closes, or that `_description_lines` refuses, or whose
            description is empty; `where` names the file.
    """
    found = _FRONT_MATTER.match(text)
    if found is None:
        if _OPENS.match(text) is not None:
            raise PersonaError(BAD, f"{where} opens a front matter with `---` and never closes it")
        return text, None
    value = _description_lines(where, found.group(1))
    if value is None:
        return text[found.end() :], None
    words = " ".join(" ".join(value).split())
    quoted = _QUOTED.fullmatch(words)
    described = " ".join((quoted.group(2) if quoted is not None else words).split())
    if not described:
        raise PersonaError(BAD, f"{where} has an empty {DESCRIPTION_KEY}")
    return text[found.end() :], _cut(described)


def _description_lines(where: str, front: str) -> list[str] | None:
    """Return the lines of a front matter's `description`: its value on its key's line, then each indented line after.

    Returns:
        The lines, or None when the front matter names no description.

    Raises:
        PersonaError: (`BAD`) a line that is not a field, a key but `description`, or a description twice.
    """
    value: list[str] | None = None
    for line in front.splitlines():
        if not line.strip() or line.startswith("#"):
            continue
        if line[0] in " \t" and value is not None:
            value.append(line)
            continue
        field = _FIELD.fullmatch(line.rstrip())
        if field is None:
            raise PersonaError(BAD, f"{where} has a front matter line that is not `key: value`: {line.strip()!r}")
        if field.group(1) != DESCRIPTION_KEY:
            raise PersonaError(
                BAD,
                f"{where} has front matter key {field.group(1)!r}; only {DESCRIPTION_KEY!r} is read",
            )
        if value is not None:
            raise PersonaError(BAD, f"{where} names its {DESCRIPTION_KEY} twice")
        value = [field.group(2)]
    return value


def _where(config: Config) -> str:
    # Where a persona's file was looked for, and what to do, to end a refusal's sentence.
    yours = f" in {config.paths.personas} or" if config.paths.personas is not None else ""
    return f"{yours} among canopy's own: add it, or name one `canopy personas` lists"


def _flag(agent: Agent) -> str:
    # The `--agent` a command names `agent` with: none for the workers, whose override `canopy persona KEY` sets.
    return "" if agent == "worker" else f" --agent {agent}"
