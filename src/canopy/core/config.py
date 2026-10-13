"""Layered configuration: built-in defaults, then the workspace file, then the user's `config.toml`.

The shared file is the workspace's `canopy-workspace.toml`. No code repository's file is read (D016).

Every key has a scope (DESIGN §12). A shared key may be set in either file and the user file wins. A user-only key may
be set only in the user file; a workspace file that sets one is an error, because a workspace file may be committed to
a shared repository, and anyone who can push there controls it (TRUST_MODEL T7). Unknown keys are errors in both files.
The workspace file's `policy.*` values apply only when stricter than the built-in defaults.

The models below are the schema: each field carries its type, default, and scope, and policy fields say which
direction is stricter. `load` enforces scopes and the tighten rule per file, merges, then lets pydantic validate
(D026).
"""

from __future__ import annotations

import ipaddress
import os
import re
import shlex
import tomllib
from dataclasses import dataclass
from enum import Enum
from pathlib import Path
from typing import TYPE_CHECKING, Annotated, Literal, get_args
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from pydantic import (
    AfterValidator,
    BaseModel,
    ConfigDict,
    Field,
    StrictBool,
    StrictInt,
    StrictStr,
    ValidationError,
    model_validator,
)

from canopy.core import contract

if TYPE_CHECKING:
    from pydantic.fields import FieldInfo

WORKSPACE_FILE_NAME = "canopy-workspace.toml"
# A workspace's state is always here, under its root: each workspace has its own journal and locks (DESIGN §18).
WORKSPACE_STATE_DIR = ".canopy"
# Tables of the workspace file that are its map, not config. `canopy.core.workspace` reads them.
WORKSPACE_MAP_TABLES = ("workspace", "repos")
# Keys earlier canopy read, and what to do with one left in a file. Each is an error that says so, not "unknown key".
REMOVED_KEYS = {
    "paths.state_dir": f"delete it; state is always in the workspace's {WORKSPACE_STATE_DIR}/ (D016)",
}
PROMPT = "{prompt}"
# Replaced with the snapshot of canopy's agent definitions and skills (D040).
DEFINITIONS_DIR = "{definitions_dir}"
DEFINITIONS_ENV_PREFIX = f"env OPENCODE_CONFIG_DIR={DEFINITIONS_DIR} "
# Replaced with the run's session title: a worker's `<KEY> <kind>: <ticket title>`, `tick <id>`, `chore:<name>`, or
# `review <PR URL>` (DESIGN §13). Optional in every template.
TITLE = "{title}"
_PLACEHOLDER_RE = re.compile(r"\{prompt\}|\{definitions_dir\}|\{title\}")
# A repository name is a directory name, a treehouse leaf, and a `--repo` argument (DESIGN §18).
REPO_NAME_RE = re.compile(r"[a-z][a-z0-9-]*")
# A chore's name appears in file paths and on the command line (DESIGN §19).
CHORE_NAME_RE = re.compile(r"[a-z][a-z0-9-]*")
MIN_CHORE_EVERY_MINUTES = 15


class ConfigError(Exception):
    """The configuration cannot be used. The message names the file and key."""


class Scope(Enum):
    """Where a key may be set: either file, or only the user file."""

    SHARED = "shared"
    USER = "user-only"


class Tighten(Enum):
    """For the workspace file's policy: which direction is stricter than the default."""

    LOWER = "lower"
    HIGHER = "higher"
    # For a field typed as a Literal of choices listed from loosest to strictest: a later choice is stricter.
    LATER = "later"


def _non_blank(value: str) -> str:
    if not value.strip():
        raise ValueError("must not be empty")
    return value


# One or more plain ref components, each followed by "/". Branch names reach git's argv, so none may start with "-" or
# hold anything git treats specially ("..", "@{", a leading "."). The workspace file can set this key (TRUST_MODEL T7).
BRANCH_PREFIX_RE = re.compile(r"(?:[A-Za-z0-9][A-Za-z0-9_-]*/)+")


def _branch_prefix(value: str) -> str:
    if not BRANCH_PREFIX_RE.fullmatch(value):
        raise ValueError("must be non-empty, end in '/', and use only letters, digits, '_', '-' and '/'")
    return value


MAX_COMMENT_MARK = 80


def _comment_mark(value: str) -> str:
    # What workers start or end every comment with; a comment that carries it is never feedback or an instruction
    # (DESIGN §8, D069). Empty means not used. Prompts quote it in backticks, and one without a letter or digit (`-`,
    # `>`) would match ordinary list items and quotes.
    if value and (
        len(value) > MAX_COMMENT_MARK
        or value != value.strip()
        or not value.isprintable()
        or "`" in value
        or not any(c.isalnum() for c in value)
    ):
        raise ValueError(
            f"must be empty, or one line of at most {MAX_COMMENT_MARK} characters with a letter or digit, no backtick, "
            "and no surrounding spaces"
        )
    return value


