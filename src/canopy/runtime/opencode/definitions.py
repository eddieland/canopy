"""canopy's agent definitions in OpenCode's format (DESIGN §13): the bundled files, and what is rendered into them.

canopy ships its agents and skills as OpenCode reads them from a config directory, `agents/<name>.md` and
`skills/<name>/SKILL.md`, and its plugins beside them, `plugins/<name>.js`: the clock that tells a running agent the
minutes left (DESIGN §33). Each agent is a Markdown file whose frontmatter holds its permission rules. What canopy
decides from config, what each agent may do (`canopy.runtime.agents.Rules`), `render` writes at the lines the shipped
files mark for it:

- the tracker's MCP server and the tools of it the private worker and the planner may call: its read tools, and for
  the private worker alone, its tools that create a ticket and those that write to a PR (DESIGN §22, §25); and the
  overseer, the reviewer, and the chore, its reads only; off a GitHub tracker, the overseer's and the reviewer's denial
  of GitHub's issue reads, and both workers' and the planner's of GitHub's issue tools (DESIGN §13);
- the rule that lets both workers push a rebased branch with a lease, with `trust.rebase` (DESIGN §8);
- the denial of the tools that comment, when workers draft their replies (DESIGN §29);
- the artifact store's MCP server, denied whole to every agent, then for each agent config lets publish its tools
  allowed by name, and the store's skill, which every definition denies as shipped (DESIGN §38);
- the reviewer's and overseer's temperature, unless it sets none;
- the commands the operator allows an agent beyond its own bash rules (`runtime.allow_bash`, DESIGN §13), last of
  them;
- the overseer's prompt, then the tracker's skill if canopy ships one, as the overseer's body: the body is the agent's
  system prompt, which the provider caches across ticks, where the state block, the tick's message, changes every tick
  (DESIGN §6). With the skill there, the overseer's skill tool is denied, so that OpenCode sends neither it nor the
  list of skills.

Every shipped agent denies the operator's own skill, `canopy` (DESIGN §13), by name, whatever directory it is installed
in: it is for the operator's sessions, and an agent canopy runs has its own prompt to follow.

OpenCode applies the last matching permission rule (D021), so every catch-all `"*"` comes before its exceptions, a
rendered rule that allows goes after the deny it narrows, and a rendered deny goes after every allow it must beat: the
private worker's reply tools are marked below its tracker tools, which allow GitHub's reply tool by name.
"""

from __future__ import annotations

import fnmatch
import re
from typing import TYPE_CHECKING

from canopy.infra import resources
from canopy.runtime.agents import CHORE, OVERSEER, PLANNER, PRIVATE_WORKER, REVIEWER, WORKER, DefinitionsError

if TYPE_CHECKING:
    from collections.abc import Iterable, Mapping, Sequence
    from pathlib import Path

    from canopy.runtime.agents import McpTools, Publishing, Rules

#: The directories of a config directory OpenCode reads agents, skills, and plugins from.
AGENTS_SUBDIR = "agents"
SKILLS_SUBDIR = "skills"
PLUGINS_SUBDIR = "plugins"

#: A part of an OpenCode tool name: an MCP server's name or one of its tools', as OpenCode sanitizes them. They are
#: rendered into definitions, so nothing else may reach them.
TOOL_PART_RE = re.compile(r"[A-Za-z0-9][A-Za-z0-9_-]{0,99}")
#: OpenCode's rule for a skill's name: lowercase letters and digits in words joined by single hyphens, at most 64.
SKILL_NAME_RE = re.compile(r"[a-z0-9]+(?:-[a-z0-9]+)*")
MAX_SKILL_NAME = 64
#: A bash rule canopy renders from config: a command's name, a literal word, then words of plain characters and
#: OpenCode's wildcards, `*` for any run of characters and `?` for one, each after a single space. No character of it
#: ends a shell's word or command, or a YAML string in double quotes, and with no wildcard in its first word it matches
#: one command.
BASH_ALLOW_RE = re.compile(r"[A-Za-z0-9][A-Za-z0-9._+-]*(?: [A-Za-z0-9._,:=@%+/*?-]+)*")
#: The commands of OpenCode itself, which run an agent with rules of its own.
RUNTIME_COMMANDS = ("opencode",)


