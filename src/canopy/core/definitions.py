"""The directory agent runs load canopy's agent definitions and skills from (DESIGN §13, D040, D044).

canopy snapshots its bundled `agents/` and `skills/` into `<state_dir>/runtime/<digest>/`, named for a digest of their
contents. A snapshot is written to a temporary directory and renamed into place, so a run never sees a partial one.
Command templates name it with `{definitions_dir}`, and OpenCode reads it through `OPENCODE_CONFIG_DIR`.

Six definitions are rendered from config. `canopy-worker-private`, `canopy-planner`, and `canopy-plan-triage` get the
tracker's MCP server and the tools of it they may call, its read tools (`render_private`, DESIGN §22, §25). Both workers
get the rule that lets them push a rebased branch with a lease when `trust.rebase` is set (`render_rebase`, DESIGN §8).
`canopy-reviewer` gets `runtime.review_temperature`, unless that sets none (`render_temperature`).
`canopy-overseer` gets the overseer's prompt, the operator's override if any, and the tracker's skill if canopy ships
one, as its body (`render_overseer`): the body is the agent's system prompt, which the provider caches across ticks,
where the state block, the tick's message, changes every tick (DESIGN §6). The digest covers the rendered text, so a
config or override change makes a new snapshot rather than changing one a run may be loading.

OpenCode merges a repository's definition of an agent into canopy's, and a repository that repeats one of canopy's
permission patterns can put its own rules after it (D044). So a run refuses to start in a directory whose OpenCode
config defines one of canopy's agents: `shadowing` finds those files. A private run also refuses one whose config names
the tracker server's tools (`naming_tools`): a rule merged after canopy's could reopen a write tool.
"""

from __future__ import annotations

import hashlib
import os
import shutil
import tempfile
import time
from collections.abc import Collection, Iterable, Mapping
from pathlib import Path
from typing import TYPE_CHECKING

from canopy.core import prompts, replies
from canopy.core.config import NO_TEMPERATURE
from canopy.core.vocab import ReplyMode, RunKind
from canopy.infra import logs, resources

if TYPE_CHECKING:
    from canopy.core.config import Config, TrackerTools

RUNTIME_DIR = "runtime"
_TMP_PREFIX = ".tmp-"
# A temporary directory this old belongs to a process that died mid-copy; a copy takes well under a second.
_STALE_TMP_SECONDS = 3600
WORKER = "canopy-worker"
PRIVATE_WORKER = "canopy-worker-private"
_PRIVATE_FILE = f"agents/{PRIVATE_WORKER}.md"
PLANNER = "canopy-planner"
#: The triage agent: the planner with nothing to edit (DESIGN §25, Triage before a plan).
PLAN_TRIAGE = "canopy-plan-triage"
# The definitions that may call only the tracker's read tools, rendered at their marked line.
_READ_ONLY_TRACKER_FILES = (_PRIVATE_FILE, f"agents/{PLANNER}.md", f"agents/{PLAN_TRIAGE}.md")
_WORKER_FILES = (f"agents/{WORKER}.md", _PRIVATE_FILE)
# The line of the shipped worker definitions the rules for a rebased branch's push are rendered at.
_REBASE_MARKER = "    # canopy: rebase rules\n"
# The one forced push `trust.rebase` allows, after the deny of every other: the prompts' own command, a lease on the
# branch's remote-tracking ref. A `--force` added to it is denied again; the rules after the marker still deny the rest.
_REBASE_RULES = (
    '    "git push --force-with-lease origin HEAD:refs/heads/*": allow\n',
    '    "git push *--force": deny\n',
    '    "git push *--force *": deny\n',
)
# The lines of the shipped worker definitions the denial of commenting is rendered at, with `trust.review_replies =
# "approve"` (DESIGN §29): in bash, `gh`'s commands that comment; among the MCP rules, the GitHub server's comment
# tools.
# A worker that still posts its ticket comments itself, for want of a tracker source that posts, keeps the issue ones.
_REPLY_BASH_MARKER = "    # canopy: reply rules\n"
_REPLY_TOOLS_MARKER = "  # canopy: reply tools\n"
_REPLY_BASH = ('    "gh pr comment*": deny\n',)
_REPLY_BASH_ISSUES = ('    "gh issue comment*": deny\n',)
_REPLY_TOOLS = ('  "*reply_to_pull_request_comment*": deny\n', '  "*add_comment_to_pending_review*": deny\n')
_REPLY_TOOLS_ISSUES = ('  "*add_issue_comment*": deny\n',)
# The line of the shipped private worker's and planner's definitions the tracker's rules are rendered at.
_TOOLS_MARKER = "  # canopy: tracker tools\n"
_REVIEWER_FILE = "agents/canopy-reviewer.md"
#: The line of the shipped reviewer definition its temperature is rendered at.
_TEMPERATURE_MARKER = "# canopy: temperature\n"
OVERSEER = "canopy-overseer"
_OVERSEER_FILE = f"agents/{OVERSEER}.md"
# The line of the shipped overseer definition its prompt replaces, with everything after it.
_PROMPT_MARKER = "<!-- canopy: overseer prompt -->\n"