MAX_REVIEWER = 100
# The `trust.trusted_reviewers` entry for canopy's own reviewer (DESIGN §21). A login cannot hold a colon, so no account
# can be read as it; canopy's reviewer posts as the operator, so the operator's login cannot stand for it.
CANOPY_REVIEWER = "canopy:review"


def _reviewer(value: str) -> str:
    # A VCS host account whose review feedback a worker may address unasked (DESIGN §7). Prompts quote it in backticks.
    if value != CANOPY_REVIEWER and (
        not value
        or len(value) > MAX_REVIEWER
        or not value.isprintable()
        or any(c.isspace() or c in "`:" for c in value)
    ):
        raise ValueError(
            f"must be a login of at most {MAX_REVIEWER} characters with no spaces, colon, or backtick, or "
            f"{CANOPY_REVIEWER!r} for canopy's own reviewer"
        )
    return value


def command_words(template: str) -> list[str]:
    """Split a command template into words, as `render_command` does. It must mention `{prompt}` exactly once."""
    words = shlex.split(template)
    if not words:
        raise ValueError("must not be empty")
    # Exactly once: the prompt must land in one argument, not be copied into several (D023).
    if sum(w.count("{prompt}") for w in words) != 1:
        raise ValueError("must contain {prompt} exactly once")
    return words


def _command_template(value: str) -> str:
    command_words(value)
    return value


def _agent_template(value: str) -> str:
    # Without the placeholder, OpenCode would look for canopy's agent in the repository and, not finding it, run its
    # default agent, which allows everything (D040). The old default templates lack it, so say what to write instead.
    if DEFINITIONS_DIR not in value:
        raise ValueError(
            f"must contain {DEFINITIONS_DIR}, the directory canopy's agent definitions are in (D040). "
            f"For OpenCode, write: '{DEFINITIONS_ENV_PREFIX}{value}'"
        )
    return value


def notify_words(template: str) -> list[str]:
    """Split `notify.cmd` into argv with shell word rules. No shell runs (D023). Empty means no notify command.

    Its input arrives on stdin, so a `{prompt}` would reach the command as a literal word; it is refused.
    """
    if "{prompt}" in template:
        raise ValueError("must not contain {prompt}; the notification arrives on stdin")
    return shlex.split(template)


def _notify_command(value: str) -> str:
    notify_words(value)
    return value


def setup_words(template: str) -> list[str]:
    """Split `runtime.setup_cmd` into argv with shell word rules. No shell runs (D023). Empty means no setup.

    It gets no placeholders: it runs in a slot, as its working directory, and reads its repository from the
    environment (DESIGN §8). A placeholder would reach the command as a literal word, so one is refused.
    """
    if PROMPT in template or DEFINITIONS_DIR in template:
        raise ValueError(f"must not contain {PROMPT} or {DEFINITIONS_DIR}; setup runs no agent")
    return shlex.split(template)


def _setup_command(value: str) -> str:
    setup_words(value)
    return value


def _user_path(value: Path) -> Path:
    # A relative path would resolve against the working directory, which is the workspace: its files would stand in
    # for the operator's prompts (TRUST_MODEL T7). `Path("")` is `.`, so an empty value is refused here too.
    expanded = value.expanduser()
    if not expanded.is_absolute():
        raise ValueError("must be an absolute path or start with ~")
    return expanded


# bool is an int subclass; Strict* types reject `max_workers = true` and quoted numbers.
NonBlank = Annotated[StrictStr, AfterValidator(_non_blank)]
Count = Annotated[StrictInt, Field(ge=0)]
Minutes = Annotated[StrictInt, Field(ge=1)]
CommandTemplate = Annotated[StrictStr, AfterValidator(_command_template)]
AgentTemplate = Annotated[StrictStr, AfterValidator(_command_template), AfterValidator(_agent_template)]
NotifyCommand = Annotated[StrictStr, AfterValidator(_notify_command)]
SetupCommand = Annotated[StrictStr, AfterValidator(_setup_command)]
UserPath = Annotated[Path, AfterValidator(_user_path)]


class Section(BaseModel):
    """Base for config tables: unknown keys are errors, values are frozen, defaults are validated."""

    # validate_default: defaults go through the same validators as file values, so `~/.canopy` is expanded.
    model_config = ConfigDict(extra="forbid", frozen=True, validate_default=True)


# A part of an OpenCode tool name: an MCP server's name or one of its tools', as OpenCode sanitizes them. They are
# rendered into the private worker's definition (DESIGN §22), so nothing else may reach it.
TOOL_PART_RE = re.compile(r"[A-Za-z0-9][A-Za-z0-9_-]{0,99}")


def _tool_part(value: str) -> str:
    if not TOOL_PART_RE.fullmatch(value):
        raise ValueError(f"{value!r} must match {TOOL_PART_RE.pattern}")
    return value


def _server_name(value: str) -> str:
    # Empty means the provider's default.
    return _tool_part(value) if value else value


ToolPart = Annotated[str, AfterValidator(_tool_part)]

TICKET_KEY = "{key}"
MAX_TICKET_URL = 500