def _file(agent: str) -> str:
    return f"{AGENTS_SUBDIR}/{agent}.md"


_PRIVATE_FILE = _file(PRIVATE_WORKER)
_OVERSEER_FILE = _file(OVERSEER)
_REVIEWER_FILE = _file(REVIEWER)
_CHORE_FILE = _file(CHORE)
# The definitions that may call only the tracker's read tools, rendered at their marked line.
_READ_ONLY_TRACKER_FILES = (_PRIVATE_FILE, _file(PLANNER))
_WORKER_FILES = (_file(WORKER), _PRIVATE_FILE)
# The definitions that deny GitHub's issue tools off a GitHub tracker, at their marked line.
_GITHUB_ISSUE_FILES = (*_WORKER_FILES, _file(PLANNER))
# The line of the shipped worker definitions the rules for a rebased branch's push are rendered at.
_REBASE_MARKER = "    # canopy: rebase rules\n"
# The one forced push `trust.rebase` allows, after the deny of every other: the prompts' own command, a lease on the
# branch's remote-tracking ref. A `--force` added to it is denied again; the rules after the marker still deny the rest.
_REBASE_RULES = (
    '    "git push --force-with-lease origin HEAD:refs/heads/*": allow\n',
    '    "git push *--force": deny\n',
    '    "git push *--force *": deny\n',
)
# The lines of the shipped worker definitions the denial of commenting is rendered at, when workers draft their
# replies (DESIGN §29): in bash, `gh`'s commands that comment; among the MCP rules, the GitHub server's comment tools.
# A worker that still posts its ticket comments itself, for want of a tracker source that posts, keeps the issue ones.
_REPLY_BASH_MARKER = "    # canopy: reply rules\n"
_REPLY_TOOLS_MARKER = "  # canopy: reply tools\n"
_REPLY_BASH = ('    "gh pr comment*": deny\n',)
_REPLY_BASH_ISSUES = ('    "gh issue comment*": deny\n',)
_REPLY_TOOLS = ('  "*reply_to_pull_request_comment*": deny\n', '  "*add_comment_to_pending_review*": deny\n')
_REPLY_TOOLS_ISSUES = ('  "*add_issue_comment*": deny\n',)
# The line of the shipped private worker's and planner's definitions the tracker's rules are rendered at.
_TOOLS_MARKER = "  # canopy: tracker tools\n"
# The line of the shipped overseer's, reviewer's, and chore's definitions the tracker's rules are rendered at, above
# their denials of GitHub's tools by name and patterns, so that no allow rendered there reopens a write they close
# (D021).
_READS_MARKER = "  # canopy: tracker reads\n"
# The tracker provider whose tickets are GitHub's issues, on the same server as the PRs (the skill `tracker-github`).
_GITHUB = "github"
# The overseer's reads of GitHub, as its definition keeps them, allowed by name when the tracker is GitHub and so the
# server is the tracker's: the tracker's read tools there include the PR writes a private worker needs.
_OVERSEER_GITHUB_READS = (
    "get_me",
    "issue_read",
    "list_issues",
    "search_issues",
    "pull_request_read",
    "list_pull_requests",
    "search_pull_requests",
    "list_branches",
)
# GitHub's issue reads, which the overseer and the reviewer have no use for off a GitHub tracker. Rendered before the
# tracker's rules: a read of the tracker's that one matches, such as a `list_issues` of its own, is allowed again after
# it.
_GITHUB_ISSUE_READS = ("*issue_read*", "*list_issues*", "*search_issues*")
# GitHub's issue tools, which only the `tracker-github` skill names, so that the workers and the planner have no use
# for them off a GitHub tracker: the reads, and what filing or labelling an issue takes. Not its issue comment tools,
# which comment on a PR's conversation too.
_GITHUB_ISSUE_TOOLS = (
    *_GITHUB_ISSUE_READS,
    "*issue_write*",
    "*list_issue_types*",
    "*list_issue_fields*",
    "*get_label*",
)
# The line of the shipped workers' and planner's definitions the denial of GitHub's issue tools is rendered at.
_ISSUES_MARKER = "  # canopy: github issue tools\n"
# The line of every shipped definition the artifact store's server is rendered at (DESIGN §38): after the patterns
# that deny tools by their names, so that a tool allowed by name there is allowed, and before the rules for canopy's own
# servers, whose names no store's may share.
_ARTIFACT_TOOLS_MARKER = "  # canopy: artifact tools\n"
# The line of the shipped worker definition the allow of the store's skill is rendered at, after its deny.
_ARTIFACT_SKILL_MARKER = "    # canopy: artifact skill\n"
_ARTIFACT_SKILL = "canopy-artifacts"
# The agents canopy ships, each of which is rendered with the store's server.
_AGENTS = (WORKER, PRIVATE_WORKER, PLANNER, REVIEWER, OVERSEER, CHORE)
# The line of the shipped reviewer's and overseer's definitions their temperature is rendered at.
_TEMPERATURE_MARKER = "# canopy: temperature\n"
# The line of the shipped overseer definition its prompt replaces, with everything after it.
_PROMPT_MARKER = "<!-- canopy: overseer prompt -->\n"
# The line of the shipped overseer definition the denial of its skill tool is rendered at, when its body holds the
# tracker's skill: nothing is left for it to load, and a tool whose last rule denies `*` is not sent. The line ends its
# `skill` rules, after the denial of the operator's skill.
_SKILL_MARKER = "    # canopy: skill rule\n"
_SKILL_RULE = '    "*": deny\n'
# The line of a shipped definition the commands config allows it are rendered at: the last of its bash rules, so each
# allow wins (D021). Only a definition whose bash rules deny every command but those they name has it.
_BASH_ALLOWS_MARKER = "    # canopy: bash allows\n"