class DefinitionsError(Exception):
    """The snapshot for this canopy exists but is not one canopy made, so no run may load it."""


def _files(root: Path) -> list[Path]:
    return sorted(p for p in root.rglob("*") if p.is_file())


def render_private(text: str, tools: TrackerTools | None, name: str = _PRIVATE_FILE) -> str:
    """Return definition `name`, the private worker's, the planner's, or the triage's, with the tracker's rules.

    Every tool of the server is denied by a wildcard and the allowed ones named after it: the last matching rule wins
    (D021). With no tools known, the marked line stays as it is; dispatch refuses a private run or a plan then
    (`no_read_tools`, DESIGN §22, §25).

    Raises:
        DefinitionsError: `text` has no marked line to render the tracker's tools at.
    """
    if _TOOLS_MARKER not in text:
        raise DefinitionsError(f"{name} has no line {_TOOLS_MARKER.strip()!r} to render the tracker's tools at")
    if tools is None:
        return text
    rules = [f'  "{tools.server}_*": deny\n', *(f'  "{tools.server}_{tool}": allow\n' for tool in tools.allowed)]
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


def render_temperature(text: str, name: str, temperature: float) -> str:
    """Return definition `name` with `temperature` at its marked line, or as it is if `temperature` sets none.

    Raises:
        DefinitionsError: `text` has no marked line to render the temperature at.
    """
    if _TEMPERATURE_MARKER not in text:
        raise DefinitionsError(f"{name} has no line {_TEMPERATURE_MARKER.strip()!r} to render the temperature at")
    if temperature == NO_TEMPERATURE:
        return text
    return text.replace(_TEMPERATURE_MARKER, f"{_TEMPERATURE_MARKER}temperature: {temperature}\n", 1)


def render_overseer(text: str, prompt: str, skill: str | None) -> str:
    """Return the overseer's definition with `prompt`, then `skill` if given, as its body from its marked line on.

    The body is the agent's system prompt, so it is cached across ticks with the tools (DESIGN §6, §13). `skill` is the
    tracker's skill, its own frontmatter left out: given here, the overseer need not load it with a tool call each tick.

    Raises:
        DefinitionsError: `text` has no marked line to render the prompt at.
    """
    head, marker, _ = text.partition(_PROMPT_MARKER)
    if not marker:
        raise DefinitionsError(f"{_OVERSEER_FILE} has no line {_PROMPT_MARKER.strip()!r} to render the prompt at")
    parts = [prompt] if skill is None else [prompt, skill]
    return head + "\n\n".join(part.strip("\n") for part in parts) + "\n"