def _ticket_url(value: str) -> str:
    # Empty means unset. The web UI puts it in an `href`: only a plain https:// URL, with the key's place exactly once.
    rest = value.replace(TICKET_KEY, "", 1)
    if value and (
        not contract.plain_url(value, MAX_TICKET_URL) or TICKET_KEY not in value or "{" in rest or "}" in rest
    ):
        raise ValueError(
            f"must be empty, or a plain https:// URL of at most {MAX_TICKET_URL} characters with {TICKET_KEY} exactly "
            "once and no other braces"
        )
    return value


@dataclass(frozen=True)
class TrackerTools:
    """The tracker's MCP server, and the tools of it a private worker may call: every other one is denied."""

    server: str
    allowed: tuple[str, ...]


# Each shipped provider's usual MCP server, as an operator's OpenCode config usually names it, and the tools of it a
# private worker needs: reading tickets, and for GitHub, whose server is also the one PRs go through, the PR tools. None
# of them writes to an issue (DESIGN §22). Named from the servers' tool lists (Atlassian's Rovo MCP server v2, GitHub's
# MCP server v2.0.1); a name wrong here fails closed. Atlassian's server lists only its primary tools unless its URL
# asks for `?tools=all`, and runs the rest through `execute*` tools that read or write by argument; those are denied.
DEFAULT_TRACKER_TOOLS: dict[str, TrackerTools] = {
    "jira": TrackerTools(
        "atlassian",
        (
            "atlassianUserInfo",
            "getAccessibleAtlassianResources",
            "getJiraIssue",
            "getJiraIssueTypeMetaWithFields",
            "listJiraIssueChangelogs",
            "listJiraIssueComments",
            "listJiraIssueLinkTypes",
            "listJiraIssueRemoteIssueLinks",
            "listJiraProjectIssueTypesMetadata",
            "listJiraProjects",
            "lookupJiraAccountId",
            "searchJiraIssuesUsingJql",
        ),
    ),
    "github": TrackerTools(
        "github",
        (
            "get_me",
            "issue_read",
            "list_issues",
            "search_issues",
            "list_issue_types",
            "get_label",
            "pull_request_read",
            "list_pull_requests",
            "search_pull_requests",
            "create_pull_request",
            "update_pull_request",
            "add_reply_to_pull_request_comment",
            "actions_get",
            "actions_list",
            "get_job_logs",
        ),
    ),
}


class Tracker(Section):
    """The `[tracker]` table."""

    provider: Annotated[NonBlank, Scope.SHARED]
    query: Annotated[NonBlank, Scope.SHARED]
    needs_human_label: Annotated[NonBlank, Scope.SHARED] = "needs-human"
    # A ticket's page in the tracker, with {key} where its key goes: the web UI links each ticket there (DESIGN §17).
    # Empty means no link. Shared: the tracker's address is the team's, and a link runs nothing.
    ticket_url: Annotated[StrictStr, Scope.SHARED, AfterValidator(_ticket_url)] = ""
    labels: Annotated[tuple[NonBlank, ...], Scope.USER, Field(min_length=1)]
    # Work only the tickets the operator started (DESIGN §22): the overseer runs no query and reads a ticket only while
    # it has no branch, and a dispatch of any other ticket is refused. User-only: it defines this operator's queue.
    private_only: Annotated[StrictBool, Scope.USER] = False
    # The tracker's MCP server, as the operator's OpenCode config names it, and the tools of it a private worker may
    # call (DESIGN §22). Empty and unset mean the provider's defaults. User-only: they decide what a private worker can
    # write, which a shared workspace file must not (TRUST_MODEL T7).
    mcp_server: Annotated[StrictStr, Scope.USER, AfterValidator(_server_name)] = ""
    read_tools: Annotated[tuple[ToolPart, ...] | None, Scope.USER] = None

    def tools(self) -> TrackerTools | None:
        """The server and tools a private worker gets, or None if neither config nor a default names any."""
        default = DEFAULT_TRACKER_TOOLS.get(self.provider)
        server = self.mcp_server or (default.server if default is not None else "")
        allowed = self.read_tools if self.read_tools is not None else (default.allowed if default is not None else ())
        if not server or not allowed:
            return None
        return TrackerTools(server, tuple(allowed))


class Policy(Section):
    """The `[policy]` table: attempt limits and cooldowns. A limit counts every run of that kind a ticket has had."""

    max_implement_attempts: Annotated[Count, Scope.SHARED, Tighten.LOWER] = 2
    max_fix_ci_attempts: Annotated[Count, Scope.SHARED, Tighten.LOWER] = 2
    fix_ci_cooldown_minutes: Annotated[Count, Scope.SHARED, Tighten.HIGHER] = 30
    max_resume_attempts: Annotated[Count, Scope.SHARED, Tighten.LOWER] = 3
    # Split runs per ticket (DESIGN §18). A split creates tickets in the tracker, so one try is the default.
    max_split_attempts: Annotated[Count, Scope.SHARED, Tighten.LOWER] = 1
    # Review runs per PR, whatever they ended as (DESIGN §21).
    max_reviews_per_pr: Annotated[Count, Scope.SHARED, Tighten.LOWER] = 3
    # Whether the overseer may stack a ticket on its blocker's open PR (DESIGN §10). Prompt policy, not a guard.
    stacking: Annotated[Literal["auto", "never"], Scope.SHARED, Tighten.LATER] = "auto"