def agent_names() -> list[str]:
    """Return the names of the agents canopy ships, as OpenCode names them: the file name without `.md`."""
    return sorted(p.stem for p in resources.agents_dir().glob("*.md"))


def bundled() -> dict[str, bytes]:
    """Return the bundled agents, skills, and plugins as a config directory holds them, by relative path, unrendered."""
    found: dict[str, bytes] = {}
    for name, root in (
        (AGENTS_SUBDIR, resources.agents_dir()),
        (SKILLS_SUBDIR, resources.skills_dir()),
        (PLUGINS_SUBDIR, resources.plugins_dir()),
    ):
        for path in _files(root):
            found[f"{name}/{path.relative_to(root).as_posix()}"] = path.read_bytes()
    return found


def _files(root: Path) -> list[Path]:
    return sorted(p for p in root.rglob("*") if p.is_file())


def render(files: Mapping[str, bytes], rules: Rules) -> dict[str, bytes]:
    """Return `files`, a config directory's by relative path, with `rules` written into canopy's agents.

    Returns:
        A copy of `files` with each of canopy's definitions it holds rendered.

    Raises:
        DefinitionsError: A definition lacks a line it is rendered at.
    """
    found = dict(files)
    for rel in _READ_ONLY_TRACKER_FILES:
        if rel in found:
            found[rel] = render_private(found[rel].decode(), rules.tracker_tools, rel).encode()
    for rel in _WORKER_FILES:
        if rel in found:
            text = render_rebase(found[rel].decode(), rel, rebase=rules.rebase)
            drafts = rules.private_drafts if rel == _PRIVATE_FILE else rules.worker_drafts
            rendered = render_replies(text, rel, approve=drafts.approve, ticket_comments=drafts.ticket_comments)
            found[rel] = rendered.encode()
    for rel in _GITHUB_ISSUE_FILES:
        if rel in found:
            text = found[rel].decode()
            found[rel] = render_github_issues(text, rel, rules.tracker_tools, rules.tracker_provider).encode()
    _render_by_agent(found, rules)
    if _OVERSEER_FILE in found:
        skill = _tracker_skill(found, rules.tracker_provider)
        text = render_overseer_reads(found[_OVERSEER_FILE].decode(), rules.tracker_tools, rules.tracker_provider)
        found[_OVERSEER_FILE] = render_overseer(text, rules.overseer_prompt, skill).encode()
    if _REVIEWER_FILE in found:
        text = found[_REVIEWER_FILE].decode()
        found[_REVIEWER_FILE] = render_reviewer_reads(text, rules.tracker_tools, rules.tracker_provider).encode()
    if _CHORE_FILE in found:
        text = found[_CHORE_FILE].decode()
        found[_CHORE_FILE] = render_chore_reads(text, rules.tracker_tools, rules.tracker_provider).encode()
    return found


