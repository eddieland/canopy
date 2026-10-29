"""What OpenCode 2 offers canopy's agents (DESIGN §13), asked of a private server of its own.

OpenCode merges the operator's config into canopy's definitions, so what an agent is offered is not what canopy's
definitions say alone. OpenCode 2 has no command that prints the merge reliably: its debug commands attach to the shared
background service, and a private server answers before its plugins, canopy's definitions among them, have loaded, with
no agent and no skill. So canopy starts `opencode serve` itself, on a port of the system's choosing, with a password of
its own, and asks it through `opencode api --server`: `agent.list` until the agents have loaded, then `skill.list`,
and `config.get` for the MCP servers, of which only their names, `disabled`, and `codemode` are read, since the rest
may hold a secret. Then it stops the server.

From those this applies OpenCode's own rules, read from its source at 2.1.2: an agent's rules are `{action, resource,
effect}`, the last whose action and resource both match decides, and only a deny with the resource `*` keeps a tool from
the agent; a skill is offered unless the skill tool is kept so, or the last `skill` rule matching its id denies it.
OpenCode 2 lists no agent's tools, so its built-in tools are judged by the permissions they ask under (`_BUILTIN`).

An MCP server's tools are not listed without connecting to it, so a server is judged by a name none of its tools has,
`<server>_` and a NUL: a rule that matches that name matches every tool of the server. A later rule that could match
only some of them makes its reach `some`. A server in code mode, as every server is unless its config says otherwise,
is reached only through the `execute` tool, so an agent whose rules take `execute` away reaches none of it.

What one run is offered is asked with the words its own command starts OpenCode with, `opencode run` and what follows it
swapped for `serve`: the server loads the plugins of the config where it starts, so it runs inside whatever wraps the
agent, a sandbox among them, and with the config directory the command points OpenCode at.
"""

from __future__ import annotations

import json
import re
import secrets
import time
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING, Literal

from pydantic import BaseModel, ConfigDict, StrictBool, StrictStr, ValidationError

from canopy.infra import procs
from canopy.runtime.agents import AgentOffer, Offerings, Reach, ServerOffer, SkillFile
from canopy.runtime.opencode2.invocation import CONFIG_DIR_ENV

if TYPE_CHECKING:
    from collections.abc import Callable, Collection

#: How long the server may take to say where it listens, and its plugins to load once it has.
TIMEOUT_SECONDS = 120
LOADED_SECONDS = 30
#: How long one question of the server may take, and how long to wait between asking whether its plugins have loaded.
ASK_SECONDS = 30
POLL_SECONDS = 0.25
#: The variable a server takes its password from, and a client the password it sends.
PASSWORD_ENV = "OPENCODE_PASSWORD"  # noqa: S105 - a variable's name, not a password
#: OpenCode's tool that loads a skill, the permission its rules name, and the tool that runs code calling other tools.
SKILL = "skill"
EXECUTE = "execute"
# The words that start OpenCode, as canopy's own questions run it.
_OPENCODE = ("opencode",)
# Each built-in tool OpenCode 2.1.2 sends a primary agent, and the permission it asks under: the file tools that
# write share `edit`. `patch` stands in for `edit` on some models only, and `todowrite` is an experiment off by default.
_BUILTIN = {
    "shell": "shell",
    "read": "read",
    "edit": "edit",
    "write": "edit",
    "glob": "glob",
    "grep": "grep",
    "webfetch": "webfetch",
    "websearch": "websearch",
    SKILL: SKILL,
    "question": "question",
    "subagent": "subagent",
    EXECUTE: EXECUTE,
}
# Where the server says it listens.
_LISTENING_RE = re.compile(r"server listening on (http://127\.0\.0\.1:\d{1,5})\b")
# An agent's name, as one path component could hold it.
_AGENT_RE = re.compile(r"[a-z][a-z0-9-]*")
# What OpenCode makes of a server's name in its tools' names: anything but a letter, a digit, `_`, or `-` is `_`.
_UNSAFE_RE = re.compile(r"[^a-zA-Z0-9_-]")
# The regex characters OpenCode escapes in a pattern before it reads `*` and `?` as wildcards.
_SPECIAL_RE = re.compile(r"[.+^${}()|\[\]\\]")


class _Rule(BaseModel):
    model_config = ConfigDict(extra="ignore", frozen=True, defer_build=True)

    action: StrictStr
    resource: StrictStr
    effect: Literal["allow", "deny", "ask"]


class _Agent(BaseModel):
    model_config = ConfigDict(extra="ignore", frozen=True, defer_build=True)

    id: StrictStr
    permissions: tuple[_Rule, ...]