class Trust(Section):
    """The `[trust]` table."""

    branch_prefix: Annotated[StrictStr, Scope.SHARED, AfterValidator(_branch_prefix)] = "agent/"
    pr_label: Annotated[NonBlank, Scope.SHARED] = "agent"
    authorized_repliers: Annotated[tuple[NonBlank, ...], Scope.USER] = ()
    # Whose review feedback a worker may address without the operator's go-ahead (DESIGN §7, D089): VCS host logins,
    # and `canopy:review` for canopy's own reviewer. Anyone else's waits for an operator message. User-only: a
    # workspace file that listed its own bots would decide what steers the operator's workers.
    trusted_reviewers: Annotated[tuple[Annotated[StrictStr, AfterValidator(_reviewer)], ...], Scope.USER] = ()
    # What every worker comment starts and ends with, when set (DESIGN §8, D069). They only take authority away, from
    # the comments that carry them; user-only, so a shared file cannot pick marks that silence people's comments.
    comment_prefix: Annotated[StrictStr, Scope.USER, AfterValidator(_comment_mark)] = "CANOPY:"
    comment_suffix: Annotated[StrictStr, Scope.USER, AfterValidator(_comment_mark)] = ""

    @model_validator(mode="after")
    def _one_comment_mark(self) -> Trust:
        # With neither, a worker's comment reads as the operator's, and its PR replies as new review feedback.
        if not self.comment_prefix and not self.comment_suffix:
            raise ValueError("set trust.comment_prefix, trust.comment_suffix, or both: workers mark their comments")
        return self


# OpenCode's rule for a skill's name: lowercase letters and digits in words joined by single hyphens, at most 64.
SKILL_NAME_RE = re.compile(r"[a-z0-9]+(?:-[a-z0-9]+)*")
MAX_SKILL_NAME = 64


def _skill_name(value: str) -> str:
    # Empty means unset. The name is quoted in worker prompts, so it is checked as OpenCode would (DESIGN §8).
    if value and (len(value) > MAX_SKILL_NAME or not SKILL_NAME_RE.fullmatch(value)):
        raise ValueError(
            f"must be empty, or a skill name of at most {MAX_SKILL_NAME} lowercase letters and digits in words joined "
            "by single hyphens"
        )
    return value


def _repo_name(value: str) -> str:
    if not REPO_NAME_RE.fullmatch(value):
        raise ValueError(f"repository name {value!r} must match {REPO_NAME_RE.pattern}")
    return value


RepoName = Annotated[str, AfterValidator(_repo_name)]


class Capacity(Section):
    """The `[capacity]` table."""

    max_workers: Annotated[Count, Scope.USER] = 2
    # Chore runs at once, apart from max_workers; 0 turns every chore off (DESIGN §19).
    max_chores: Annotated[Count, Scope.USER] = 1
    # Review runs at once, within max_workers, and started in any 24 hours; 0 turns reviews off (DESIGN §21).
    max_reviews: Annotated[Count, Scope.USER] = 1
    max_reviews_per_day: Annotated[Count, Scope.USER] = 20
    # Slots in each repository's pool, in a workspace: `canopy workspace sync` creates and removes slots to match, and
    # no lease grows a pool past it. None leaves the pools unmanaged, as treehouse's own `max_trees` has them. Names in
    # `repo_slots` need not be in this workspace's map: one user file serves every workspace (DESIGN §18).
    slots_per_repo: Annotated[Count | None, Scope.USER] = None
    repo_slots: Annotated[dict[RepoName, Count], Scope.USER] = {}

    def slots_for(self, repo: str) -> int | None:
        """The slots declared for repository `repo`'s pool, or None if its pool is not managed."""
        return self.repo_slots.get(repo, self.slots_per_repo)


