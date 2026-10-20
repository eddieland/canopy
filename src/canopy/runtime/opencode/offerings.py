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
"""

from __future__ import annotations

import re
from collections.abc import Mapping
from typing import TYPE_CHECKING, Literal

from pydantic import BaseModel, ConfigDict, StrictBool, StrictStr, TypeAdapter, ValidationError

from canopy.infra import procs
from canopy.runtime.agents import AgentOffer, Offerings, Reach, ServerOffer
from canopy.runtime.opencode.invocation import CONFIG_DIR_ENV

if TYPE_CHECKING:
    from collections.abc import Callable, Sequence
    from pathlib import Path

#: How long one of OpenCode's debug commands may take: each starts OpenCode, which reads its config and its plugins.
TIMEOUT_SECONDS = 120
#: OpenCode's tool that loads a skill, and the permission its rules name.
SKILL = "skill"
# What OpenCode makes of a server's name in its tools' names: anything but a letter, a digit, `_`, or `-` is `_`.
_UNSAFE_RE = re.compile(r"[^a-zA-Z0-9_-]")
# The regex characters OpenCode escapes in a pattern before it reads `*` and `?` as wildcards.
_SPECIAL_RE = re.compile(r"[.+^${}()|\[\]\\]")
# The longest line of OpenCode's error output a failure quotes.
_MAX_ERROR = 200


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
    env = {CONFIG_DIR_ENV: str(definitions_dir)}
    try:
        config = _read(_run(runner, ("debug", "config"), cwd, env), _Config.model_validate_json, "debug config")
        listed = _read(_run(runner, ("debug", SKILL), cwd, env), _SKILLS.validate_json, "debug skill")
    except _FailedError as e:
        return Offerings(error=str(e))
    servers = tuple(config.mcp)
    skills = tuple(sorted({s.name for s in listed}))
    return Offerings(
        servers=servers,
        disabled_servers=tuple(name for name, server in config.mcp.items() if not server.enabled),
        skills=skills,
        agents=tuple(_offer(runner, agent, cwd=cwd, env=env, servers=servers, skills=skills) for agent in agents),
    )


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


def _run(runner: procs.Runner, args: Sequence[str], cwd: Path, env: Mapping[str, str]) -> str:
    command = f"opencode {' '.join(args)}"
    try:
        result = runner.run(["opencode", *args], cwd=cwd, env=env, timeout=TIMEOUT_SECONDS)
    except procs.CommandNotFoundError:
        raise _FailedError("opencode is not on PATH") from None
    except procs.ProcError as e:
        raise _FailedError(f"`{command}` could not start: {e}") from None
    if result.timed_out:
        raise _FailedError(f"`{command}` took over {TIMEOUT_SECONDS} seconds")
    if not result.ok:
        lines = [line.strip() for line in result.stderr.splitlines() if line.strip()]
        said = "".join(c for c in lines[-1] if c.isprintable())[:_MAX_ERROR] if lines else "no error output"
        raise _FailedError(f"`{command}` exited {result.returncode}: {said}")
    return result.stdout


def _read[T](stdout: str, validate: Callable[[str], T], command: str) -> T:
    try:
        return validate(stdout)
    except ValidationError:
        # Not the error itself: it quotes what was printed, which for the config may hold a secret.
        raise _FailedError(f"`opencode {command}` printed what canopy cannot read") from None


def _offer(
    runner: procs.Runner,
    agent: str,
    *,
    cwd: Path,
    env: Mapping[str, str],
    servers: Sequence[str],
    skills: Sequence[str],
) -> AgentOffer:
    try:
        printed = _run(runner, ("debug", "agent", agent), cwd, env)
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