class _Agents(BaseModel):
    model_config = ConfigDict(extra="ignore", frozen=True, defer_build=True)

    data: tuple[_Agent, ...]


class _Skill(BaseModel):
    model_config = ConfigDict(extra="ignore", frozen=True, defer_build=True)

    # What its rules match; its `name` is what its file calls it, which the id is made from.
    id: StrictStr
    description: StrictStr | None = None
    path: StrictStr = ""
    content: StrictStr = ""


class _Skills(BaseModel):
    model_config = ConfigDict(extra="ignore", frozen=True, defer_build=True)

    data: tuple[_Skill, ...]


class _McpServer(BaseModel):
    model_config = ConfigDict(extra="ignore", frozen=True, defer_build=True)

    disabled: StrictBool = False
    codemode: StrictBool = True


class _Mcp(BaseModel):
    model_config = ConfigDict(extra="ignore", frozen=True, defer_build=True)

    servers: Mapping[str, _McpServer] = {}


class _Info(BaseModel):
    model_config = ConfigDict(extra="ignore", frozen=True, defer_build=True)

    mcp: _Mcp | None = None


class _Entry(BaseModel):
    model_config = ConfigDict(extra="ignore", frozen=True, defer_build=True)

    # A directory entry holds no config of its own; a document's, as OpenCode normalized it.
    info: _Info | None = None


@dataclass(frozen=True)
class _Loaded:
    """What the server has loaded: canopy's agents' rules, the skills, and the MCP servers, in config's order."""

    agents: Mapping[str, Sequence[_Rule]]
    #: Each skill as the server read it, sorted by id.
    skill_files: Sequence[SkillFile]
    servers: Mapping[str, _McpServer]

    @property
    def skills(self) -> tuple[str, ...]:
        """The skills' ids, sorted."""
        return tuple(f.name for f in self.skill_files)


class _FailedError(Exception):
    """The server could not be started, asked, or understood."""


def offerings(runner: procs.Runner, *, cwd: Path, definitions_dir: Path, agents: Sequence[str]) -> Offerings:
    """Ask OpenCode what it offers each of `agents`, started in `cwd` with canopy's definitions in `definitions_dir`.

    Returns:
        The servers and skills OpenCode has, and what each agent is offered of them; with `error` set, and nothing
        else, when they could not be listed, and an agent's `error` set when OpenCode has no such agent.
    """
    try:
        loaded = _load(runner, _OPENCODE, cwd, {CONFIG_DIR_ENV: str(definitions_dir)}, agents)
    except _FailedError as e:
        return Offerings(error=str(e))
    return Offerings(
        servers=tuple(loaded.servers),
        disabled_servers=tuple(name for name, server in loaded.servers.items() if server.disabled),
        skills=loaded.skills,
        skill_files=loaded.skill_files,
        agents=tuple(_offer(loaded, agent) for agent in agents),
    )


def offered(runner: procs.Runner, argv: Sequence[str], *, cwd: Path, env: Mapping[str, str]) -> AgentOffer:
    """Ask OpenCode what the agent `argv` runs is offered, started as `argv` starts it, in `cwd` with `env`.

    Returns:
        The servers its config turns on, each with the agent's reach, and the skills it is offered; with `error` set,
        and nothing else, when `argv` runs no `opencode run` with an agent, or OpenCode could not say.
    """
    words = tuple(argv)
    start = next((i for i, w in enumerate(words[:-1]) if Path(w).name == "opencode" and words[i + 1] == "run"), None)
    if start is None:
        return AgentOffer("", error="its command runs no `opencode run`")
    agent = _agent(words[start + 2 :])
    if agent is None:
        return AgentOffer("", error="its command names no agent")
    try:
        loaded = _load(runner, words[: start + 1], cwd, env, (agent,))
    except _FailedError as e:
        return AgentOffer(agent, error=str(e))
    on = {name: server for name, server in loaded.servers.items() if not server.disabled}
    return _offer(_Loaded(agents=loaded.agents, skill_files=loaded.skill_files, servers=on), agent)


def matches(text: str, pattern: str) -> bool:
    """Whether `text` matches one of OpenCode's permission patterns, as OpenCode's `Wildcard.match` decides it.

    `*` matches anything and `?` one character, and a pattern ending ` *` matches without the space too.

    Returns:
        True when the whole of `text` matches.
    """
    text, pattern = text.replace("\\", "/"), pattern.replace("\\", "/")
    escaped = _SPECIAL_RE.sub(lambda m: "\\" + m[0], pattern).replace("*", ".*").replace("?", ".")
    if escaped.endswith(" .*"):
        escaped = escaped[:-3] + "( .*)?"
    return re.fullmatch(escaped, text, re.DOTALL) is not None