class Runtime(Section):
    """The `[runtime]` table: agent command templates and timeouts."""

    overseer_cmd: Annotated[AgentTemplate, Scope.USER] = (
        "env OPENCODE_CONFIG_DIR={definitions_dir} opencode run --agent canopy-overseer --format json "
        "--title={title} {prompt}"
    )
    worker_cmd: Annotated[AgentTemplate, Scope.USER] = (
        "env OPENCODE_CONFIG_DIR={definitions_dir} opencode run --agent canopy-worker --format json "
        "--title={title} {prompt}"
    )
    # A private ticket's worker: its own agent, which cannot write to the tracker (DESIGN §22). Shares the worker's
    # timeout.
    private_worker_cmd: Annotated[AgentTemplate, Scope.USER] = (
        "env OPENCODE_CONFIG_DIR={definitions_dir} opencode run --agent canopy-worker-private --format json "
        "--title={title} {prompt}"
    )
    # The splitter is its own agent, with no edit or shell tools (DESIGN §18); it shares the worker's timeout.
    split_cmd: Annotated[AgentTemplate, Scope.USER] = (
        "env OPENCODE_CONFIG_DIR={definitions_dir} opencode run --agent canopy-splitter --format json "
        "--title={title} {prompt}"
    )
    # A chore's default command; a chore that runs the operator's own tools sets its own (DESIGN §19).
    chore_cmd: Annotated[AgentTemplate, Scope.USER] = (
        "env OPENCODE_CONFIG_DIR={definitions_dir} opencode run --agent canopy-chore --format json "
        "--title={title} {prompt}"
    )
    # The reviewer; pointing it at a different model from the worker's is recommended (DESIGN §21).
    review_cmd: Annotated[AgentTemplate, Scope.USER] = (
        "env OPENCODE_CONFIG_DIR={definitions_dir} opencode run --agent canopy-reviewer --format json "
        "--title={title} {prompt}"
    )
    review_timeout_minutes: Annotated[Minutes, Scope.USER] = 20
    overseer_timeout_minutes: Annotated[Minutes, Scope.USER] = 15
    worker_timeout_minutes: Annotated[Minutes, Scope.USER] = 45
    # The skill workers open PRs with, instead of the GitHub MCP; empty means the MCP (DESIGN §8). User-only: it
    # chooses what workers are told to do, which a shared workspace file must not (TRUST_MODEL T7).
    pr_skill: Annotated[StrictStr, Scope.USER, AfterValidator(_skill_name)] = ""
    # Run in each slot of a worker run once its branch is checked out, before the worker starts; a failure or timeout
    # ends the run `crashed` (DESIGN §8). Empty means none. It runs the branch's code on this machine.
    setup_cmd: Annotated[SetupCommand, Scope.USER] = ""
    setup_timeout_minutes: Annotated[Minutes, Scope.USER] = 30


class Review(Section):
    """The `[review]` table: which PRs get an adversarial review (DESIGN §21). Every key is user-only."""

    # The loop's own PRs, before a human is asked to review them.
    agent_prs: Annotated[StrictBool, Scope.USER] = False
    # PRs the operator names in the VCS host's own search syntax. It authorizes, unlike tracker.query.
    query: Annotated[StrictStr, Scope.USER] = ""
    # Plain language for the reviewer: which changes it may call low impact. Without it, none.
    low_impact: Annotated[StrictStr, Scope.USER] = ""


class Loop(Section):
    """The `[loop]` table: how `canopy loop` paces ticks. Every tick runs the overseer, so this sets its spend."""

    interval_minutes: Annotated[Minutes, Scope.USER] = 15
    # The longest wait after idle ticks in a row (DESIGN §6, Idle pacing). Not above the interval, idle pacing is off.
    idle_max_minutes: Annotated[Minutes, Scope.USER] = 120

    @model_validator(mode="after")
    def _cap_not_below_interval(self) -> Loop:
        # Only when set: the default under a longer interval turns idle pacing off, as setting it to the interval does.
        if "idle_max_minutes" in self.model_fields_set and self.idle_max_minutes < self.interval_minutes:
            raise ValueError(
                f"loop.idle_max_minutes ({self.idle_max_minutes}) must be at least loop.interval_minutes "
                f"({self.interval_minutes}); set them equal to turn idle pacing off"
            )
        return self


# Host names that mean loopback. The web UI's Host and Origin checks accept these and the bind address (DESIGN §22).
LOOPBACK_NAMES = frozenset({"localhost", "127.0.0.1", "::1"})
# A path prefix the web UI is served under through a proxy: `/canopy`, `/a/b`. Restricted to characters that need no
# escaping in a URL or an HTML attribute, since the server writes it into index.html's <base href>.
_BASE_PATH_RE = re.compile(r"(/[A-Za-z0-9._~-]+)*")


def listen_address(value: str) -> str:
    """Refuse an address a listener may not bind (TRUST_MODEL T8): only loopback or a private address, as an IP.

    Never a wildcard (`0.0.0.0`, `::`), a public address, or a host name other than `localhost`, whose address canopy
    would not know.
    """
    if value in LOOPBACK_NAMES:
        return value
    try:
        address = ipaddress.ip_address(value)
    except ValueError:
        raise ValueError(f"{value!r} must be a loopback or private IP address, or localhost") from None
    if address.is_unspecified or address.is_multicast:
        raise ValueError(f"{value!r} is a wildcard or multicast address; bind loopback or one private address")
    if not (address.is_loopback or address.is_private):
        raise ValueError(f"{value!r} is a public address; bind loopback or a private address")
    return value


def check_base_path(value: str) -> str:
    """Refuse a path prefix that is not empty or like `/canopy`, with no trailing slash."""
    if not _BASE_PATH_RE.fullmatch(value) or any(part in {".", ".."} for part in value.split("/")):
        raise ValueError(f"base path {value!r} must be empty or like /canopy, with no trailing slash")
    return value