def sources(config: Config | None = None) -> dict[str, bytes]:
    """Return the snapshot's files by relative path.

    They are the bundled agents and skills, with the workers', the reviewer's, and the overseer's definitions rendered
    from `config` when it is given.

    Raises:
        DefinitionsError: The overseer's prompt cannot be read.
    """
    found: dict[str, bytes] = {}
    for name, root in (("agents", resources.agents_dir()), ("skills", resources.skills_dir())):
        for path in _files(root):
            found[f"{name}/{path.relative_to(root).as_posix()}"] = path.read_bytes()
    for rel in _READ_ONLY_TRACKER_FILES:
        if config is not None and rel in found:
            found[rel] = render_private(found[rel].decode(), config.tracker.tools(), rel).encode()
    for rel in _WORKER_FILES:
        if config is not None and rel in found:
            text = render_rebase(found[rel].decode(), rel, rebase=config.trust.rebase)
            replied = replies.render(config, RunKind.RESUME, private=rel == _PRIVATE_FILE)
            approve = replied is not None and replied.mode is ReplyMode.APPROVE
            # A public worker without a ticket's draft posts its ticket comments itself; a private one posts none.
            ticket_comments = rel != _PRIVATE_FILE and not (replied is not None and replied.ticket_drafts)
            found[rel] = render_replies(text, rel, approve=approve, ticket_comments=ticket_comments).encode()
    if config is not None and _REVIEWER_FILE in found:
        text = found[_REVIEWER_FILE].decode()
        found[_REVIEWER_FILE] = render_temperature(text, _REVIEWER_FILE, config.runtime.review_temperature).encode()
    if config is not None and _OVERSEER_FILE in found:
        path = prompts.prompt_path(config, prompts.OVERSEER)
        try:
            prompt = path.read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError) as e:
            raise DefinitionsError(f"cannot read the overseer prompt {path}: {e}") from e
        skill = _tracker_skill(found, config.tracker.provider)
        text = found[_OVERSEER_FILE].decode()
        found[_OVERSEER_FILE] = render_overseer(text, prompt, skill).encode()
    return found


def _tracker_skill(found: Mapping[str, bytes], provider: str) -> str | None:
    """Return the shipped skill for `provider`, introduced by name, without the frontmatter that names it for loading.

    Returns:
        The skill's text, or None when canopy ships no skill for `provider`.
    """
    name = f"tracker-{provider}"
    data = found.get(f"skills/{name}/SKILL.md")
    if data is None:
        return None
    text = data.decode()
    if text.startswith("---\n"):
        _, _, text = text.removeprefix("---\n").partition("\n---\n")
    return f"The skill `{name}` follows, given here so that you need not load it.\n\n{text.strip()}"


def digest(config: Config | None = None) -> str:
    """Return a digest of the snapshot's files: their relative paths and contents."""
    return _digest(sources(config))


def _digest(files: Mapping[str, bytes]) -> str:
    h = hashlib.sha256()
    for rel, data in sorted(files.items()):
        h.update(f"{rel}\0{len(data)}\0".encode())
        h.update(data)
    return h.hexdigest()[:16]


def agent_names() -> list[str]:
    """Return the names of the agents canopy ships, as OpenCode names them: the file name without `.md`."""
    return sorted(p.stem for p in resources.agents_dir().glob("*.md"))


def ensure(state_dir: Path, config: Config | None = None) -> Path:
    """Return the snapshot for the installed canopy and `config`, creating it if missing.

    Safe to call from concurrent processes.

    canopy creates a snapshot readable only by the operator. One that is not was put there by something else, such as a
    checkout of a shared workspace (DESIGN §18), and could loosen canopy's agents, so it is refused, never loaded.

    Raises:
        DefinitionsError: the snapshot's directory exists and is not private to the operator, or the overseer's prompt
            cannot be read.
        OSError: the snapshot could not be written, and no other process put one in its place.
    """
    files = sources(config)
    runtime = state_dir / RUNTIME_DIR
    final = runtime / _digest(files)
    if final.is_dir() or final.is_symlink():
        return _checked(final)
    runtime.mkdir(parents=True, exist_ok=True)
    tmp = Path(tempfile.mkdtemp(prefix=_TMP_PREFIX, dir=runtime))
    try:
        for rel, data in files.items():
            path = tmp / rel
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(data)
        os.rename(tmp, final)  # noqa: PTH104  (os.rename, unlike Path.replace, never replaces a non-empty directory)
    except OSError:
        shutil.rmtree(tmp, ignore_errors=True)
        # Another process renamed its copy into place first; theirs has the same contents.
        if final.is_dir():
            return _checked(final)
        raise
    return final