# The agent `opencode run`'s arguments name, read word by word: the prompt is one word, so its text names none.
def _agent(args: Sequence[str]) -> str | None:
    for i, word in enumerate(args):
        if word == "--agent" or word.startswith("--agent="):
            name = word.removeprefix("--agent=") if "=" in word else (args[i + 1] if i + 1 < len(args) else "")
            return name if _AGENT_RE.fullmatch(name) else None
    return None


def _load(
    runner: procs.Runner,
    launcher: Sequence[str],
    cwd: Path,
    env: Mapping[str, str],
    agents: Collection[str],
) -> _Loaded:
    """Start a server with `launcher`, the words that start OpenCode, in `cwd` with `env`, and ask what it loaded.

    It waits for `agents`, the ones asked about, to load.

    Returns:
        canopy's agents' rules, the skills, and the MCP servers, as the server loaded them.

    Raises:
        _FailedError: The server could not be started, did not load in time, or said what canopy cannot read.
    """
    serve = _Serve(runner, launcher, cwd, {**env, PASSWORD_ENV: secrets.token_urlsafe(24)})
    return serve.ask(lambda client: _loaded(client, agents))


class _Serve:
    """`opencode serve`, started with `launcher` in `cwd` with `env`, for the questions of one function."""

    def __init__(self, runner: procs.Runner, launcher: Sequence[str], cwd: Path, env: Mapping[str, str]) -> None:
        self.runner = runner
        self.launcher = tuple(launcher)
        self.cwd = cwd
        self.env = env

    def ask[T](self, questions: Callable[[_Client], T]) -> T:
        """Start the server, put `questions` to it once it listens, and stop it.

        Returns:
            What `questions` returned.

        Raises:
            _FailedError: The server could not start, or exited or timed out before it listened, or `questions` did.
        """
        argv = [*self.launcher, "serve", "--hostname", "127.0.0.1", "--port", "0"]
        answers: list[T] = []

        def listening(line: str) -> None:
            found = _LISTENING_RE.search(line)
            if found is None:
                return
            answers.append(questions(_Client(self, found[1])))
            # Raised from here, it stops the server.
            raise _Answered

        try:
            result = self.runner.run(argv, cwd=self.cwd, env=self.env, timeout=TIMEOUT_SECONDS, on_line=listening)
        except _Answered:
            return answers[0]
        except procs.CommandNotFoundError:
            raise _FailedError(f"{self.launcher[0]} is not on PATH") from None
        except procs.ProcError as e:
            raise _FailedError(f"`opencode serve` could not start: {e}") from None
        if result.timed_out:
            raise _FailedError(f"`opencode serve` did not listen within {TIMEOUT_SECONDS} seconds")
        raise _FailedError(f"`opencode serve` exited {result.returncode}; run it to see why")


class _Answered(Exception):  # noqa: N818 - it is no error: it ends the server once the questions are answered.
    """The questions were answered, so the server may stop."""


class _Client:
    """`opencode api --server`, asking the server at `url` with the server's own launcher and environment."""

    def __init__(self, server: _Serve, url: str) -> None:
        self.server = server
        self.url = url

    def get(self, operation: str) -> str:
        """Return what operation `operation` answered.

        Raises:
            _FailedError: It could not start, timed out, or failed.
        """
        server = self.server
        argv = [*server.launcher, "api", "--server", self.url, operation]
        try:
            # Through a file, not a pipe: OpenCode exits having written only what a pipe's buffer holds, 64 KiB.
            result = server.runner.run(argv, cwd=server.cwd, env=server.env, timeout=ASK_SECONDS, stdout_to_file=True)
        except procs.ProcError as e:
            raise _FailedError(f"`opencode api {operation}` could not start: {e}") from None
        if result.timed_out:
            raise _FailedError(f"`opencode api {operation}` took over {ASK_SECONDS} seconds")
        if not result.ok:
            # Not what it printed: an error about the config may quote a value of it, and an agent reads this.
            raise _FailedError(f"`opencode api {operation}` exited {result.returncode}")
        return result.stdout


