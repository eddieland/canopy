"""canopy's agent definitions in OpenCode's format (DESIGN §13): the bundled files, and what is rendered into them.

canopy ships its agents and skills as OpenCode reads them from a config directory, `agents/<name>.md` and
`skills/<name>/SKILL.md`. Each agent is a Markdown file whose frontmatter holds its permission rules. What canopy
decides from config, what each agent may do (`canopy.runtime.agents.Rules`), `render` writes at the lines the shipped
files mark for it:

- the tracker's MCP server and the tools of it the private worker, the planner, and the triage agent may call, its read
  tools (DESIGN §22, §25), and the overseer, its reads only; off a GitHub tracker, the overseer's denial of GitHub's
  issue reads (DESIGN §13);
- the rule that lets both workers push a rebased branch with a lease, with `trust.rebase` (DESIGN §8);
- the denial of the tools that comment, when workers draft their replies (DESIGN §29);
- the reviewer's, overseer's, and triage agent's temperature, unless it sets none;
- the overseer's prompt, then the tracker's skill if canopy ships one, as the overseer's body: the body is the agent's
  system prompt, which the provider caches across ticks, where the state block, the tick's message, changes every tick
  (DESIGN §6). With the skill there, the overseer's skill tool is denied, so that OpenCode sends neither it nor the
  list of skills.

OpenCode applies the last matching permission rule (D021), so every catch-all `"*"` comes before its exceptions, and
a rendered rule that allows goes after the deny it narrows.
"""

from __future__ import annotations

import re
from typing import TYPE_CHECKING

from canopy.infra import resources
from canopy.runtime.agents import OVERSEER, PLAN_TRIAGE, PLANNER, PRIVATE_WORKER, WORKER, DefinitionsError

if TYPE_CHECKING:
    from collections.abc import Mapping
    from pathlib import Path

    from canopy.runtime.agents import McpTools, Rules

#: The directories of a config directory OpenCode reads agents and skills from.
AGENTS_SUBDIR = "agents"
SKILLS_SUBDIR = "skills"

#: A part of an OpenCode tool name: an MCP server's name or one of its tools', as OpenCode sanitizes them. They are
#: rendered into definitions, so nothing else may reach them.
TOOL_PART_RE = re.compile(r"[A-Za-z0-9][A-Za-z0-9_-]{0,99}")
#: OpenCode's rule for a skill's name: lowercase letters and digits in words joined by single hyphens, at most 64.
SKILL_NAME_RE = re.compile(r"[a-z0-9]+(?:-[a-z0-9]+)*")
MAX_SKILL_NAME = 64


def _file(agent: str) -> str:
    return f"{AGENTS_SUBDIR}/{agent}.md"


_PRIVATE_FILE = _file(PRIVATE_WORKER)
_OVERSEER_FILE = _file(OVERSEER)
# The definitions that may call only the tracker's read tools, rendered at their marked line.
_READ_ONLY_TRACKER_FILES = (_PRIVATE_FILE, _file(PLANNER), _file(PLAN_TRIAGE))
_WORKER_FILES = (_file(WORKER), _PRIVATE_FILE)
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
# The line of the shipped overseer definition the tracker's rules are rendered at, above its denials of GitHub's tools
# by name, so that no allow rendered there reopens a write they close (D021).
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
# GitHub's issue reads, which the overseer has no use for off a GitHub tracker. Rendered before the tracker's rules: a
# read of the tracker's that one matches, such as a `list_issues` of its own, is allowed again after it.
_GITHUB_ISSUE_READS = ('  "*issue_read*": deny\n', '  "*list_issues*": deny\n', '  "*search_issues*": deny\n')
# The line of the shipped reviewer's, overseer's, and triage agent's definitions their temperature is rendered at.
_TEMPERATURE_MARKER = "# canopy: temperature\n"
# The line of the shipped overseer definition its prompt replaces, with everything after it.
_PROMPT_MARKER = "<!-- canopy: overseer prompt -->\n"
# The line of the shipped overseer definition the denial of its skill tool is rendered at, when its body holds the
# tracker's skill: nothing is left for it to load, and a tool denied whole is not sent.
_SKILL_MARKER = "  # canopy: skill rule\n"
_SKILL_RULE = "  skill: deny\n"


def agent_names() -> list[str]:
    """Return the names of the agents canopy ships, as OpenCode names them: the file name without `.md`."""
    return sorted(p.stem for p in resources.agents_dir().glob("*.md"))


def bundled() -> dict[str, bytes]:
    """Return the bundled agents and skills as a config directory holds them, by relative path, unrendered."""
    found: dict[str, bytes] = {}
    for name, root in ((AGENTS_SUBDIR, resources.agents_dir()), (SKILLS_SUBDIR, resources.skills_dir())):
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
    for agent, temperature in rules.temperatures.items():
        rel = _file(agent)
        if rel in found:
            found[rel] = render_temperature(found[rel].decode(), rel, temperature).encode()
    if _OVERSEER_FILE in found:
        skill = _tracker_skill(found, rules.tracker_provider)
        text = render_overseer_reads(found[_OVERSEER_FILE].decode(), rules.tracker_tools, rules.tracker_provider)
        found[_OVERSEER_FILE] = render_overseer(text, rules.overseer_prompt, skill).encode()
    return found


def render_private(text: str, tools: McpTools | None, name: str = _PRIVATE_FILE) -> str:
    """Return definition `name`, the private worker's, the planner's, or the triage's, with the tracker's rules.

    Every tool of the server is denied by a wildcard and the allowed ones named after it: the last matching rule wins
    (D021). The private worker's also allows the server's create tools, whole, to file follow-ups (DESIGN §18); the
    planner and the triage write nothing. With no tools known, the marked line stays as it is; dispatch refuses a
    private run or a plan then (`no_read_tools`, DESIGN §22, §25).

    Raises:
        DefinitionsError: `text` has no marked line to render the tracker's tools at.
    """
    if _TOOLS_MARKER not in text:
        raise DefinitionsError(f"{name} has no line {_TOOLS_MARKER.strip()!r} to render the tracker's tools at")
    if tools is None:
        return text
    allowed = (*tools.allowed, *tools.create) if name == _PRIVATE_FILE else tools.allowed
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
    comment are denied by name, as defense in depth: the prompt is what keeps it from posting. A worker that still
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
    if _READS_MARKER not in text:
        marker = _READS_MARKER.strip()
        raise DefinitionsError(f"{_OVERSEER_FILE} has no line {marker!r} to render the tracker's reads at")
    if tools is None:
        return text
    github = provider == _GITHUB
    reads = _OVERSEER_GITHUB_READS if github else tools.allowed
    rules = [
        *(() if github else _GITHUB_ISSUE_READS),
        f'  "{tools.server}_*": deny\n',
        *(f'  "{tools.server}_{tool}": allow\n' for tool in reads),
    ]
    return text.replace(_READS_MARKER, _READS_MARKER + "".join(rules), 1)


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
