"""What OpenCode offers canopy's agents (DESIGN §13), read from its own debug commands.

OpenCode merges the operator's config into canopy's definitions, so what an agent is offered is not what canopy's
definitions say alone. OpenCode prints the merged result: `opencode debug config` its resolved config, of which only the
MCP servers' names and `enabled` are read, since the rest may hold what its redaction misses; `opencode debug skill`
every skill it finds; and `opencode debug agent NAME` an agent's merged permission rules. From those this applies
OpenCode's own rules, read from its source at 1.19.3: the last rule whose permission pattern matches a tool's name
decides, and only a deny with the pattern `*` keeps the tool from the agent; a skill is offered unless the skill tool is
kept so, or the last `skill` rule matching its name denies it.

An MCP server's tools are not listed without connecting to it, so a server is judged by a name none of its tools has,
`<server>_` and a NUL: a rule that matches that name matches every tool of the server. A later rule that could match
only some of them, one naming the server's prefix or starting with a wildcard, makes its reach `some`.

What one run is offered is asked with the words its own command starts OpenCode with, `opencode run` and what follows
it swapped for each debug command: a debug command loads the plugins of the config where it starts, so it runs inside
whatever wraps the agent, a sandbox among them, and with the config directory the command points OpenCode at.
"""

from __future__ import annotations

import re
from collections.abc import Mapping
from pathlib import Path
from typing import TYPE_CHECKING, Literal

from pydantic import BaseModel, ConfigDict, StrictBool, StrictStr, TypeAdapter, ValidationError

from canopy.infra import procs
from canopy.runtime.agents import AgentOffer, Offerings, Reach, ServerOffer
from canopy.runtime.opencode.invocation import CONFIG_DIR_ENV

if TYPE_CHECKING:
    from collections.abc import Callable, Sequence

#: How long one of OpenCode's debug commands may take: each starts OpenCode, which reads its config and its plugins.
TIMEOUT_SECONDS = 120
#: OpenCode's tool that loads a skill, and the permission its rules name.
SKILL = "skill"
# The words that start OpenCode, as canopy's debug commands run it.
_OPENCODE = ("opencode",)
# An agent's name, as one path component could hold it.
_AGENT_RE = re.compile(r"[a-z][a-z0-9-]*")
# What OpenCode makes of a server's name in its tools' names: anything but a letter, a digit, `_`, or `-` is `_`.
_UNSAFE_RE = re.compile(r"[^a-zA-Z0-9_-]")
# The regex characters OpenCode escapes in a pattern before it reads `*` and `?` as wildcards.
_SPECIAL_RE = re.compile(r"[.+^${}()|\[\]\\]")


class _Rule(BaseModel):
    model_config = ConfigDict(extra="ignore", frozen=True, defer_build=True)

    permission: StrictStr
    pattern: StrictStr
    action: Literal["allow", "deny", "ask"]


class _Agent(BaseModel):
    model_config = ConfigDict(extra="ignore", frozen=True, defer_build=True)

    permission: tuple[_Rule, ...]


class _Server(BaseModel):
    model_config = ConfigDict(extra="ignore", frozen=True, defer_build=True)

    enabled: StrictBool = True


class _Config(BaseModel):
    model_config = ConfigDict(extra="ignore", frozen=True, defer_build=True)

    mcp: Mapping[str, _Server] = {}


class _Skill(BaseModel):
    model_config = ConfigDict(extra="ignore", frozen=True, defer_build=True)

    name: StrictStr


_SKILLS = TypeAdapter(tuple[_Skill, ...])


class _FailedError(Exception):
    """A debug command could not be run, failed, or printed what canopy cannot read."""