class Serve(Section):
    """The `[serve]` table: the web UI `canopy loop` serves (DESIGN §22).

    Every key is user-only: it opens a listener on the operator's machine (TRUST_MODEL T8).
    """

    enabled: Annotated[StrictBool, Scope.USER] = True
    bind: Annotated[StrictStr, Scope.USER, AfterValidator(listen_address)] = "127.0.0.1"
    port: Annotated[StrictInt, Scope.USER, Field(ge=1, le=65535)] = 8765
    base_path: Annotated[StrictStr, Scope.USER, AfterValidator(check_base_path)] = ""


class Paths(Section):
    """The `[paths]` table."""

    # No static default: `load` supplies `prompts/` next to the user file, which depends on XDG_CONFIG_HOME.
    prompt_overrides: Annotated[UserPath, Scope.USER]
    # A personal `.worktreeinclude`, passed on every `treehouse get` as `--include-file`. treehouse then seeds the
    # ignored files it selects from the primary clone in place of the committed manifest's (DESIGN §9).
    worktree_include: Annotated[UserPath | None, Scope.USER] = None


# A sink's name is a table name and appears in `canopy notify test` and the journal (DESIGN §20).
SINK_NAME_RE = re.compile(r"[a-z][a-z0-9-]*")
MAX_SINKS = 5
# The event groups a sink may take. `attention` is the attention list's diff; the others are point events.
EVENT_GROUPS = ("attention", "loop", "runs", "chores", "reviews")
EventGroup = Literal["attention", "loop", "runs", "chores", "reviews"]
# The sink `notify.cmd` stands for.
DEFAULT_SINK = "default"
MIN_DIGEST_MINUTES = 60


def _sink_name(value: str) -> str:
    if not SINK_NAME_RE.fullmatch(value):
        raise ValueError(f"sink name {value!r} must match {SINK_NAME_RE.pattern}")
    return value


def _sink_command(value: str) -> str:
    if not notify_words(value):
        raise ValueError("must not be empty")
    return value


class Sink(Section):
    """One `[notify.sinks.<name>]` table: a command that reads one message on stdin (DESIGN §20)."""

    cmd: Annotated[StrictStr, AfterValidator(_notify_command), AfterValidator(_sink_command)]
    format: Literal["json", "text"] = "json"
    events: tuple[EventGroup, ...] = ("attention", "loop")
    digest_every_minutes: Annotated[StrictInt, Field(ge=MIN_DIGEST_MINUTES)] | None = None


SinkName = Annotated[str, AfterValidator(_sink_name)]


class Notify(Section):
    """The `[notify]` table."""

    # Receives the attention diff on stdin. Split into argv like the runtime templates, with no `{prompt}`. Shorthand
    # for a sink named `default` that takes the attention list as text (DESIGN §20).
    cmd: Annotated[NotifyCommand, Scope.USER] = ""
    sinks: Annotated[dict[SinkName, Sink], Scope.USER] = {}

    @model_validator(mode="after")
    def _one_default(self) -> Notify:
        if self.cmd and DEFAULT_SINK in self.sinks:
            raise ValueError(f"set notify.cmd or [notify.sinks.{DEFAULT_SINK}], not both: notify.cmd is that sink")
        if len(self.all_sinks()) > MAX_SINKS:
            raise ValueError(f"at most {MAX_SINKS} sinks, counting notify.cmd: each can hold the tick lock 60 seconds")
        return self

    def all_sinks(self) -> dict[str, Sink]:
        """Every sink by name, in name order, `notify.cmd` included as `default`."""
        found = dict(self.sinks)
        if self.cmd:
            found[DEFAULT_SINK] = Sink(cmd=self.cmd, format="text", events=("attention",))
        return dict(sorted(found.items()))

    def takes(self, group: str) -> bool:
        """Whether any sink takes `group`: events of a group no sink takes are not recorded."""
        return any(group in sink.events for sink in self.all_sinks().values())


CHORE_DAYS = ("mon", "tue", "wed", "thu", "fri", "sat", "sun")  # by `datetime.weekday()`
ChoreDay = Literal["mon", "tue", "wed", "thu", "fri", "sat", "sun"]
_HOURS_RE = re.compile(r"([01]\d|2[0-3]):([0-5]\d)-([01]\d|2[0-4]):([0-5]\d)")
_DAY_MINUTES = 24 * 60


def chore_hours(value: str) -> tuple[int, int]:
    """Read a chore's `hours`, `HH:MM-HH:MM`, as minutes after midnight: the start, and the end, which may be 24:00.

    Raises:
        ValueError: not in that shape, not a time of day, or not ending after it starts.
    """
    found = _HOURS_RE.fullmatch(value)
    start, end = (int(found[1]) * 60 + int(found[2]), int(found[3]) * 60 + int(found[4])) if found else (0, 0)
    if found is None or end > _DAY_MINUTES:
        raise ValueError(f"hours {value!r} must be two times of day, 00:00 to 24:00, like 08:00-18:00")
    if end <= start:
        raise ValueError(f"hours {value!r} must end after they start, on the same day")
    return start, end


