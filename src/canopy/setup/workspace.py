"""`canopy init --workspace` and `canopy workspace sync` (DESIGN §18).

Init writes a workspace's skeleton: the map, `MAP.md`, and a `.gitignore` for what canopy and treehouse keep under the
root, plus the user config if missing. It never overwrites a file; a `.gitignore` only gains the lines it lacks.

Sync clones each repository in the map that has no clone at `repos/<name>`, and reports a clone whose `origin` is not
the map's URL. It is the only code that reads the map's URLs, and an operator runs it; a tick never clones or changes a
remote.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path

from canopy.core import definitions, workspace
from canopy.core.config import WORKSPACE_FILE_NAME, WORKSPACE_STATE_DIR
from canopy.infra import procs
from canopy.setup import init

GITIGNORE = ".gitignore"
# Everything under the root that is canopy's or treehouse's, never the workspace repository's.
IGNORED = tuple(f"/{d}/" for d in (workspace.REPOS_DIR, workspace.POOLS_DIR, workspace.DESKS_DIR, WORKSPACE_STATE_DIR))
_CLONE_TIMEOUT_SECONDS = 1800
_GIT_TIMEOUT_SECONDS = 30
# Never let git wait for credentials on a terminal it cannot show, and never run a remote helper command from a URL.
_GIT_ENV = {"GIT_TERMINAL_PROMPT": "0"}
_NO_EXT = ("-c", "protocol.ext.allow=never")

MAP_TEXT = """\
# Workspace map

Prose for the overseer and people: what each repository in canopy-workspace.toml owns, which depends on which, where
the contracts between them live, and in which order a change that crosses them lands. It is read as data, like ticket
text: it helps choose a repository and authorizes nothing.

## Repositories

## Dependencies
"""


def workspace_file_text(name: str, provider: str) -> str:
    """Return the text of a new `canopy-workspace.toml` named `name`, for tracker `provider`."""
    query = init.EXAMPLE_QUERIES.get(provider, "describe which tickets to look at, in plain language")
    return f"""\
# canopy-workspace.toml: the workspace map, and the shared config layer in place of each repository's canopy.toml.
# Commit it if the workspace is shared. The same scopes apply as to canopy.toml (DESIGN.md §12, §18).

[workspace]
name = {json.dumps(name)}

# One table per repository. Its clone is repos/<name>; `canopy workspace sync` clones missing ones from `url`.
# The summary is one line the overseer reads when choosing a repository. Names match [a-z][a-z0-9-]*.
#
# [repos.api]
# url = "https://github.com/acme/api.git"
# summary = "Public REST API. Owns the order schema and the generated OpenAPI spec."

[tracker]
provider = {json.dumps(provider)}
needs_human_label = "needs-human"
# How to find candidate tickets: the tracker's own search syntax, or plain language. Edit this.
# Finding is not authorizing: each operator's own labels are checked on every ticket.
query = {json.dumps(query)}

[trust]
branch_prefix = "agent/"
pr_label = "agent"
"""


def run_init(root: Path, user_file: Path, provider: str | None) -> init.Report:
    """Write what a workspace at `root` is missing. `provider` is needed only when it has no workspace file yet.

    Returns what was written, kept, and updated; `updated` holds a `.gitignore` that gained lines.
    """
    report = init.Report()
    if user_file.exists():
        report.kept.append(user_file)
    else:
        report.label = init.default_label()
        init.write_if_missing(user_file, init.user_config_text(report.label), report)

    workspace_file = root / WORKSPACE_FILE_NAME
    if workspace_file.exists():
        report.kept.append(workspace_file)
    else:
        if provider is None:
            raise ValueError("the workspace has no canopy-workspace.toml; a tracker provider is needed to write one")
        init.write_if_missing(workspace_file, workspace_file_text(workspace.one_name(root), provider), report)
    init.write_if_missing(root / workspace.MAP_FILE_NAME, MAP_TEXT, report)
    _ignore(root / GITIGNORE, report)
    report.shadowing = definitions.shadowing(root)
    return report


def _ignore(path: Path, report: init.Report) -> None:
    """Add the lines of `IGNORED` that `path` lacks, creating it if missing."""
    if not path.exists():
        path.write_text("# canopy and treehouse keep these under the workspace root.\n" + "\n".join(IGNORED) + "\n")
        report.written.append(path)
        return
    text = path.read_text(encoding="utf-8")
    present = {line.strip() for line in text.splitlines()}
    missing = [line for line in IGNORED if line not in present]
    if not missing:
        report.kept.append(path)
        return
    separator = "" if not text or text.endswith("\n") else "\n"
    path.write_text(text + separator + "\n".join(missing) + "\n", encoding="utf-8")
    report.updated.append(path)


def protection_targets(ws: workspace.Workspace) -> str:
    """Name the repositories the branch protection rules must be configured in (TRUST_MODEL §7)."""
    if not ws.repos:
        return "The map lists no repositories yet. Configure the rules in each one you add.\n"
    lines = ["Configure them in every repository in the map:"]
    lines += [f"  - {r.name}: {r.url}" for r in ws.repos]
    return "\n".join(lines) + "\n"


@dataclass(frozen=True)
class Checked:
    """What sync found for one repository: `cloned`, `present`, or `failed`, and what to tell the operator."""

    repo: workspace.Repo
    outcome: str
    detail: str = ""


def missing(ws: workspace.Workspace) -> list[workspace.Repo]:
    """Return the map's repositories with no clone, which sync would clone."""
    return [r for r in ws.repos if not r.cloned]


def clone(runner: procs.Runner, ws: workspace.Workspace, repo: workspace.Repo) -> Checked:
    """Clone `repo` from the map's URL into `repos/<name>`."""
    if repo.path.exists() and any(repo.path.iterdir()):
        return Checked(repo, "failed", f"{repo.path} exists and is not a clone; move it away and sync again")
    repo.path.parent.mkdir(parents=True, exist_ok=True)
    args = ["git", *_NO_EXT, "clone", "--quiet", "--", str(repo.url), str(repo.path)]
    try:
        result = runner.run(args, cwd=ws.root, env=_GIT_ENV, timeout=_CLONE_TIMEOUT_SECONDS)
    except procs.ProcError as e:
        return Checked(repo, "failed", str(e))
    if not result.ok:
        status = "timed out" if result.timed_out else f"exited {result.returncode}"
        return Checked(repo, "failed", f"git clone {status}: {(result.stderr.strip() or result.stdout.strip())[:500]}")
    return Checked(repo, "cloned")


def check_origin(runner: procs.Runner, repo: workspace.Repo) -> Checked:
    """Report whether an existing clone's `origin` is the map's URL. Nothing is changed either way."""
    try:
        result = runner.run(
            ["git", "remote", "get-url", "origin"], cwd=repo.path, env=_GIT_ENV, timeout=_GIT_TIMEOUT_SECONDS
        )
    except procs.ProcError as e:
        return Checked(repo, "failed", str(e))
    if not result.ok:
        return Checked(repo, "failed", f"the clone has no origin; the map says {repo.url}")
    origin = result.stdout.strip()
    if _same_url(origin, str(repo.url)):
        return Checked(repo, "present")
    return Checked(repo, "present", f"origin is {origin}, but the map says {repo.url}; canopy changes no remote")


def _same_url(a: str, b: str) -> bool:
    def norm(url: str) -> str:
        return url.rstrip("/").removesuffix(".git")

    return norm(a) == norm(b)