def _loaded(client: _Client, wanted: Collection[str]) -> _Loaded:
    """Ask the server for its agents once its plugins have loaded `wanted`, then its skills and its MCP servers.

    OpenCode lists its own agents before the plugins have loaded the definitions, canopy's among them, so it waits for
    the agents asked about, at most `LOADED_SECONDS`; one still missing then is one whose definition did not load.

    Returns:
        Each agent's rules by its name, the skills sorted by id, the first of an id kept, and the MCP servers in
        config's order.

    Raises:
        _FailedError: An answer could not be read, or no agent had loaded within `LOADED_SECONDS`.
    """
    deadline = time.monotonic() + LOADED_SECONDS
    while True:
        agents = _read(client.get("agent.list"), _Agents.model_validate_json, "agent.list").data
        if set(wanted) <= {agent.id for agent in agents}:
            break
        if time.monotonic() >= deadline:
            if not agents:
                raise _FailedError(f"`opencode serve` had loaded no agent after {LOADED_SECONDS} seconds")
            break
        time.sleep(POLL_SECONDS)
    skills = _read(client.get("skill.list"), _Skills.model_validate_json, "skill.list").data
    entries = _read(client.get("config.get"), _entries, "config.get")
    servers: dict[str, _McpServer] = {}
    for entry in entries:
        mcp = entry.info.mcp if entry.info is not None else None
        # A later definition of a server replaces an earlier one whole.
        servers.update(mcp.servers if mcp is not None else {})
    files = {s.id: SkillFile(s.id, s.description, s.path, s.content) for s in reversed(skills)}
    return _Loaded(
        agents={agent.id: agent.permissions for agent in agents},
        skill_files=tuple(files[name] for name in sorted(files)),
        servers=servers,
    )


def _entries(printed: str) -> tuple[_Entry, ...]:
    return tuple(_Entry.model_validate(entry) for entry in json.loads(printed))


def _read[T](printed: str, validate: Callable[[str], T], operation: str) -> T:
    try:
        return validate(printed)
    except (ValidationError, ValueError, TypeError):
        # Not the error itself: it quotes what was printed, which for the config may hold a secret.
        raise _FailedError(f"`opencode api {operation}` printed what canopy cannot read") from None


def _offer(loaded: _Loaded, agent: str) -> AgentOffer:
    rules = loaded.agents.get(agent)
    if rules is None:
        return AgentOffer(agent, error=f"OpenCode has no agent {agent}: its definition did not load")
    offered = () if _hidden(SKILL, rules) else tuple(s for s in loaded.skills if _action(SKILL, s, rules) != "deny")
    executes = not _hidden(EXECUTE, rules)
    return AgentOffer(
        agent,
        servers=tuple(_server(name, server, rules, executes=executes) for name, server in loaded.servers.items()),
        skills=offered,
        denied_skills=tuple(s for s in loaded.skills if s not in offered),
        tools=tuple(sorted(tool for tool, permission in _BUILTIN.items() if not _hidden(permission, rules))),
    )


# OpenCode's `whollyDisabled` for one tool: the last rule matching its permission denies it with the resource `*`.
def _hidden(permission: str, rules: Sequence[_Rule]) -> bool:
    deciding = next((r for r in reversed(rules) if matches(permission, r.action)), None)
    return deciding is not None and _denies(deciding)


def _denies(rule: _Rule) -> bool:
    return rule.resource == "*" and rule.effect == "deny"


# OpenCode's `Permission.evaluate`: the last rule matching both, or `ask` when none does.
def _action(permission: str, resource: str, rules: Sequence[_Rule]) -> str:
    for rule in reversed(rules):
        if matches(permission, rule.action) and matches(resource, rule.resource):
            return rule.effect
    return "ask"


def _server(name: str, server: _McpServer, rules: Sequence[_Rule], *, executes: bool) -> ServerOffer:
    if server.codemode and not executes:
        return ServerOffer(name, "none", (f"deny {EXECUTE}, which its tools are called through",))
    prefix = _UNSAFE_RE.sub("_", name) + "_"
    probe = prefix + "\x00"
    last = max((i for i, r in enumerate(rules) if matches(probe, r.action)), default=-1)
    offered = last < 0 or not _denies(rules[last])
    exceptions = tuple(
        f"{'deny' if _denies(r) else 'offer'} {r.action}"
        for r in rules[last + 1 :]
        if _may_match(prefix, r.action) and _denies(r) == offered
    )
    reach: Reach = "some" if exceptions else "all" if offered else "none"
    return ServerOffer(name, reach, exceptions)


# Whether `pattern` could match a tool whose name starts `prefix`: its text before its first wildcard and the prefix
# agree as far as both go.
def _may_match(prefix: str, pattern: str) -> bool:
    literal = re.split(r"[*?]", pattern, maxsplit=1)[0]
    return literal.startswith(prefix) or prefix.startswith(literal)