def _chore_hours(value: str) -> str:
    chore_hours(value)
    return value


def _days(value: tuple[str, ...]) -> tuple[str, ...]:
    if len(set(value)) != len(value):
        raise ValueError("days must not repeat")
    return value


def _time_zone(value: str) -> str:
    try:
        ZoneInfo(value)
    except (ZoneInfoNotFoundError, ValueError):
        raise ValueError(f"time zone {value!r} is not an IANA time zone this machine knows") from None
    return value


def _chore_name(value: str) -> str:
    if not CHORE_NAME_RE.fullmatch(value):
        raise ValueError(f"chore name {value!r} must match {CHORE_NAME_RE.pattern}")
    return value


class Chore(Section):
    """One `[chores.<name>]` table: recurring work the operator defines and the overseer delegates (DESIGN §19)."""

    prompt: UserPath
    # Its own template need not name canopy's definitions: a chore that runs the operator's tools has its own agent.
    cmd: CommandTemplate | None = None
    every_minutes: Annotated[StrictInt, Field(ge=MIN_CHORE_EVERY_MINUTES)]
    when: StrictStr = ""
    # When a run may start, checked in code: the days of the week, empty for every day; the hours of each, as
    # `HH:MM-HH:MM`; and the zone they are in, an IANA name, by default this machine's local time.
    days: Annotated[tuple[ChoreDay, ...], AfterValidator(_days)] = ()
    hours: Annotated[StrictStr, AfterValidator(_chore_hours)] | None = None
    timezone: Annotated[StrictStr, AfterValidator(_time_zone)] | None = None
    timeout_minutes: Minutes = 15
    cwd: UserPath | None = None
    # The workspaces it runs in, by name; empty means every workspace whose loop reads this file.
    workspaces: tuple[NonBlank, ...] = ()


ChoreName = Annotated[str, AfterValidator(_chore_name)]


class Config(Section):
    """The merged, validated configuration."""

    tracker: Tracker
    policy: Policy
    trust: Trust
    capacity: Capacity
    runtime: Runtime
    loop: Loop
    review: Review
    paths: Paths
    notify: Notify
    serve: Serve
    # Tables of tables, keyed by name; user-only as a whole (TABLE_SECTIONS).
    chores: Annotated[dict[ChoreName, Chore], Scope.USER] = {}

    @property
    def reviews_on(self) -> bool:
        """Whether reviews run at all: `max_reviews` above 0 and something to review (DESIGN §21)."""
        return self.capacity.max_reviews > 0 and (self.review.agent_prs or bool(self.review.query.strip()))


SECTIONS: dict[str, type[Section]] = {
    "tracker": Tracker,
    "policy": Policy,
    "trust": Trust,
    "capacity": Capacity,
    "runtime": Runtime,
    "loop": Loop,
    "review": Review,
    "paths": Paths,
    "notify": Notify,
    "serve": Serve,
}


@dataclass(frozen=True)
class KeySpec:
    """One config key's scope and tighten direction, read from its field's metadata."""

    name: str
    scope: Scope
    tighten: Tighten | None
    field: FieldInfo


def _spec(name: str, field: FieldInfo) -> KeySpec:
    scopes = [m for m in field.metadata if isinstance(m, Scope)]
    tightens = [m for m in field.metadata if isinstance(m, Tighten)]
    if len(scopes) != 1:
        raise TypeError(f"{name} must declare exactly one Scope")
    return KeySpec(name, scopes[0], tightens[0] if tightens else None, field)


SPECS: dict[str, KeySpec] = {
    f"{section}.{key}": _spec(f"{section}.{key}", field)
    for section, model in SECTIONS.items()
    for key, field in model.model_fields.items()
}
# Sections whose tables are named by the operator, such as `[chores.build-health]`: one key each, the whole section.
TABLE_SECTIONS = ("chores",)
SPECS.update({name: _spec(name, Config.model_fields[name]) for name in TABLE_SECTIONS})


def user_config_dir() -> Path:
    """`$XDG_CONFIG_HOME/canopy`, or `~/.config/canopy` when XDG_CONFIG_HOME is unset or empty."""
    base = os.environ.get("XDG_CONFIG_HOME") or str(Path.home() / ".config")
    return Path(base).expanduser() / "canopy"


def user_config_path() -> Path:
    """Return the user config file's path."""
    return user_config_dir() / "config.toml"


def load(root: Path, user_file: Path | None = None) -> Config:
    """Read and validate the layered config for the workspace at `root`: its workspace file, then the user file.

    No code repository's file is read (D016). The workspace file's map tables are `canopy.core.workspace`'s to read.
    """
    user_file = user_file or user_config_path()
    shared_file = root / WORKSPACE_FILE_NAME
    shared: dict[str, object] = _read(shared_file, skip=WORKSPACE_MAP_TABLES) if shared_file.exists() else {}
    for name in shared:
        if SPECS[name].scope is Scope.USER:
            raise ConfigError(
                f"{shared_file}: {name} is user-only and cannot be set in the workspace file; set it in {user_file}"
            )
    if not user_file.exists():
        raise ConfigError(f"no user config at {user_file}; run `canopy init`")
    user_values = _read(user_file)

    merged, origin = _merge(((shared_file, shared), (user_file, user_values)), shared_file)
    # Unset or empty: `prompts/` next to the user file.
    if merged["paths"].get("prompt_overrides", "") == "":
        merged["paths"]["prompt_overrides"] = str(user_file.parent / "prompts")

    try:
        return Config.model_validate(merged)
    except ValidationError as e:
        raise ConfigError(_describe(e, origin, shared_file, user_file)) from e