def _render_by_agent(found: dict[str, bytes], rules: Rules) -> None:
    """Render into `found`, in place, what `rules` gives agents by name: the store, bash allows, temperature."""
    for agent in _AGENTS:
        rel = _file(agent)
        if rel in found:
            found[rel] = render_artifacts(found[rel].decode(), agent, rules.artifacts).encode()
    for agent, allows in rules.bash_allows.items():
        rel = _file(agent)
        if rel in found:
            found[rel] = render_bash_allows(found[rel].decode(), rel, allows).encode()
    for agent, temperature in rules.temperatures.items():
        rel = _file(agent)
        if rel in found:
            found[rel] = render_temperature(found[rel].decode(), rel, temperature).encode()


def render_private(text: str, tools: McpTools | None, name: str = _PRIVATE_FILE) -> str:
    """Return definition `name`, the private worker's or the planner's, with the tracker's rules.

    Every tool of the server is denied by a wildcard and the allowed ones named after it: the last matching rule wins
    (D021). The private worker's also allows the server's PR tools, for its own PRs, and its create tools, whole, to
    file follow-ups (DESIGN §18). The planner writes nothing: it gets the read tools only, less any of those writes
    that config's read tools name. With no tools known, the marked line stays as it is; dispatch refuses a
    private run or a plan then (`no_read_tools`, DESIGN §22, §25).

    Raises:
        DefinitionsError: `text` has no marked line to render the tracker's tools at.
    """
    if _TOOLS_MARKER not in text:
        raise DefinitionsError(f"{name} has no line {_TOOLS_MARKER.strip()!r} to render the tracker's tools at")
    if tools is None:
        return text
    writes = (*tools.pr_writes, *tools.create)
    if name == _PRIVATE_FILE:
        allowed = list(dict.fromkeys((*tools.allowed, *writes)))
    else:
        allowed = [tool for tool in tools.allowed if tool not in writes]
    rules = [f'  "{tools.server}_*": deny\n', *(f'  "{tools.server}_{tool}": allow\n' for tool in allowed)]
    return text.replace(_TOOLS_MARKER, _TOOLS_MARKER + "".join(rules), 1)


def render_rebase(text: str, name: str, *, rebase: bool) -> str:
    """Return worker definition `name` with the rules for a rebased branch's push at its marked line, if `rebase`.

    Without `rebase`, the marked line stays as it is, and every forced push stays denied (TRUST_MODEL T1).

    Raises:
        DefinitionsError: `text` has no marked line to render the rules at.
    """
    if _REBASE_MARKER not in text:
        raise DefinitionsError(f"{name} has no line {_REBASE_MARKER.strip()!r} to render the rebase rules at")
    if not rebase:
        return text
    return text.replace(_REBASE_MARKER, _REBASE_MARKER + "".join(_REBASE_RULES), 1)