def _checked(snapshot: Path) -> Path:
    if not logs.private_dir(snapshot):
        raise DefinitionsError(
            f"{snapshot} is not a snapshot canopy made: canopy creates it readable only by you, and this one is a "
            "symlink, someone else's, or open to others. Remove it; canopy recreates it."
        )
    return snapshot


def prune(state_dir: Path, keep: Path) -> list[Path]:
    """Remove snapshots other than `keep`, and temporary directories a dead process left. Returns what was removed.

    Call it only when no run is live: a run of an earlier canopy may still be loading its snapshot.

    Returns:
        The directories removed, in name order; empty when there is no runtime directory.
    """
    runtime = state_dir / RUNTIME_DIR
    if not runtime.is_dir():
        return []
    removed: list[Path] = []
    now = time.time()
    for entry in sorted(runtime.iterdir()):
        if entry == keep or not entry.is_dir():
            continue
        if entry.name.startswith(_TMP_PREFIX) and now - entry.stat().st_mtime < _STALE_TMP_SECONDS:
            continue
        shutil.rmtree(entry, ignore_errors=True)
        removed.append(entry)
    return removed


def shadowing(root: Path, names: Collection[str] | None = None) -> list[Path]:
    """Return the files in `root`'s OpenCode config that define, or may define, one of canopy's agents.

    That is an agent or mode file with a canopy agent's name under `.opencode/`, and an `opencode.json` or
    `opencode.jsonc` that mentions one. The JSON files are matched as text, not parsed: a comment naming an agent is a
    false positive, which only asks the operator to reword it.
    """
    names = agent_names() if names is None else names
    found: list[Path] = []
    config_dir = root / ".opencode"
    if config_dir.is_dir():
        for pattern in ("agent/**/*.md", "agents/**/*.md", "mode/*.md", "modes/*.md"):
            for path in sorted(config_dir.glob(pattern)):
                # OpenCode names an agent by its path below `agent/`, without `.md`.
                name = path.relative_to(config_dir).with_suffix("").as_posix().split("/", 1)[1]
                if name in names:
                    found.append(path)
    configs = (d / f for d in (root, config_dir) for f in ("opencode.json", "opencode.jsonc"))
    found.extend(p for p in configs if p.is_file() and any(n in p.read_text(errors="replace") for n in names))
    return found


def shadowing_message(found: Iterable[Path]) -> str:
    """Explain what `shadowing` found and what to do about it.

    Returns:
        A message for the operator naming every file in `found`.
    """
    files = ", ".join(str(p) for p in found)
    return (
        f"OpenCode config here defines one of canopy's agents ({files}). canopy's agents come from its own definitions "
        "directory (D040), and a definition here could loosen their permissions (D044). Remove it, or rename the agent."
    )


def naming_tools(root: Path, server: str) -> list[Path]:
    """Return the files in `root`'s OpenCode config that may name a tool of MCP server `server` (DESIGN §22, D044).

    OpenCode names a server's tools `<server>_<tool>`, and a `permission` or `tools` entry for one, merged after
    canopy's rules, could reopen a write tool a private worker is denied. Matched as text, like `shadowing`: a false
    positive only asks the operator to reword it.
    """
    needle = f"{server}_"
    config_dir = root / ".opencode"
    candidates: list[Path] = []
    if config_dir.is_dir():
        for pattern in ("agent/**/*.md", "agents/**/*.md", "mode/*.md", "modes/*.md"):
            candidates.extend(sorted(config_dir.glob(pattern)))
    candidates.extend(d / f for d in (root, config_dir) for f in ("opencode.json", "opencode.jsonc"))
    return [p for p in candidates if p.is_file() and needle in p.read_text(errors="replace")]


def naming_tools_message(server: str, found: Iterable[Path]) -> str:
    """Explain what `naming_tools` found and what to do about it.

    Returns:
        A message for the operator naming `server` and every file in `found`.
    """
    files = ", ".join(str(p) for p in found)
    return (
        f"OpenCode config here names tools of the tracker's MCP server {server!r} ({files}). A private ticket's worker "
        "may call only the tracker's read tools, and a rule here could reopen a write tool (DESIGN §22). Remove it, or "
        "work this ticket publicly."
    )