def offerings(runner: procs.Runner, *, cwd: Path, definitions_dir: Path, agents: Sequence[str]) -> Offerings:
    """Ask OpenCode what it offers each of `agents`, started in `cwd` with canopy's definitions in `definitions_dir`.

    Returns:
        The servers and skills OpenCode has, and what each agent is offered of them; with `error` set, and nothing
        else, when the servers or the skills could not be listed, and an agent's `error` set when its rules could not.
    """
    ask = _Ask(runner, _OPENCODE, cwd, {CONFIG_DIR_ENV: str(definitions_dir)})
    try:
        config, skills = ask.listed()
    except _FailedError as e:
        return Offerings(error=str(e))
    servers = tuple(config.mcp)
    return Offerings(
        servers=servers,
        disabled_servers=tuple(name for name, server in config.mcp.items() if not server.enabled),
        skills=skills,
        agents=tuple(_offer(ask, agent, servers=servers, skills=skills) for agent in agents),
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
    ask = _Ask(runner, words[: start + 1], cwd, env)
    try:
        config, skills = ask.listed()
    except _FailedError as e:
        return AgentOffer(agent, error=str(e))
    servers = tuple(name for name, server in config.mcp.items() if server.enabled)
    return _offer(ask, agent, servers=servers, skills=skills)


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


class _Ask:
    """OpenCode's debug commands, each started with `launcher`, the words that start OpenCode, in `cwd` with `env`."""

    def __init__(self, runner: procs.Runner, launcher: Sequence[str], cwd: Path, env: Mapping[str, str]) -> None:
        self.runner = runner
        self.launcher = launcher
        self.cwd = cwd
        self.env = env

    def listed(self) -> tuple[_Config, tuple[str, ...]]:
        """Return OpenCode's resolved config and every skill it finds, by name, sorted.

        Raises:
            _FailedError: either could not be read.
        """
        config = _read(self.run("debug", "config"), _Config.model_validate_json, "debug config")
        listed = _read(self.run("debug", SKILL), _SKILLS.validate_json, "debug skill")
        return config, tuple(sorted({s.name for s in listed}))

    def run(self, *args: str) -> str:
        """Return what the debug command `args` printed.

        Raises:
            _FailedError: it could not start, timed out, or failed.
        """
        command = f"opencode {' '.join(args)}"
        try:
            result = self.runner.run([*self.launcher, *args], cwd=self.cwd, env=self.env, timeout=TIMEOUT_SECONDS)
        except procs.CommandNotFoundError:
            raise _FailedError(f"{self.launcher[0]} is not on PATH") from None
        except procs.ProcError as e:
            raise _FailedError(f"`{command}` could not start: {e}") from None
        if result.timed_out:
            raise _FailedError(f"`{command}` took over {TIMEOUT_SECONDS} seconds")
        if not result.ok:
            # Not what it printed: an error about the config may quote a value of it, and an agent reads this.
            raise _FailedError(f"`{command}` exited {result.returncode}; run it to see why")
        return result.stdout


def _read[T](stdout: str, validate: Callable[[str], T], command: str) -> T:
    try:
        return validate(stdout)
    except ValidationError:
        # Not the error itself: it quotes what was printed, which for the config may hold a secret.
        raise _FailedError(f"`opencode {command}` printed what canopy cannot read") from None


def _offer(ask: _Ask, agent: str, *, servers: Sequence[str], skills: Sequence[str]) -> AgentOffer:
    try:
        printed = ask.run("debug", "agent", agent)
        rules = _read(printed, _Agent.model_validate_json, "debug agent").permission
    except _FailedError as e:
        return AgentOffer(agent, error=str(e))
    offered = () if _hidden(SKILL, rules) else tuple(s for s in skills if _action(SKILL, s, rules) != "deny")
    return AgentOffer(
        agent,
        servers=tuple(_server(name, rules) for name in servers),
        skills=offered,
        denied_skills=tuple(s for s in skills if s not in offered),
    )


# OpenCode's `Permission.disabled` for one tool: the last rule matching its name denies it with the pattern `*`.
def _hidden(tool: str, rules: Sequence[_Rule]) -> bool:
    deciding = next((r for r in reversed(rules) if matches(tool, r.permission)), None)
    return deciding is not None and _denies(deciding)


def _denies(rule: _Rule) -> bool:
    return rule.pattern == "*" and rule.action == "deny"


# OpenCode's `Permission.evaluate`: the last rule matching both, or `ask` when none does.
def _action(permission: str, pattern: str, rules: Sequence[_Rule]) -> str:
    for rule in reversed(rules):
        if matches(permission, rule.permission) and matches(pattern, rule.pattern):
            return rule.action
    return "ask"


def _server(name: str, rules: Sequence[_Rule]) -> ServerOffer:
    prefix = _UNSAFE_RE.sub("_", name) + "_"
    probe = prefix + "\x00"
    last = max((i for i, r in enumerate(rules) if matches(probe, r.permission)), default=-1)
    offered = last < 0 or not _denies(rules[last])
    exceptions = tuple(
        f"{'deny' if _denies(r) else 'offer'} {r.permission}"
        for r in rules[last + 1 :]
        if _may_match(prefix, r.permission) and _denies(r) == offered
    )
    reach: Reach = "some" if exceptions else "all" if offered else "none"
    return ServerOffer(name, reach, exceptions)


# Whether `pattern` could match a tool whose name starts `prefix`: its text before its first wildcard and the prefix
# agree as far as both go.
def _may_match(prefix: str, pattern: str) -> bool:
    literal = re.split(r"[*?]", pattern, maxsplit=1)[0]
    return literal.startswith(prefix) or prefix.startswith(literal)