def render_replies(text: str, name: str, *, approve: bool, ticket_comments: bool) -> str:
    """Return worker definition `name` denying the GitHub server's comment tools and `gh`'s, if `approve`.

    Under `trust.review_replies = "approve"` a worker drafts every comment it would post (DESIGN §29), so the tools that
    comment are denied by name, as defense in depth: the prompt is what keeps it from posting. They are marked after
    the private worker's tracker tools, which allow GitHub's reply tool for a GitHub tracker. A worker that still
    posts its ticket comments itself (`ticket_comments`) keeps the issue-comment ones, which GitHub's issues share with
    a PR's top-level comments.

    Raises:
        DefinitionsError: `text` has no marked lines to render the rules at.
    """
    for marker in (_REPLY_BASH_MARKER, _REPLY_TOOLS_MARKER):
        if marker not in text:
            raise DefinitionsError(f"{name} has no line {marker.strip()!r} to render the reply rules at")
    if not approve:
        return text
    bash = (*_REPLY_BASH, *(() if ticket_comments else _REPLY_BASH_ISSUES))
    tools = (*_REPLY_TOOLS, *(() if ticket_comments else _REPLY_TOOLS_ISSUES))
    text = text.replace(_REPLY_BASH_MARKER, _REPLY_BASH_MARKER + "".join(bash), 1)
    return text.replace(_REPLY_TOOLS_MARKER, _REPLY_TOOLS_MARKER + "".join(tools), 1)


def render_github_issues(text: str, name: str, tools: McpTools | None, provider: str) -> str:
    """Return worker or planner definition `name` denying GitHub's issue tools, if the tracker is not GitHub.

    Only the `tracker-github` skill names them, and OpenCode sends no tool a rule denies whole, so each run's request is
    smaller by their schemas. The patterns match by tool name whatever the server, so one that matches a tool of the
    tracker's that canopy knows, such as a `list_issues` of its own, is left out, and GitHub's tool of that name stays:
    the worker's rules allow no tracker tool by name to win it back, and each pattern left out only keeps a tool. On a
    GitHub tracker, whose issues are the tickets, and with no tracker tools known, the marked line stays as it is.

    Raises:
        DefinitionsError: `text` has no marked line to render the denials at.
    """
    if _ISSUES_MARKER not in text:
        raise DefinitionsError(f"{name} has no line {_ISSUES_MARKER.strip()!r} to render GitHub's issue tools at")
    if tools is None or provider == _GITHUB:
        return text
    known = [f"{tools.server}_{tool}" for tool in (*tools.allowed, *tools.create, *tools.pr_writes)]
    denied = [p for p in _GITHUB_ISSUE_TOOLS if not any(fnmatch.fnmatchcase(tool, p) for tool in known)]
    return text.replace(_ISSUES_MARKER, _ISSUES_MARKER + "".join(_deny(pattern) for pattern in denied), 1)


def render_artifacts(text: str, agent: str, publishing: Publishing | None) -> str:
    """Return agent `agent`'s definition with the artifact store's rules at its marked lines (DESIGN §38).

    Every tool of the store's server is denied by a wildcard. For an agent that publishes, the tools it may call are
    allowed by exact name after it, the last rules that match them (D021), and so is the store's skill, which the
    definition denies as shipped. With no store configured, the marked lines stay as they are.

    Raises:
        DefinitionsError: `text` has no marked line to render the rules at.
    """
    name = _file(agent)
    if _ARTIFACT_TOOLS_MARKER not in text:
        marker = _ARTIFACT_TOOLS_MARKER.strip()
        raise DefinitionsError(f"{name} has no line {marker!r} to render the artifact store's rules at")
    if publishing is None:
        return text
    server = publishing.server
    publishes = agent in publishing.agents
    allows = [f'  "{server}_{tool}": allow\n' for tool in publishing.tools] if publishes else []
    text = text.replace(_ARTIFACT_TOOLS_MARKER, _ARTIFACT_TOOLS_MARKER + _deny(f"{server}_*") + "".join(allows), 1)
    if not publishes:
        return text
    if _ARTIFACT_SKILL_MARKER not in text:
        marker = _ARTIFACT_SKILL_MARKER.strip()
        raise DefinitionsError(f"{name} has no line {marker!r} to render the artifact store's skill at")
    return text.replace(_ARTIFACT_SKILL_MARKER, f'{_ARTIFACT_SKILL_MARKER}    "{_ARTIFACT_SKILL}": allow\n', 1)