def _merge(
    layers: tuple[tuple[Path, dict[str, object]], ...], shared_file: Path
) -> tuple[dict[str, dict[str, object]], dict[str, Path]]:
    """Merge the files' keys in order, later files winning. Returns the merged sections and each key's file."""
    merged: dict[str, dict[str, object]] = {section: {} for section in (*SECTIONS, *TABLE_SECTIONS)}
    origin: dict[str, Path] = {}
    for source, values in layers:
        for name, value in values.items():
            spec = SPECS[name]
            if source == shared_file and spec.tighten is not None and not _stricter(spec, value):
                continue
            origin[name] = source
            if isinstance(value, dict) and name in TABLE_SECTIONS:
                # A table of tables, such as every `[chores.<name>]`: the user file's replaces any other whole.
                merged[name] = {str(k): v for k, v in value.items()}
                continue
            section, key = name.split(".", 1)
            merged[section][key] = value
    return merged, origin


def _read(path: Path, *, skip: tuple[str, ...] = ()) -> dict[str, object]:
    """Return the file's config keys as `section.key` names. Tables named in `skip` are someone else's to read."""
    try:
        with path.open("rb") as f:
            doc = tomllib.load(f)
    except tomllib.TOMLDecodeError as e:
        raise ConfigError(f"{path}: {e}") from e
    except OSError as e:
        raise ConfigError(f"{path}: {e.strerror}") from e

    values: dict[str, object] = {}
    for section, table in doc.items():
        if section in skip:
            continue
        if not isinstance(table, dict):
            raise ConfigError(f"{path}: unknown key {section}")
        if section in TABLE_SECTIONS:
            values[section] = table
            continue
        for key, raw in table.items():
            name = f"{section}.{key}"
            if name in REMOVED_KEYS:
                raise ConfigError(f"{path}: {name} was removed: {REMOVED_KEYS[name]}")
            if name not in SPECS:
                raise ConfigError(f"{path}: unknown key {name}")
            values[name] = raw
    return values


def _stricter(spec: KeySpec, value: object) -> bool:
    """Return whether a workspace file's policy value may replace the default.

    A value of the wrong type is kept, so that validation reports it against the workspace file instead of silently
    dropping it.
    """
    default = spec.field.default
    if spec.tighten is Tighten.LATER:
        choices = get_args(spec.field.annotation)
        if value not in choices or default not in choices:
            return True
        return choices.index(value) > choices.index(default)
    if not isinstance(value, int) or isinstance(value, bool) or not isinstance(default, int):
        return True
    return value < default if spec.tighten is Tighten.LOWER else value > default


def _describe(error: ValidationError, origin: dict[str, Path], shared_file: Path, user_file: Path) -> str:
    lines: list[str] = []
    for e in error.errors():
        loc = [str(p) for p in e["loc"] if p != "[key]"]
        if loc[0] in TABLE_SECTIONS:
            # A named table's errors are about one of its keys: `chores.build-health.every_minutes`.
            source = origin.get(loc[0])
            prefix = f"{source}: " if source is not None else ""
            lines.append(f"{prefix}{'.'.join(loc[:3])}{''.join(f'[{p}]' for p in loc[3:])}: {e['msg']}")
            continue
        name = ".".join(loc[:2])
        where = name + "".join(f"[{p}]" for p in loc[2:])
        if e["type"] == "missing":
            files = str(user_file) if SPECS[name].scope is Scope.USER else f"{shared_file} or {user_file}"
            lines.append(f"missing required key {name}; set it in {files}")
        else:
            source = origin.get(name)
            prefix = f"{source}: " if source is not None else ""
            lines.append(f"{prefix}{where}: {e['msg']}")
    return "\n".join(lines)


def render_command(template: str, prompt: str, definitions_dir: Path, title: str) -> list[str]:
    """Turn a command template into argv. No shell runs (D023).

    The template is split with shell word rules, then `{prompt}`, `{definitions_dir}`, and `{title}` are replaced inside
    each word, in one pass, so no value is searched for another placeholder. The prompt therefore always lands in
    exactly one argument, whatever it contains. Every title starts with a letter or digit, so even as a word of its own
    it is never read as an option.
    """
    values = {PROMPT: prompt, DEFINITIONS_DIR: str(definitions_dir), TITLE: title}
    return [_PLACEHOLDER_RE.sub(lambda m: values[m.group(0)], w) for w in command_words(template)]