def render_temperature(text: str, name: str, temperature: float | None) -> str:
    """Return definition `name` with `temperature` at its marked line, or as it is if `temperature` sets none.

    Raises:
        DefinitionsError: `text` has no marked line to render the temperature at.
    """
    if _TEMPERATURE_MARKER not in text:
        raise DefinitionsError(f"{name} has no line {_TEMPERATURE_MARKER.strip()!r} to render the temperature at")
    if temperature is None:
        return text
    return text.replace(_TEMPERATURE_MARKER, f"{_TEMPERATURE_MARKER}temperature: {temperature}\n", 1)


def render_bash_allows(text: str, name: str, allows: Sequence[str]) -> str:
    """Return definition `name` with each of `allows` allowed at its marked line, the last of its bash rules.

    The last matching rule wins (D021), so each allow beats the definition's denies, its catch-all or a worker's named
    ones, and no rule of canopy's comes after it to beat it in turn. The shipped definitions mark the line in the
    overseer's, the planner's, and the workers'; the agents with no shell deny bash whole, and mark none.

    Raises:
        DefinitionsError: `text` has no marked line to render the allows at, or an allow is not a rule canopy renders.
    """
    if _BASH_ALLOWS_MARKER not in text:
        raise DefinitionsError(f"{name} has no line {_BASH_ALLOWS_MARKER.strip()!r} to render bash allows at")
    for allow in allows:
        if not BASH_ALLOW_RE.fullmatch(allow):
            raise DefinitionsError(f"{name}: {allow!r} is not a bash rule canopy renders")
    rules = [f'    "{allow}": allow\n' for allow in allows]
    return text.replace(_BASH_ALLOWS_MARKER, _BASH_ALLOWS_MARKER + "".join(rules), 1)


def render_overseer_reads(text: str, tools: McpTools | None, provider: str) -> str:
    """Return the overseer's definition with the tracker's rules at its marked line: it may only read the tracker.

    As for the planner, every tool of the server is denied by a wildcard and the reads allowed after it (D021): the
    tracker's read tools, or on a GitHub tracker, whose server the PRs share, the overseer's own reads of GitHub, since
    the provider's read tools there hold the PR writes a private worker needs. Off a GitHub tracker, GitHub's issue
    reads are denied first. With no tools known, the marked line stays as it is, and the overseer keeps the tracker's
    tools and GitHub's issue reads: a pattern could take a read it needs.

    Raises:
        DefinitionsError: `text` has no marked line to render the tracker's rules at.
    """
    _require_reads_marker(text, _OVERSEER_FILE)
    if tools is None:
        return text
    github = provider == _GITHUB
    reads = _OVERSEER_GITHUB_READS if github else tools.allowed
    return _render_reads(text, tools.server, reads, issue_reads=not github)


def render_reviewer_reads(text: str, tools: McpTools | None, provider: str) -> str:
    """Return the reviewer's definition with the tracker's rules at its marked line: it may only read the tracker.

    It reads the ticket and writes nothing (DESIGN §21, TRUST_MODEL T6), so as for the overseer every tool of the
    tracker's server is denied by a wildcard and its read tools allowed after it, less the writes canopy knows of it,
    with GitHub's issue reads denied first. On a GitHub tracker the line stays as it is: the server is the one the
    reviewer reads the PR through, and its patterns govern it. With no tools known it stays as well, as the
    overseer's does.

    Raises:
        DefinitionsError: `text` has no marked line to render the tracker's rules at.
    """
    return _render_tracker_reads(text, tools, provider, _REVIEWER_FILE, issue_reads=True)


def render_chore_reads(text: str, tools: McpTools | None, provider: str) -> str:
    """Return the chore's definition with the tracker's rules at its marked line: it may only read the tracker.

    As for the reviewer, but GitHub's issue reads stay whatever the tracker: a chore's prompt is the operator's, and may
    ask for them (DESIGN §19). OpenCode sends no tool a rule denies whole, so a chore is sent none of the tracker's
    server's other tools.

    Raises:
        DefinitionsError: `text` has no marked line to render the tracker's rules at.
    """
    return _render_tracker_reads(text, tools, provider, _CHORE_FILE, issue_reads=False)


def render_overseer(text: str, prompt: str, skill: str | None) -> str:
    """Return the overseer's definition with `prompt`, then `skill` if given, as its body from its marked line on.

    The body is the agent's system prompt, so it is cached across ticks with the tools (DESIGN §6, §13). `skill` is the
    tracker's skill, its own frontmatter left out: given here, the overseer need not load it with a tool call each tick,
    so its skill tool is denied too. Without one, the prompt has it load the tracker's skill by name.

    Raises:
        DefinitionsError: `text` has no marked line to render the prompt at, or none for the skill rule.
    """
    head, marker, _ = text.partition(_PROMPT_MARKER)
    if not marker:
        raise DefinitionsError(f"{_OVERSEER_FILE} has no line {_PROMPT_MARKER.strip()!r} to render the prompt at")
    if _SKILL_MARKER not in head:
        raise DefinitionsError(f"{_OVERSEER_FILE} has no line {_SKILL_MARKER.strip()!r} to render the skill rule at")
    if skill is not None:
        head = head.replace(_SKILL_MARKER, _SKILL_MARKER + _SKILL_RULE, 1)
    parts = [prompt] if skill is None else [prompt, skill]
    return head + "\n\n".join(part.strip("\n") for part in parts) + "\n"


def _require_reads_marker(text: str, name: str) -> None:
    if _READS_MARKER not in text:
        marker = _READS_MARKER.strip()
        raise DefinitionsError(f"{name} has no line {marker!r} to render the tracker's reads at")


def _render_tracker_reads(text: str, tools: McpTools | None, provider: str, name: str, *, issue_reads: bool) -> str:
    """Render the tracker's read tools at definition `name`'s marked line, less the writes canopy knows of it.

    On a GitHub tracker, whose server the PRs share, and with no tools known, `text` is returned as it is.

    Returns:
        `text`, rendered or not.
    """
    _require_reads_marker(text, name)
    if tools is None or provider == _GITHUB:
        return text
    writes = (*tools.pr_writes, *tools.create)
    reads = [tool for tool in tools.allowed if tool not in writes]
    return _render_reads(text, tools.server, reads, issue_reads=issue_reads)


def _render_reads(text: str, server: str, reads: Iterable[str], *, issue_reads: bool) -> str:
    """Render `server` denied by a wildcard at the reads marker, then `reads` allowed by name.

    With `issue_reads`, GitHub's issue reads are denied first, so that an allow after them reopens a read of the
    tracker's they match.

    Returns:
        `text` with the rules after its marked line.
    """
    rules = [
        *(_deny(pattern) for pattern in (_GITHUB_ISSUE_READS if issue_reads else ())),
        _deny(f"{server}_*"),
        *(f'  "{server}_{tool}": allow\n' for tool in reads),
    ]
    return text.replace(_READS_MARKER, _READS_MARKER + "".join(rules), 1)


def _deny(pattern: str) -> str:
    return f'  "{pattern}": deny\n'


def _tracker_skill(found: Mapping[str, bytes], provider: str) -> str | None:
    """Return the shipped skill for `provider`, introduced by name, without the frontmatter that names it for loading.

    Returns:
        The skill's text, or None when canopy ships no skill for `provider`.
    """
    name = f"tracker-{provider}"
    data = found.get(f"{SKILLS_SUBDIR}/{name}/SKILL.md")
    if data is None:
        return None
    text = data.decode()
    if text.startswith("---\n"):
        _, _, text = text.removeprefix("---\n").partition("\n---\n")
    return f"The skill `{name}` follows, given here so that you need not load it.\n\n{text.strip()}"
