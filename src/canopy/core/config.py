"""Layered configuration: built-in defaults, the workspace file, the user file, then the workspace's private file.

The workspace file is `canopy-workspace.toml`, which may be shared. The user file, `config.toml` in the user config
directory, serves every workspace and is optional. The private file, `config.toml` in the workspace's state directory,
is the operator's own for that workspace. No code repository's file is read (D016).

Every key has a scope (DESIGN §12). A shared key may be set in any file. A private key may be set in the user file or
the private file, never in the workspace file: a workspace file may be committed to a shared repository, and anyone who
can push there controls it (TRUST_MODEL T7). Later files win, key by key. Unknown keys are errors in every file. The
workspace file's `policy.*` values apply only when stricter than the built-in defaults.

The private file is under the workspace root, which may be a checkout, and its keys run commands. So `load` refuses a
state directory any of whose files git tracks, and a private file that is a symlink, someone else's, or writable by
anyone else. A relative `paths.*` value in it names a file in the state directory.

The models below are the schema: each field carries its type, default, and scope, and policy fields say which
direction is stricter. `load` enforces scopes and the tighten rule per file, merges, then lets pydantic validate
(D026).
"""

from __future__ import annotations

import ipaddress
import os
import re
import shlex
import stat
import tomllib
from collections.abc import Collection, Iterable, Mapping, Sequence
from dataclasses import dataclass
from enum import Enum
from pathlib import Path
from typing import TYPE_CHECKING, Annotated, Literal, get_args
from urllib.parse import urlsplit
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from pydantic import (
    AfterValidator,
    BaseModel,
    BeforeValidator,
    ConfigDict,
    Field,
    StrictBool,
    StrictFloat,
    StrictInt,
    StrictStr,
    ValidationError,
    model_validator,
)

from canopy.core import agent_models, bash_allows, chore_result, contract, hostgit
from canopy.core.vocab import MemoryMode, PlannerApproval, PoolKind, ReplyMode
from canopy.infra import procs, tracing
from canopy.runtime import agents, invocation
from canopy.runtime.agents import McpTools
from canopy.runtime.definitions import MAX_SKILL_NAME, SKILL_NAME_RE, TOOL_PART_RE
from canopy.runtime.implementation import Version

if TYPE_CHECKING:
    from pydantic.fields import FieldInfo

WORKSPACE_FILE_NAME = "canopy-workspace.toml"
# A workspace's state is always here, under its root: each workspace has its own journal and locks (DESIGN §18).
WORKSPACE_STATE_DIR = ".canopy"
# The private file's name, in the state directory, and the user file's, in the user config directory.
CONFIG_FILE_NAME = "config.toml"
# Tables of the workspace file that are its map, not config. `canopy.core.workspace` reads them.
WORKSPACE_MAP_TABLES = ("workspace", "repos")
# M55: triage before a plan waived too few plans to pay for itself, so trivial work is planned (DESIGN §25).
_PLANNED = "delete it; every ticket policy.plan plans is planned, and canopy plan KEY --skip waives one"
# Keys earlier canopy read, and what to do with one left in a file. Each is an error that says so, not "unknown key".
REMOVED_KEYS = {
    "paths.state_dir": f"delete it; state is always in the workspace's {WORKSPACE_STATE_DIR}/ (D016)",
    "trust.pr_label": "delete it; workers no longer label their PRs, which the branch prefix already marks",
    # M56: a `resume` fixes CI, so one limit counts it, and the cooldown holds a `resume` for CI alone (DESIGN §8).
    "policy.max_fix_ci_attempts": "delete it; a resume now fixes CI, so raise policy.max_resume_attempts instead",
    "policy.fix_ci_cooldown_minutes": "rename it policy.ci_cooldown_minutes; it holds a resume whose only reason is ci",
    # M46: workers file follow-up tickets, which replaced splits (DESIGN §18).
    "policy.max_split_attempts": "delete it; workers file follow-up tickets instead of a split run",
    "runtime.split_cmd": "delete it; workers file follow-up tickets instead of a split run",
    # M55: a triage's keys.
    "policy.plan_triage": _PLANNED,
    "policy.trivial": _PLANNED,
    "runtime.plan_triage_cmd": _PLANNED,
    "runtime.plan_triage_temperature": _PLANNED,
    "runtime.plan_triage_timeout_minutes": _PLANNED,
}
PROMPT = "{prompt}"
# Replaced with the snapshot of canopy's agent definitions and skills (D040).
DEFINITIONS_DIR = "{definitions_dir}"
# Replaced with the run's session title: a worker's `<KEY> <kind>: <ticket title>`, `tick <id>`, `chore:<name>`, or
# `review <PR URL>` (DESIGN §13). Optional in every template.
TITLE = "{title}"
_PLACEHOLDER_RE = re.compile(r"\{prompt\}|\{definitions_dir\}|\{title\}")
#: The sandbox wrapper canopy installs beside itself (DESIGN §24), by the name its command is installed as.
SANDBOX_WRAPPER = "canopy-sandbox"
# A repository name is a directory name, a treehouse leaf, and a `--repo` argument (DESIGN §18).
REPO_NAME_RE = re.compile(r"[a-z][a-z0-9-]*")
# A chore's name appears in file paths and on the command line (DESIGN §19).
CHORE_NAME_RE = re.compile(r"[a-z][a-z0-9-]*")
MIN_CHORE_EVERY_MINUTES = 15
#: A persona's name, and its file's, `<name>.md` (DESIGN §31): lowercase words joined by single hyphens, at most 40
#: characters, so it is a plain file name and reaches the journal and the command line as it is.
PERSONA_NAME_RE = re.compile(r"(?=[a-z0-9-]{1,40}\Z)[a-z0-9]+(?:-[a-z0-9]+)*")
#: The persona every agent writes in unless the operator chooses another: canopy's own voice, which it ships.
DEFAULT_PERSONA = "canopy"


class ConfigError(Exception):
    """The configuration cannot be used. The message names the file and key."""


class Scope(Enum):
    """Where a key may be set: any file, or only the user file and the private file."""

    SHARED = "shared"
    PRIVATE = "private"


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


#: The temperature that sets none, leaving the model's own: some models, such as OpenAI's reasoning ones, refuse a
#: request that sets one. No provider takes a negative temperature, so it cannot mean one.
NO_TEMPERATURE = -1
#: The highest temperature a provider takes; OpenAI's range ends there, Anthropic's at 1.
MAX_TEMPERATURE = 2


def _temperature(value: float) -> float:
    if value != NO_TEMPERATURE and not 0 <= value <= MAX_TEMPERATURE:
        raise ValueError(f"must be from 0 to {MAX_TEMPERATURE}, or {NO_TEMPERATURE} to set none")
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
    if not value:
        return value
    if (
        len(value) > MAX_COMMENT_MARK
        or value != value.strip()
        or not value.isprintable()
        or "`" in value
        or not any(c.isalnum() for c in value)
    ):
        raise ValueError(
            f"must be empty, or one line of at most {MAX_COMMENT_MARK} characters with a letter or digit, no backtick, "
            "and no surrounding spaces",
        )
    return value


MAX_TRAILER_NAME = 80
MAX_TRAILER_EMAIL = 254
# The `Co-authored-by` trailer canopy's git hooks add to a worker's commits (TRUST_MODEL T5).
DEFAULT_TRAILER_NAME = "canopy worker"
DEFAULT_TRAILER_EMAIL = "noreply@canopy.invalid"
# An address git and VCS hosts read as one: no whitespace, angle brackets, or backtick, and one "@" inside it.
TRAILER_EMAIL_RE = re.compile(r"[^\s<>@`]+@[^\s<>@`]+")


def _trailer_name(value: str) -> str:
    # The name in `Co-authored-by: <name> <<email>>`. Prompts quote the trailer in backticks, and an angle bracket or a
    # second line would end it early or start another.
    if (
        len(value) > MAX_TRAILER_NAME
        or value != value.strip()
        or not value.isprintable()
        or any(c in value for c in "`<>")
        or not any(c.isalnum() for c in value)
    ):
        raise ValueError(
            f"must be one line of at most {MAX_TRAILER_NAME} characters with a letter or digit, no backtick or angle "
            "bracket, and no surrounding spaces",
        )
    return value


def _trailer_email(value: str) -> str:
    if len(value) > MAX_TRAILER_EMAIL or not TRAILER_EMAIL_RE.fullmatch(value):
        raise ValueError(
            f"must be an address of at most {MAX_TRAILER_EMAIL} characters with one '@', and no whitespace, backtick, "
            "or angle bracket",
        )
    return value


MAX_COMMIT_PREFIX = 60
#: The placeholder `trust.commit_prefix` names the run's ticket key with.
KEY_PLACEHOLDER = "{key}"
#: How git's `--autosquash` finds the commit a fixup is for: by its subject, which a prefix must leave as it is.
AUTOSQUASH = ("fixup!", "squash!", "amend!")


def _commit_prefix(value: str) -> str:
    # Prompts quote it in backticks, and git reads a subject that starts with `#` as a comment and drops it.
    rest = value.replace(KEY_PLACEHOLDER, "")
    one_line = len(value) <= MAX_COMMIT_PREFIX and value.isprintable() and value == value.lstrip()
    quotable = not any(c in rest for c in "`{}")
    if value and not (one_line and quotable and not value.startswith(("#", *AUTOSQUASH))):
        raise ValueError(
            f"must be one line of at most {MAX_COMMIT_PREFIX} characters with no backtick, no brace but in "
            f"{KEY_PLACEHOLDER}, and no leading space, '#', or {', '.join(AUTOSQUASH)}",
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
            f"{CANOPY_REVIEWER!r} for canopy's own reviewer",
        )
    return value


def command_words(template: str) -> list[str]:
    """Split a command template into words, as `render_command` does. It may mention `{prompt}` at most once.

    Returns:
        The template's words, its placeholders not yet replaced.

    Raises:
        ValueError: The template is empty, has an unclosed quote, or contains `{prompt}` more than once.
    """
    words = shlex.split(template)
    if not words:
        raise ValueError("must not be empty")
    # At most once: the prompt must land in one argument, or on stdin, not be copied into several (D023).
    if sum(w.count("{prompt}") for w in words) > 1:
        raise ValueError("must contain {prompt} at most once; without it, the prompt arrives on stdin")
    return words


def _command_template(value: str) -> str:
    command_words(value)
    return value


def _agent_template(value: str) -> str:
    # Without the placeholder, the runtime would look for canopy's agent in the repository and, not finding it, run its
    # default agent, which allows everything (D040). The old default templates lack it, so say what to write instead.
    if DEFINITIONS_DIR not in value:
        raise ValueError(
            f"must contain {DEFINITIONS_DIR}, the directory canopy's agent definitions are in (D040). "
            f"For {invocation.NAME}, write: '{invocation.with_config_dir(DEFINITIONS_DIR, value)}'",
        )
    return value


def notify_words(template: str) -> list[str]:
    """Split `notify.cmd` into argv with shell word rules. No shell runs (D023). Empty means no notify command.

    Its input arrives on stdin, so a `{prompt}` would reach the command as a literal word; it is refused.

    Returns:
        The command's argv, or an empty list when `template` is empty.

    Raises:
        ValueError: The template contains `{prompt}` or has an unclosed quote.
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

    Returns:
        The command's argv, or an empty list when `template` is empty.

    Raises:
        ValueError: The template contains `{prompt}` or `{definitions_dir}`, or has an unclosed quote.
    """
    if PROMPT in template or DEFINITIONS_DIR in template:
        raise ValueError(f"must not contain {PROMPT} or {DEFINITIONS_DIR}; setup runs no agent")
    return shlex.split(template)


def _setup_command(value: str) -> str:
    setup_words(value)
    return value


def _no_model(*roles: str, run_args: bool = False) -> AfterValidator:
    """Refuse a template, prefix, or suffix that passes the runtime a model or a variant of one (DESIGN §13).

    canopy writes each agent's model, and its variant, into its definition, from `runtime.models`, and either on the
    command line would beat it unseen, so a run would record one model and run on another. `roles` are the keys of
    `runtime.models` to set instead. With `run_args`, every word is an argument of the agent's run, as a suffix's are.

    Returns:
        The validator.
    """
    keys = " or ".join(f"runtime.models.{role}" for role in roles)

    def check(value: str) -> str:
        _refuse_model_option(value, f"Set {keys} instead", run_args=run_args)
        return value

    return AfterValidator(check)


def _refuse_model_option(template: str, instead: str, *, run_args: bool = False) -> None:
    """Refuse `template` if it passes the runtime a model or a variant, saying what to set `instead`.

    Raises:
        ValueError: it passes one.
    """
    found = invocation.model_option(shlex.split(template), run_args=run_args)
    if found is not None:
        raise ValueError(
            f"must not pass a model or a variant ({found!r}): canopy writes the model into the agent's definition, "
            f"and one passed here would override it unseen. {instead}",
        )


def _wrapper(value: str) -> str:
    # `runtime.worker_cmd_prefix` or `worker_cmd_suffix`. It may name `{definitions_dir}` and `{title}`, replaced as in
    # the template it wraps, but the prompt is that template's to place, exactly once (D023).
    if PROMPT in value:
        raise ValueError(f"must not contain {PROMPT}; the command it wraps places the prompt")
    shlex.split(value)
    return value


def _user_path(value: Path) -> Path:
    # A relative path would resolve against the working directory, which is the workspace: its files would stand in
    # for the operator's prompts (TRUST_MODEL T7). `Path("")` is `.`, so an empty value is refused here too.
    expanded = value.expanduser()
    if not expanded.is_absolute():
        raise ValueError("must be an absolute path or start with ~")
    return expanded


def _persona_name(value: str) -> str:
    if not PERSONA_NAME_RE.fullmatch(value):
        raise ValueError(f"persona name {value!r} must be lowercase words joined by hyphens, at most 40 characters")
    return value


def _distinct_personas(value: tuple[str, ...]) -> tuple[str, ...]:
    # A persona named twice would review each commit twice in one voice.
    twice = sorted({name for name in value if value.count(name) > 1})
    if twice:
        raise ValueError(f"names {', '.join(twice)} more than once")
    return value


#: The highest the `policy.max_attachment*` keys go, whatever a file says: attachments are copied into every run of
#: their subject, and the web UI uploads one in a single request, which its server bounds (DESIGN §22).
ATTACHMENTS_CEILING = 20
ATTACHMENT_KIB_CEILING = 1024
ATTACHMENTS_TOTAL_KIB_CEILING = 4096

# bool is an int subclass; Strict* types reject `max_workers = true` and quoted numbers.
NonBlank = Annotated[StrictStr, AfterValidator(_non_blank)]
Count = Annotated[StrictInt, Field(ge=0)]
Minutes = Annotated[StrictInt, Field(ge=1)]
#: The longest `review.settle_minutes`: a week (DESIGN §21).
MAX_SETTLE_MINUTES = 7 * 24 * 60
#: An agent's sampling temperature, or `NO_TEMPERATURE`. TOML has no null, so a sentinel says "set none".
Temperature = Annotated[StrictFloat, AfterValidator(_temperature)]
CommandTemplate = Annotated[StrictStr, AfterValidator(_command_template)]
AgentTemplate = Annotated[StrictStr, AfterValidator(_command_template), AfterValidator(_agent_template)]
NotifyCommand = Annotated[StrictStr, AfterValidator(_notify_command)]
SetupCommand = Annotated[StrictStr, AfterValidator(_setup_command)]
Wrapper = Annotated[StrictStr, AfterValidator(_wrapper)]
UserPath = Annotated[Path, AfterValidator(_user_path)]
PersonaName = Annotated[StrictStr, AfterValidator(_persona_name)]
#: One of canopy's agents `runtime.allow_bash` names, and the commands it allows that agent (`canopy.core.bash_allows`).
BashRole = Annotated[str, AfterValidator(bash_allows.check_role)]
#: One of canopy's agents `runtime.models` names, and the model it chooses for that agent (`canopy.core.agent_models`).
ModelRole = Annotated[str, AfterValidator(agent_models.check_role)]
ModelId = Annotated[StrictStr, AfterValidator(agent_models.check_model)]
BashAllows = Annotated[
    tuple[Annotated[StrictStr, AfterValidator(bash_allows.check_pattern)], ...],
    AfterValidator(bash_allows.check_patterns),
]


class Section(BaseModel):
    """Base for config tables: unknown keys are errors, values are frozen, defaults are validated."""

    # validate_default: defaults go through the same validators as file values, so `~/.canopy` is expanded.
    model_config = ConfigDict(extra="forbid", frozen=True, validate_default=True, defer_build=True)


def _tool_part(value: str) -> str:
    if not TOOL_PART_RE.fullmatch(value):
        raise ValueError(f"{value!r} must match {TOOL_PART_RE.pattern}")
    return value


def _server_name(value: str) -> str:
    # Empty means the provider's default.
    return _tool_part(value) if value else value


ToolPart = Annotated[str, AfterValidator(_tool_part)]

TICKET_KEY = "{key}"
MAX_LINK_URL = 500


def link_template(placeholder: str) -> AfterValidator:
    """Refuse a link template unless it is empty or a plain https:// URL with `placeholder` in it exactly once.

    The web UI puts the template in an `href`, with the placeholder replaced: `tracker.ticket_url`'s `{key}`, a
    repository's `branch_url`'s `{branch}`.

    Returns:
        A validator that passes an empty or valid template through unchanged and raises `ValueError` on anything else.
    """

    def check(value: str) -> str:
        # Empty means unset.
        rest = value.replace(placeholder, "", 1)
        if value and (
            not contract.plain_url(value, MAX_LINK_URL) or placeholder not in value or "{" in rest or "}" in rest
        ):
            raise ValueError(
                f"must be empty, or a plain https:// URL of at most {MAX_LINK_URL} characters with {placeholder} "
                "exactly once and no other braces",
            )
        return value

    return AfterValidator(check)


# Each shipped provider's usual MCP server, as an operator's runtime config usually names it, and the tools of it a
# private worker needs: its read tools, which the planner gets too, and for GitHub, whose server is also the one PRs
# go through, the PR tools, which only the private worker gets. None of the reads writes anything
# (DESIGN §22, §25). Named from the servers' tool lists (Atlassian's Rovo MCP server v2, GitHub's MCP server v2.0.1);
# a name wrong here fails closed. Atlassian's server lists only its primary tools unless its URL asks for
# `?tools=all`, and runs the rest through `execute*` tools that read or write by argument; those are denied.
# The create tools are the ones a private worker files follow-ups with. GitHub's `issue_write` also edits and closes
# issues, which has no narrower tool to name; the prompt keeps it to creating (TRUST_MODEL T6).
DEFAULT_TRACKER_TOOLS: dict[str, McpTools] = {
    "jira": McpTools(
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
        ("createJiraIssue",),
    ),
    "github": McpTools(
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
            "actions_get",
            "actions_list",
            "get_job_logs",
        ),
        ("issue_write",),
        ("create_pull_request", "update_pull_request", "add_reply_to_pull_request_comment"),
    ),
}


class Tracker(Section):
    """The `[tracker]` table."""

    provider: Annotated[NonBlank, Scope.SHARED]
    query: Annotated[NonBlank, Scope.SHARED]
    needs_human_label: Annotated[NonBlank, Scope.SHARED] = "needs-human"
    # A ticket's page in the tracker, with {key} where its key goes: the web UI links each ticket there (DESIGN §17).
    # Empty means no link. Shared: the tracker's address is the team's, and a link runs nothing.
    ticket_url: Annotated[StrictStr, Scope.SHARED, link_template(TICKET_KEY)] = ""
    labels: Annotated[tuple[NonBlank, ...], Scope.PRIVATE, Field(min_length=1)]
    # The least time between ticks that run `query` (DESIGN §7, Spacing the query): a tick sooner than that after the
    # last live one that ran it works the tickets the journal knows and leaves the query out. 0 runs it every tick.
    # Private: it sets the operator's spend, and how long a newly labeled ticket can wait to be found.
    query_every_minutes: Annotated[Count, Scope.PRIVATE] = 0
    # The tracker's MCP server, as the operator's runtime config names it, and the read tools of it a private worker
    # and the planner may call (DESIGN §22, §25). Empty and unset mean the provider's defaults. A
    # provider's create and PR tools come from its defaults, whatever `read_tools` says. Private: they decide what a
    # private worker can write, which a shared workspace file must not (TRUST_MODEL T7).
    mcp_server: Annotated[StrictStr, Scope.PRIVATE, AfterValidator(_server_name)] = ""
    read_tools: Annotated[tuple[ToolPart, ...] | None, Scope.PRIVATE] = None
    # Whether a labeled ticket canopy has never worked is started privately by its first dispatch, as if the operator
    # had run `canopy start` (DESIGN §22, D119). Private: it turns a label into a start record, which a shared file
    # must not.
    private: Annotated[StrictBool, Scope.PRIVATE] = False

    def tools(self) -> McpTools | None:
        """The server and tools a private worker gets, or None if neither config nor a default names any.

        Returns:
            The configured server and read tools, each falling back to the provider's default, and the provider's
            create and PR tools, none for a provider canopy ships no defaults for; or None when the server or the read
            tools are still missing.
        """
        default = DEFAULT_TRACKER_TOOLS.get(self.provider)
        server = self.mcp_server or (default.server if default is not None else "")
        allowed = self.read_tools if self.read_tools is not None else (default.allowed if default is not None else ())
        if not server or not allowed:
            return None
        if default is None:
            return McpTools(server, tuple(allowed))
        return McpTools(server, tuple(allowed), default.create, default.pr_writes)


def _approval_level(value: object) -> object:
    # The key was a switch first: `true` keeps the bar it rendered then, and `false` keeps it off.
    if value is True:
        return PlannerApproval.STRICT
    if value is False:
        return PlannerApproval.OFF
    return value


class Policy(Section):
    """The `[policy]` table: attempt limits and cooldowns. A limit counts every run of that kind a ticket has had."""

    max_implement_attempts: Annotated[Count, Scope.SHARED, Tighten.LOWER] = 2
    # Every `resume` of a unit, whatever its reasons, an old `fix-ci` run counted among them (DESIGN §8): one run does
    # what a fix-ci and a resume did, so the limit is more than their two together.
    max_resume_attempts: Annotated[Count, Scope.SHARED, Tighten.LOWER] = 6
    # How long a `resume` whose only reason is `ci` waits after the unit's last run that worked on CI ended.
    ci_cooldown_minutes: Annotated[Count, Scope.SHARED, Tighten.HIGHER] = 30
    #: How long a trusted reviewer's new feedback waits on a PR's pending checks, from when a source first observed it,
    #: before the unit is no longer `ci_running` and the feedback is addressed with them still pending (DESIGN §7). A
    #: queue of builds otherwise holds it as long as the queue lasts; at 0 feedback never waits on them.
    feedback_ci_wait_minutes: Annotated[Count, Scope.SHARED, Tighten.HIGHER] = 30
    #: The most follow-up tickets one run's result has recorded, the first in its order (DESIGN §18). At 0 workers are
    #: told to file none, and none is recorded.
    max_follow_ups: Annotated[Count, Scope.SHARED, Tighten.LOWER] = 5
    # Plan runs per ticket (DESIGN §25): a plan covers every repository the ticket will touch.
    max_plan_attempts: Annotated[Count, Scope.SHARED, Tighten.LOWER] = 3
    #: Feedback plan runs per unit (DESIGN §32), whatever they ended as, never reset.
    max_feedback_plan_attempts: Annotated[Count, Scope.SHARED, Tighten.LOWER] = 6
    # Review runs per PR, whatever they ended as (DESIGN §21).
    max_reviews_per_pr: Annotated[Count, Scope.SHARED, Tighten.LOWER] = 3
    #: Revisions per review's draft, whatever they ended as, never reset (DESIGN §34): each is a review run.
    max_revisions_per_draft: Annotated[Count, Scope.SHARED, Tighten.LOWER] = 3
    # Whether a ticket waits on a plan the operator approved before its implement (DESIGN §25): a guard in code. A
    # ticket's own setting, `canopy plan KEY` or `--skip`, overrides it.
    plan: Annotated[Literal["off", "approve"], Scope.SHARED, Tighten.LATER] = "off"
    #: Whether every `resume` but one for `no_pr` alone waits on a feedback plan the operator approved (DESIGN §32): a
    #: guard in code. Private, unlike `plan`: it holds a trusted reviewer's feedback for the operator, and lets anyone
    #: else's start a plan run that reads only, so a shared file must choose neither (TRUST_MODEL T7).
    feedback_plan: Annotated[Literal["off", "approve"], Scope.PRIVATE] = "off"
    #: How readily the harness approves a plan, or a feedback plan, whose planner says it needs no review, as the
    #: planner's approval and not the operator's (DESIGN §25): `off`, or the bar the planner's prompt sets, `strict`,
    #: `normal`, or `lenient`. `true` reads as `strict` and `false` as `off`. Private: it loosens the operator's gate
    #: on plans, so only the operator's own files turn it on (TRUST_MODEL T7).
    planner_may_approve: Annotated[PlannerApproval, Scope.PRIVATE, BeforeValidator(_approval_level)] = (
        PlannerApproval.OFF
    )
    #: How long a stale feedback plan waits after the newest item or reply on its PRs before it is planned again
    #: (DESIGN §32): a burst of comments makes one plan, and a bot's stream of them a bounded number (TRUST_MODEL T3).
    feedback_quiet_minutes: Annotated[Count, Scope.SHARED, Tighten.HIGHER] = 10
    # Whether the overseer may stack a ticket on its blocker's open PR (DESIGN §10). Prompt policy, not a guard.
    stacking: Annotated[Literal["auto", "never"], Scope.SHARED, Tighten.LATER] = "auto"
    #: The most files the operator may have attached to one ticket or task at once (DESIGN §22); 0 turns attaching off.
    max_attachments: Annotated[StrictInt, Scope.SHARED, Tighten.LOWER, Field(ge=0, le=ATTACHMENTS_CEILING)] = 5
    #: The most KiB one attachment's text may hold.
    max_attachment_kib: Annotated[StrictInt, Scope.SHARED, Tighten.LOWER, Field(ge=1, le=ATTACHMENT_KIB_CEILING)] = 512
    #: The most KiB the attachments of one ticket or task may hold together.
    max_attachments_total_kib: Annotated[
        StrictInt,
        Scope.SHARED,
        Tighten.LOWER,
        Field(ge=1, le=ATTACHMENTS_TOTAL_KIB_CEILING),
    ] = 1024

    def planner_approves(self) -> bool:
        """Return whether a planner may say its plan needs no review, at any level (DESIGN §25).

        Returns:
            True unless `planner_may_approve` is `off`.
        """
        return self.planner_may_approve is not PlannerApproval.OFF


class Trust(Section):
    """The `[trust]` table."""

    branch_prefix: Annotated[StrictStr, Scope.SHARED, AfterValidator(_branch_prefix)] = "agent/"
    authorized_repliers: Annotated[tuple[NonBlank, ...], Scope.PRIVATE] = ()
    # Whose review feedback a worker may address without the operator's go-ahead (DESIGN §7, D089): VCS host logins,
    # and `canopy:review` for canopy's own reviewer. Anyone else's waits for an operator message. Private: a
    # workspace file that listed its own bots would decide what steers the operator's workers.
    trusted_reviewers: Annotated[tuple[Annotated[StrictStr, AfterValidator(_reviewer)], ...], Scope.PRIVATE] = ()
    # What every worker comment starts and ends with, when set (DESIGN §8, D069). They only take authority away, from
    # the comments that carry them; private, so a shared file cannot pick marks that silence people's comments.
    comment_prefix: Annotated[StrictStr, Scope.PRIVATE, AfterValidator(_comment_mark)] = "CANOPY:"
    comment_suffix: Annotated[StrictStr, Scope.PRIVATE, AfterValidator(_comment_mark)] = ""
    # Whether canopy's git hooks add its trailer to a worker's commits, and whom it names as co-author (TRUST_MODEL T5).
    # Private: the commits are the operator's, and a shared file must neither credit agent work to a person nor strip
    # the mark that tells it is an agent's.
    commit_trailer: Annotated[StrictBool, Scope.PRIVATE] = True
    commit_trailer_name: Annotated[StrictStr, Scope.PRIVATE, AfterValidator(_trailer_name)] = DEFAULT_TRAILER_NAME
    commit_trailer_email: Annotated[StrictStr, Scope.PRIVATE, AfterValidator(_trailer_email)] = DEFAULT_TRAILER_EMAIL
    # What canopy's git hooks put before the subject of each commit a worker makes, `{key}` filled with its ticket's
    # key, but a `fixup!`, `squash!`, or `amend!` one's (TRUST_MODEL T5); empty for none. Private, as the trailer is:
    # the commits are the operator's, and a shared file must not write into their messages.
    commit_prefix: Annotated[StrictStr, Scope.PRIVATE, AfterValidator(_commit_prefix)] = ""
    # Whether workers bring a base branch in by rebasing, and push the result with a lease, instead of merging it
    # (TRUST_MODEL T1, D056), for repositories that refuse merge commits. Private: a shared file must not let
    # workers replace a branch's history.
    rebase: Annotated[StrictBool, Scope.PRIVATE] = False
    #: How many times canopy reruns a PR's checks a `resume` for `ci` judged flaky, for each head a worker pushed, by
    #: rebasing the branch onto its base and pushing it with a lease (DESIGN §23, TRUST_MODEL T1); 0 leaves every
    #: rerun to the operator. Private: a shared file must not let canopy replace a branch's history.
    max_flaky_kicks: Annotated[Count, Scope.PRIVATE] = 0
    # Whether workers draft the comments they would post, for the operator to send, or post them, marked (DESIGN
    # §29). Private: a shared file must not decide what is said in the operator's name.
    review_replies: Annotated[ReplyMode, Scope.PRIVATE] = ReplyMode.APPROVE

    @model_validator(mode="after")
    def _one_comment_mark(self) -> Trust:
        # With neither, a worker's comment reads as the operator's, and its PR replies as new review feedback.
        if not self.comment_prefix and not self.comment_suffix:
            raise ValueError("set trust.comment_prefix, trust.comment_suffix, or both: workers mark their comments")
        return self


def _skill_name(value: str) -> str:
    # Empty means unset. The name is quoted in worker prompts, so it is checked as the runtime would (DESIGN §8).
    if value and (len(value) > MAX_SKILL_NAME or not SKILL_NAME_RE.fullmatch(value)):
        raise ValueError(
            f"must be empty, or a skill name of at most {MAX_SKILL_NAME} lowercase letters and digits in words joined "
            "by single hyphens",
        )
    return value


def _repo_name(value: str) -> str:
    if not REPO_NAME_RE.fullmatch(value):
        raise ValueError(f"repository name {value!r} must match {REPO_NAME_RE.pattern}")
    return value


RepoName = Annotated[str, AfterValidator(_repo_name)]


class Capacity(Section):
    """The `[capacity]` table."""

    max_workers: Annotated[Count, Scope.PRIVATE] = 2
    # Chore runs at once, apart from max_workers; 0 turns every chore off (DESIGN §19).
    max_chores: Annotated[Count, Scope.PRIVATE] = 1
    # Review runs at once, within max_workers, and started in any 24 hours; 0 turns reviews off (DESIGN §21).
    max_reviews: Annotated[Count, Scope.PRIVATE] = 1
    max_reviews_per_day: Annotated[Count, Scope.PRIVATE] = 20
    #: Task runs at once, within max_workers; 0 starts none (DESIGN §36). The workspace file may only lower it.
    max_tasks: Annotated[Count, Scope.SHARED, Tighten.LOWER] = 1
    # Slots in each repository's pool, in a workspace: `canopy workspace sync` creates and removes slots to match, and
    # no lease grows a pool past it. None leaves the pools unmanaged, as treehouse's own `max_trees` has them. Names in
    # `repo_slots` need not be in this workspace's map: the user file serves every workspace (DESIGN §18).
    slots_per_repo: Annotated[Count | None, Scope.PRIVATE] = None
    repo_slots: Annotated[dict[RepoName, Count], Scope.PRIVATE] = {}

    def slots_for(self, repo: str) -> int | None:
        """The slots declared for repository `repo`'s pool, or None if its pool is not managed.

        Returns:
            The repository's entry in `repo_slots`, else `slots_per_repo`, which is None when pools are unmanaged.
        """
        return self.repo_slots.get(repo, self.slots_per_repo)


class Pools(Section):
    """The `[pools]` table: which pool makes a workspace's worktrees (DESIGN §18, ROADMAP M45).

    Private, as the pools' sizes are: it decides what runs on the operator's machine. Switching is safe with runs in
    flight, since a lease always goes back to the pool that made it.
    """

    backend: Annotated[PoolKind, Scope.PRIVATE] = PoolKind.TREEHOUSE


def _default_cmd(agent: str, version: Version = Version.ONE) -> str:
    return invocation.default_template(agent, version=version, definitions_dir=DEFINITIONS_DIR, title=TITLE)


def _plain_version(value: object) -> object:
    # A plain integer, as every number config reads is: not "2", true, or 2.0, which the enum would take as one.
    if not isinstance(value, Version) and type(value) is not int:
        raise ValueError(f"must be {' or '.join(str(v.value) for v in Version)}, a number")
    return value


#: Each agent's command template, by its key, and the agent the key's default runs.
_AGENT_CMDS = {
    "overseer_cmd": agents.OVERSEER,
    "worker_cmd": agents.WORKER,
    "private_worker_cmd": agents.PRIVATE_WORKER,
    "plan_cmd": agents.PLANNER,
    "chore_cmd": agents.CHORE,
    "review_cmd": agents.REVIEWER,
}


class Runtime(Section):
    """The `[runtime]` table: agent command templates and timeouts."""

    #: The major version of the runtime canopy runs: 1, or 2 to run OpenCode 2, 2.1.4 or later (DESIGN §13). The
    #: default templates are the version's. Private: it decides what runs on the operator's machine.
    version: Annotated[Version, Scope.PRIVATE, BeforeValidator(_plain_version)] = Version.ONE
    overseer_cmd: Annotated[AgentTemplate, Scope.PRIVATE, _no_model("overseer")] = _default_cmd(agents.OVERSEER)
    #: The overseer's temperature, or -1 to set none and leave the model's own: set -1 when the overseer runs on a
    #: model that refuses one, such as OpenAI's reasoning models.
    overseer_temperature: Annotated[Temperature, Scope.PRIVATE] = 0.1
    worker_cmd: Annotated[AgentTemplate, Scope.PRIVATE, _no_model("worker")] = _default_cmd(agents.WORKER)
    # A private ticket's worker: its own agent, which cannot write to the tracker (DESIGN §22). Shares the worker's
    # timeout.
    private_worker_cmd: Annotated[AgentTemplate, Scope.PRIVATE, _no_model("worker")] = _default_cmd(
        agents.PRIVATE_WORKER,
    )
    # The planner is its own agent, with no edit or shell tools and only the tracker's read tools (DESIGN §25); it
    # shares the worker's timeout.
    plan_cmd: Annotated[AgentTemplate, Scope.PRIVATE, _no_model("planner")] = _default_cmd(agents.PLANNER)
    # A chore's default command; a chore that runs the operator's own tools sets its own (DESIGN §19).
    chore_cmd: Annotated[AgentTemplate, Scope.PRIVATE, _no_model("chore")] = _default_cmd(agents.CHORE)
    # The reviewer; running it on a different model from the worker's, `models.reviewer`, is recommended (DESIGN §21).
    review_cmd: Annotated[AgentTemplate, Scope.PRIVATE, _no_model("reviewer")] = _default_cmd(agents.REVIEWER)
    #: The reviewer's temperature, or -1, the default, to set none and leave the model's own. The reviewer is meant to
    #: run on another model than the worker's (DESIGN §21), and some, such as OpenAI's reasoning models, refuse a
    #: request that sets one; set a low one when the reviewer runs on a model that takes it.
    review_temperature: Annotated[Temperature, Scope.PRIVATE] = NO_TEMPERATURE
    # Words before and after each command a worker run starts (`worker_cmd`, `private_worker_cmd`, `plan_cmd`), such as
    # a sandbox wrapper, so one key covers all three (DESIGN §12). Neither may pass a model: `models` chooses it.
    worker_cmd_prefix: Annotated[Wrapper, Scope.PRIVATE, _no_model("worker", "planner")] = ""
    worker_cmd_suffix: Annotated[Wrapper, Scope.PRIVATE, _no_model("worker", "planner", run_args=True)] = ""
    review_timeout_minutes: Annotated[Minutes, Scope.PRIVATE] = 20
    overseer_timeout_minutes: Annotated[Minutes, Scope.PRIVATE] = 15
    worker_timeout_minutes: Annotated[Minutes, Scope.PRIVATE] = 45
    # The skill workers open PRs with, instead of the GitHub MCP; empty means the MCP (DESIGN §8). Private: it
    # chooses what workers are told to do, which a shared workspace file must not (TRUST_MODEL T7).
    pr_skill: Annotated[StrictStr, Scope.PRIVATE, AfterValidator(_skill_name)] = ""
    # Run in each slot of a worker run once its branch is checked out, before the worker starts; a failure or timeout
    # ends the run `crashed` (DESIGN §8). Empty means none. It runs the branch's code on this machine.
    setup_cmd: Annotated[SetupCommand, Scope.PRIVATE] = ""
    setup_timeout_minutes: Annotated[Minutes, Scope.PRIVATE] = 30
    #: Commands an agent may run beyond its own bash rules, by its role: the overseer's, the planner's, and the workers'
    #: (DESIGN §13). Private: it widens what an agent's shell reaches (TRUST_MODEL T1, T7).
    allow_bash: Annotated[dict[BashRole, BashAllows], Scope.PRIVATE] = {}
    #: Each agent's model, `provider/model`, or `provider/model@variant` at one of its variants, by its role: `worker`
    #: (both workers, and a task's runs), `planner`, `reviewer`, `overseer`, and `chore` (every chore without a `model`
    #: of its own). canopy writes it into the agent's definition; an agent not named runs on the runtime's default.
    #: Private: it chooses what the operator's spend buys, and which provider is sent the ticket and the code (DESIGN
    #: §13, TRUST_MODEL T7).
    models: Annotated[dict[ModelRole, ModelId], Scope.PRIVATE] = {}
    #: The repositories, by name, whose runs canopy starts in the sandbox wrapper itself: each worker run's commands,
    #: `setup_cmd`, and a review's, with the role each takes (DESIGN §24). Names need not be in this workspace's map,
    #: as the user file serves every workspace. Private: it decides what a run may reach (TRUST_MODEL T4, T7).
    sandbox_repos: Annotated[tuple[RepoName, ...], Scope.PRIVATE] = ()

    @model_validator(mode="before")
    @classmethod
    def _version_defaults(cls, data: object) -> object:
        # A template the operator did not set is the default of the version they did; a version that is not one is
        # left for the field to refuse.
        if not isinstance(data, Mapping):
            return data
        try:
            version = Version(data.get("version", Version.ONE))
        except (TypeError, ValueError):
            return data
        defaults = {key: _default_cmd(agent, version) for key, agent in _AGENT_CMDS.items() if key not in data}
        return {**data, **defaults}

    @model_validator(mode="after")
    def _sandboxed_once(self) -> Runtime:
        # A command already wrapped would be wrapped again, a sandbox inside a sandbox, which the wrapper cannot run.
        if not self.sandbox_repos:
            return self
        keys = ("worker_cmd_prefix", "worker_cmd", "private_worker_cmd", "plan_cmd", "setup_cmd", "review_cmd")
        for key in keys:
            words = shlex.split(getattr(self, key))
            if words and Path(words[0]).name == SANDBOX_WRAPPER:
                raise ValueError(
                    f"runtime.{key} starts with {SANDBOX_WRAPPER}, and runtime.sandbox_repos has canopy add it: "
                    f"remove one, or the runs of {', '.join(self.sandbox_repos)} would be sandboxed twice",
                )
        return self

    def worker_template(self, template: str) -> str:
        """Return `template`, one of a worker run's commands, between `worker_cmd_prefix` and `worker_cmd_suffix`.

        Each part splits into words on its own, ending outside any quote, so the result's words are the prefix's, the
        template's, then the suffix's.
        """
        return " ".join(part for part in (self.worker_cmd_prefix, template, self.worker_cmd_suffix) if part)


#: An eval case's name, which names its files and `canopy review eval --case`.
EVAL_CASE_RE = re.compile(r"[a-z0-9][a-z0-9-]{0,39}")
#: A line a bug case's operator confirmed the bug on: `path:line`, or `path:first-last` for a range of lines.
EVAL_LINE_RE = re.compile(r"(?P<path>[^\s:][^:]*):(?P<first>[1-9][0-9]{0,6})(?:-(?P<last>[1-9][0-9]{0,6}))?")
#: A full commit, as git names one: sha-1 or sha-256.
COMMIT_RE = re.compile(r"[0-9a-f]{40}|[0-9a-f]{64}")
_MAX_EVAL_URL = 300


def _eval_case_name(value: str) -> str:
    if not EVAL_CASE_RE.fullmatch(value):
        raise ValueError(f"{value!r} must match {EVAL_CASE_RE.pattern}")
    return value


def _commit(value: str) -> str:
    if not COMMIT_RE.fullmatch(value):
        raise ValueError(f"{value!r} must be a full commit: 40 or 64 lowercase hex characters")
    return value


def _eval_url(value: str) -> str:
    if not contract.plain_url(value, _MAX_EVAL_URL):
        raise ValueError(f"{value!r} must be the PR's plain https:// URL, at most {_MAX_EVAL_URL} characters")
    return value


def _eval_line(value: str) -> str:
    found = EVAL_LINE_RE.fullmatch(value)
    if found is None:
        raise ValueError(f"{value!r} must be path:line or path:first-last")
    if found["last"] is not None and int(found["last"]) < int(found["first"]):
        raise ValueError(f"{value!r} ends before it starts")
    return value


class EvalCase(Section):
    """One `[[review.eval_cases]]` table: a PR at a commit the reviewer is scored on (DESIGN §21, Scoring the reviewer).

    A `bug` case is a change that was reverted or fixed forward, with the lines its bug is on as the operator confirmed
    them; a `clean` case is one the operator knows is sound, so every finding on it is a false alarm.
    """

    name: Annotated[StrictStr, AfterValidator(_eval_case_name)]
    pr: Annotated[StrictStr, AfterValidator(_eval_url)]
    #: The repository the PR is in, by its name in the workspace's map.
    repo: RepoName
    #: The commit reviewed: the PR's head as it merged, or as it stood when the bug was in it.
    sha: Annotated[StrictStr, AfterValidator(_commit)]
    #: The commit the PR's change starts from, its merge base with its base branch: so a PR that has since merged is
    #: reviewed as the change it was, and every eval of the case reads the same diff.
    base: Annotated[StrictStr, AfterValidator(_commit)]
    kind: Literal["bug", "clean"]
    #: A bug case's confirmed lines, at least one; a clean case has none.
    lines: tuple[Annotated[StrictStr, AfterValidator(_eval_line)], ...] = ()

    @model_validator(mode="after")
    def _lines_match_kind(self) -> EvalCase:
        if self.kind == "bug" and not self.lines:
            raise ValueError(f"bug case {self.name} needs lines, the path:line its bug is on")
        if self.kind == "clean" and self.lines:
            raise ValueError(f"clean case {self.name} has no bug, so no lines")
        return self


def _distinct_cases(value: tuple[EvalCase, ...]) -> tuple[EvalCase, ...]:
    names = [case.name for case in value]
    twice = sorted({name for name in names if names.count(name) > 1})
    if twice:
        raise ValueError(f"names {', '.join(twice)} more than once")
    return value


class Review(Section):
    """The `[review]` table: which PRs get an adversarial review (DESIGN §21). Every key is private."""

    # The loop's own PRs, before a human is asked to review them.
    agent_prs: Annotated[StrictBool, Scope.PRIVATE] = False
    # PRs the operator names in the VCS host's own search syntax. It authorizes, unlike tracker.query.
    query: Annotated[StrictStr, Scope.PRIVATE] = ""
    # Plain language for the reviewer: which changes it may call low impact. Without it, none.
    low_impact: Annotated[StrictStr, Scope.PRIVATE] = ""
    #: The PRs `canopy review eval` scores the reviewer on. Private: a case may name a private repository's PR, and it
    #: authorizes a review of it, as `query` does.
    eval_cases: Annotated[tuple[EvalCase, ...], Scope.PRIVATE, AfterValidator(_distinct_cases)] = ()
    # How long a PR's head commit must have been seen before it is reviewed; a new push starts over. 0 reviews at once.
    # At most a week: a longer wait is a reason to turn the review off, and the clock's arithmetic stays in range.
    settle_minutes: Annotated[StrictInt, Field(ge=0, le=MAX_SETTLE_MINUTES), Scope.PRIVATE] = 0


class Memory(Section):
    """The `[memory]` table: what workers record of what they learn, and whether later runs read it (DESIGN §28).

    Each tier is `off`, `record` (workers write, no agent reads), or `use`. Private: `use` changes what agents may write
    into later prompts, and `record` fills what `use` would serve (TRUST_MODEL T7).
    """

    # Notes a ticket's runs write for its later runs.
    ticket_notes: Annotated[MemoryMode, Scope.PRIVATE] = MemoryMode.OFF
    # Lessons workers propose for every run in the workspace, which reach a prompt only once the operator promotes one.
    proposals: Annotated[MemoryMode, Scope.PRIVATE] = MemoryMode.OFF

    @property
    def on(self) -> bool:
        """Whether either tier is on, recording or in use."""
        return (self.ticket_notes, self.proposals) != (MemoryMode.OFF, MemoryMode.OFF)

    @property
    def in_use(self) -> bool:
        """Whether a tier is at `use`, so some run may read memory."""
        return MemoryMode.USE in (self.ticket_notes, self.proposals)


class Retention(Section):
    """The `[retention]` table: how long canopy keeps its own history (DESIGN §26). `0` keeps that kind forever.

    Private: only the operator's own config shortens retention, since an agent that could remove history early could
    remove the transcript that shows what it did. Read by `canopy gc --dry-run`, and by the pass a live tick runs, which
    removes files and the journal's rows, and rotates `canopy.log` (ROADMAP M47).
    """

    # A run's, chore run's, or review's log, prompt, and diff, once it ended this long ago.
    run_files_days: Annotated[Count, Scope.PRIVATE] = 30
    # A tick's log and prompt; a tick that did not close `ok` keeps them for `run_files_days`.
    tick_files_days: Annotated[Count, Scope.PRIVATE] = 7
    # The attention rows the harness raised, connector runs, and derivations, once outside the attention list's window.
    journal_days: Annotated[Count, Scope.PRIVATE] = 90
    # `canopy.log` is rotated past this many MiB, and this many rotated files are kept.
    log_max_mib: Annotated[Count, Scope.PRIVATE] = 50
    log_keep: Annotated[Count, Scope.PRIVATE] = 3
    # The text of a note or proposal no longer in force (DESIGN §28); a lesson's is never removed.
    memory_days: Annotated[Count, Scope.PRIVATE] = 30


class Loop(Section):
    """The `[loop]` table: how `canopy loop` paces ticks. Every tick runs the overseer, so this sets its spend."""

    interval_minutes: Annotated[Minutes, Scope.PRIVATE] = 15
    # The longest wait after idle ticks in a row (DESIGN §6, Idle pacing). Not above the interval, idle pacing is off.
    idle_max_minutes: Annotated[Minutes, Scope.PRIVATE] = 120
    # The least time from one tick's end to the next's start, whatever ends the wait, but `TICK_NOW_KEY` (DESIGN §6).
    min_gap_minutes: Annotated[Minutes, Scope.PRIVATE] = 1
    # A tick runs no overseer, so dispatches nothing, while the state directory's or the workspace's filesystem has less
    # than this many MiB free (DESIGN §6 step 5). `0` turns the check off.
    min_free_disk_mib: Annotated[Count, Scope.PRIVATE] = 2048

    @model_validator(mode="after")
    def _cap_not_below_interval(self) -> Loop:
        # Only when set: the default under a longer interval turns idle pacing off, as setting it to the interval does.
        if "idle_max_minutes" in self.model_fields_set and self.idle_max_minutes < self.interval_minutes:
            raise ValueError(
                f"loop.idle_max_minutes ({self.idle_max_minutes}) must be at least loop.interval_minutes "
                f"({self.interval_minutes}); set them equal to turn idle pacing off",
            )
        return self


#: The most budget alerts, and the highest percentage one may name: ten times the budget.
MAX_ALERTS = 10
MAX_ALERT_PERCENT = 1000


def _distinct_alerts(value: tuple[int, ...]) -> tuple[int, ...]:
    twice = sorted({p for p in value if value.count(p) > 1})
    if twice:
        raise ValueError(f"names {', '.join(map(str, twice))} more than once")
    return value


class Spend(Section):
    """The `[spend]` table: what the operator means to spend on agent runs (DESIGN §11). Read, never enforced."""

    #: In whole US dollars: what the local calendar month's agent spend may cost, canopy's runs and the runtime's
    #: sessions outside canopy, as `canopy spend` and the spend page track it, canopy's share beside it. A sink that
    #: takes `loop` hears once when the month's spend reaches it. None tracks no budget.
    monthly_budget_usd: Annotated[Annotated[StrictInt, Field(ge=1)] | None, Scope.PRIVATE] = None
    #: Percentages of the budget, besides the 100 always sent, at which that sink also hears the month reached it:
    #: `[50, 80]` warns at half and at four fifths, `[150]` when the month runs well past it.
    budget_alerts: Annotated[
        tuple[Annotated[StrictInt, Field(ge=1, le=MAX_ALERT_PERCENT)], ...],
        Scope.PRIVATE,
        Field(max_length=MAX_ALERTS),
        AfterValidator(_distinct_alerts),
    ] = ()


# Host names that mean loopback. The web UI's Host and Origin checks accept these and the bind address (DESIGN §22).
LOOPBACK_NAMES = frozenset({"localhost", "127.0.0.1", "::1"})
# A path prefix the web UI is served under through a proxy: `/canopy`, `/a/b`. Restricted to characters that need no
# escaping in a URL or an HTML attribute, since the server writes it into index.html's <base href>.
_BASE_PATH_RE = re.compile(r"(/[A-Za-z0-9._~-]+)*")


def listen_address(value: str) -> str:
    """Refuse an address a listener may not bind (TRUST_MODEL T8): only loopback or a private address, as an IP.

    Never a wildcard (`0.0.0.0`, `::`), a public address, or a host name other than `localhost`, whose address canopy
    would not know.

    Returns:
        `value` unchanged.

    Raises:
        ValueError: `value` is not a loopback name or an IP address, or is a wildcard, multicast, or public address.
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
    """Refuse a path prefix that is not empty or like `/canopy`, with no trailing slash.

    Returns:
        `value` unchanged.

    Raises:
        ValueError: `value` is not empty or `/`-separated segments of URL-safe characters, or a segment is `.` or `..`.
    """
    if not _BASE_PATH_RE.fullmatch(value) or any(part in {".", ".."} for part in value.split("/")):
        raise ValueError(f"base path {value!r} must be empty or like /canopy, with no trailing slash")
    return value


#: The longest `serve.url`: the links built on it must fit in a notification.
MAX_UI_URL = 200
# A URL's own characters, so a link built on it needs no escaping in a notification's markup: no space, `|`, `<`, `>`,
# quote, or backslash. The Slack sink checks each link against the same class (`_PAGE` in `canopy_notify_slack`).
_UI_URL_RE = re.compile(r"https?://[A-Za-z0-9._~:/?#\[\]@!$&'()*+,;=%-]+")


def _ui_url(value: str) -> str:
    """Refuse an address for the web UI's links that is not a plain `http` or `https` URL with a host.

    Returns:
        `value`, ending in `/`, so a page's path follows it.

    Raises:
        ValueError: `value` is too long, holds a character a URL does not, a user part, a query, or a fragment, has
            a port that is not a number, or is not `http` or `https` with a host.
    """
    if len(value) > MAX_UI_URL or not _UI_URL_RE.fullmatch(value):
        raise ValueError(f"{value[:MAX_UI_URL]!r} must be an http:// or https:// URL, like http://localhost:9000/")
    parts = urlsplit(value)
    try:
        parts.port  # noqa: B018  (read for the error a port that is not a number raises)
    except ValueError:
        raise ValueError(f"{value!r} has a port that is not a number from 0 to 65535") from None
    if not parts.hostname or "@" in parts.netloc or parts.query or parts.fragment:
        raise ValueError(f"{value!r} must name a host, with no user part, query, or fragment")
    return value if value.endswith("/") else f"{value}/"


class Telemetry(Section):
    """The `[telemetry]` table: traces of what canopy does, through OpenTelemetry (DESIGN §12).

    Every key is private: what canopy records of the operator's machine, and where it goes, is theirs to choose.
    """

    #: `off`, or `file`: each span appended, as OTLP JSON, to `traces.jsonl` in the state directory, for a collector
    #: the operator runs to read. Nothing leaves the machine either way.
    traces: Annotated[tracing.Traces, Scope.PRIVATE] = "off"


class Serve(Section):
    """The `[serve]` table: the web UI `canopy loop` serves (DESIGN §22).

    Every key is private: it opens a listener on the operator's machine (TRUST_MODEL T8).
    """

    enabled: Annotated[StrictBool, Scope.PRIVATE] = True
    bind: Annotated[StrictStr, Scope.PRIVATE, AfterValidator(listen_address)] = "127.0.0.1"
    port: Annotated[StrictInt, Scope.PRIVATE, Field(ge=1, le=65535)] = 8765
    base_path: Annotated[StrictStr, Scope.PRIVATE, AfterValidator(check_base_path)] = ""
    # Where notifications' links open the UI, in place of the address it is served at: an SSH forward's port, or a
    # proxy's address. It replaces that whole address, so it includes `base_path` if the UI is served under one. It
    # moves only the links; the server still listens on `bind`, and still checks the Host header.
    url: Annotated[Annotated[StrictStr, AfterValidator(_ui_url)] | None, Scope.PRIVATE] = None


class Paths(Section):
    """The `[paths]` table."""

    # No static default: `load` supplies `prompts/` in the user config directory, which depends on XDG_CONFIG_HOME.
    prompt_overrides: Annotated[UserPath, Scope.PRIVATE]
    #: A personal `.worktreeinclude`, passed on every `treehouse get` as `--include-file`. treehouse then seeds the
    #: ignored files it selects from the primary clone in place of the committed manifest's (DESIGN §9).
    worktree_include: Annotated[UserPath | None, Scope.PRIVATE] = None
    #: The operator's standing instructions, rendered into every worker prompt (DESIGN §12).
    worker_instructions: Annotated[UserPath | None, Scope.PRIVATE] = None
    #: The operator's standing instructions to the overseer, rendered into its prompt (DESIGN §12).
    overseer_instructions: Annotated[UserPath | None, Scope.PRIVATE] = None
    #: The operator's standing instructions to every reviewer, rendered into its prompt (DESIGN §12).
    reviewer_instructions: Annotated[UserPath | None, Scope.PRIVATE] = None
    #: The operator's standing instructions to every chore run, after the chore's own prompt (DESIGN §12).
    chore_instructions: Annotated[UserPath | None, Scope.PRIVATE] = None
    #: The operator's personas, each `<name>.md`: one shadows a shipped persona of its name, any other adds to them
    #: (DESIGN §31).
    personas: Annotated[UserPath | None, Scope.PRIVATE] = None
    #: The operator's checklists, each `<repo>.md` for the mapped repository of that name: the rules a worker run
    #: that pushes there is asked to hold its diff to (DESIGN §42).
    checklists: Annotated[UserPath | None, Scope.PRIVATE] = None
    #: A clone of the operator's own repository, at its top level: a live tick exports every plan of the workspace
    #: into `<it>/<workspace>/`, commits, and pushes to its upstream (DESIGN §25). Private, since it sends every plan's
    #: text where it points (TRUST_MODEL T6).
    plan_archive: Annotated[UserPath | None, Scope.PRIVATE] = None
    #: Whether `plan_archive` takes the plans into `<it>/<workspace>/`; off, into its top level, for a clone that
    #: archives this workspace alone. Private, as `plan_archive` is: it chooses what canopy commits in that clone.
    plan_archive_workspace_dir: Annotated[StrictBool, Scope.PRIVATE] = True
    #: Whether `plan_archive` also takes the prompt each plan's planner was given, beside its plan. Private, as
    #: `plan_archive` is: a prompt carries the operator's messages and standing instructions.
    plan_archive_prompts: Annotated[StrictBool, Scope.PRIVATE] = True
    #: Whether `plan_archive` also takes each planned ticket's conversation: its workers' reports and questions, the
    #: operator's replies, and mirrored tracker comments, a private ticket's too. Off by default, and private, so only
    #: the operator sends a conversation to a remote chosen for plans.
    plan_archive_conversations: Annotated[StrictBool, Scope.PRIVATE] = False
    #: Whether `plan_archive` also takes the operator's comments on each ticket's plans, with the passages they quote
    #: and their replies. Private, as `plan_archive` is: comments are the operator's own words.
    plan_archive_comments: Annotated[StrictBool, Scope.PRIVATE] = True
    #: The least time between archives to `plan_archive`, timed from its last commit there (DESIGN §25): a live tick
    #: sooner than that leaves the plans for a later one, unless the archive is not all pushed. 0 archives every tick.
    #: Private, as `plan_archive` is: it sets how often the operator's remote is pushed to.
    plan_archive_every_minutes: Annotated[Count, Scope.PRIVATE] = 360


class Personas(Section):
    """The `[personas]` table: the persona each agent writes in (DESIGN §31), by name.

    Private: a persona is instructions in every run it reaches, so a shared workspace file chooses none (TRUST_MODEL
    T7). A name is checked for its shape here, not for a file: a run whose persona has none is refused when it starts.
    """

    #: Every `implement` and `resume`, public and private.
    worker: Annotated[PersonaName, Scope.PRIVATE] = DEFAULT_PERSONA
    #: Every plan.
    planner: Annotated[PersonaName, Scope.PRIVATE] = DEFAULT_PERSONA
    #: Every review.
    reviewer: Annotated[PersonaName, Scope.PRIVATE] = DEFAULT_PERSONA
    #: The personas each of the loop's own PRs is reviewed in at a commit, one review each, in place of `reviewer`'s
    #: one; none leaves it to `reviewer`. Each review counts against `policy.max_reviews_per_pr`.
    reviewers: Annotated[tuple[PersonaName, ...], Scope.PRIVATE, AfterValidator(_distinct_personas)] = ()


# A sink's name is a table name and appears in `canopy notify test` and the journal (DESIGN §20).
SINK_NAME_RE = re.compile(r"[a-z][a-z0-9-]*")
MAX_SINKS = 5
# The event groups a sink may take. `attention` is the attention list's diff; the others are point events.
EventGroup = Literal["attention", "loop", "runs", "chores", "reviews", "tasks", "replies"]
# The sink `notify.cmd` stands for.
DEFAULT_SINK = "default"
MIN_DIGEST_MINUTES = 60
# A sink batching for longer than a day would hold everything but what needs the operator now.
MAX_BATCH_MINUTES = 1440


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
    #: In US dollars: a due digest waits until the runs since the last one cost at least this much, so the sink hears
    #: once per this much spent, at most once per interval. Such a sink's digests are no heartbeat.
    digest_min_usd: Annotated[StrictFloat | StrictInt, Field(gt=0)] | None = None
    # After a delivery, what does not need the operator now waits this long, then goes out in one message.
    batch_minutes: Annotated[StrictInt, Field(ge=1, le=MAX_BATCH_MINUTES)] | None = None

    @model_validator(mode="after")
    def _floor_needs_digests(self) -> Sink:
        if self.digest_min_usd is not None and self.digest_every_minutes is None:
            raise ValueError("digest_min_usd needs digest_every_minutes: it holds back digests, and none are sent")
        return self


SinkName = Annotated[str, AfterValidator(_sink_name)]


class Notify(Section):
    """The `[notify]` table."""

    # Receives the attention diff on stdin. Split into argv like the runtime templates, with no `{prompt}`. Shorthand
    # for a sink named `default` that takes the attention list as text (DESIGN §20).
    cmd: Annotated[NotifyCommand, Scope.PRIVATE] = ""
    sinks: Annotated[dict[SinkName, Sink], Scope.PRIVATE] = {}

    @model_validator(mode="after")
    def _one_default(self) -> Notify:
        if self.cmd and DEFAULT_SINK in self.sinks:
            raise ValueError(f"set notify.cmd or [notify.sinks.{DEFAULT_SINK}], not both: notify.cmd is that sink")
        if len(self.all_sinks()) > MAX_SINKS:
            raise ValueError(f"at most {MAX_SINKS} sinks, counting notify.cmd: each can hold the tick lock 60 seconds")
        return self

    def all_sinks(self) -> dict[str, Sink]:
        """Every sink by name, in name order, `notify.cmd` included as `default`.

        Returns:
            The configured sinks, plus a text sink for attention events running `notify.cmd` when it is set.
        """
        found = dict(self.sinks)
        if self.cmd:
            found[DEFAULT_SINK] = Sink(cmd=self.cmd, format="text", events=("attention",))
        return dict(sorted(found.items()))

    def takes(self, group: str) -> bool:
        """Whether any sink takes `group`: events of a group no sink takes are not recorded.

        Returns:
            True when at least one sink's `events` names `group`.
        """
        return any(group in sink.events for sink in self.all_sinks().values())


# A source's name is a table name, as a sink's is (ROADMAP M36).
SOURCE_NAME_RE = SINK_NAME_RE
# The commands a `vcs` source runs when none is configured: canopy's own GitHub programs (DESIGN §29).
GITHUB_READER = "canopy-connect-github"
GITHUB_POSTER = "canopy-post-github"
# The name canopy's own `vcs` source goes by when none is configured, in `connector_runs` and `canopy status`.
DEFAULT_SOURCE = "github"
#: Why config refuses a workspace with no `tracker` source that reads: the overseer reads the tracker no longer, so it
#: could do nothing with a ticket no source observes (DESIGN §30, §39).
TRACKER_REQUIRED = (
    'a tracker source is required: add a [connect.sources.<name>] table with kind = "tracker" and a cmd that reads '
    'your tracker, such as "canopy-connect-jira --site acme.atlassian.net" or "canopy-connect-github --repo '
    "OWNER/NAME\", to the workspace's private config or your user config (DESIGN §30)"
)
#: The order a tick runs the sources in, by kind: the `vcs` run is also the reconcile read of the drafts (DESIGN §29).
_SOURCE_ORDER = ("tracker", "vcs", "artifacts", "slack")
#: A person's Slack user id, as a `slack` source's `operators` names one: `U...`, or `W...` on an Enterprise Grid.
SLACK_USER_RE = re.compile(r"[UW][A-Z0-9]{2,30}")


def _slack_user(value: str) -> str:
    if not SLACK_USER_RE.fullmatch(value):
        raise ValueError(f"{value!r} is not a Slack user id, such as U0123ABCD: copy it from the person's profile")
    return value


def _source_name(value: str) -> str:
    if not SOURCE_NAME_RE.fullmatch(value):
        raise ValueError(f"source name {value!r} must match {SOURCE_NAME_RE.pattern}")
    return value


class Source(Section):
    """One `[connect.sources.<name>]` table: the programs that read one source and post to it (DESIGN §29).

    Each command is split into argv with shell word rules, as a sink's is, and runs with no shell. The request arrives
    on stdin, so neither takes a placeholder.
    """

    kind: Literal["vcs", "tracker", "artifacts", "slack"]
    # Reads the source: for `vcs`, a PR's reviews and threads; for `artifacts`, a store's comment feed; for `slack`,
    # the replies in the Slack sink's ticket threads. Empty for a source canopy only posts to.
    cmd: NotifyCommand = ""
    # Posts what the operator approved: for `vcs`, a PR's drafts; for `tracker`, a ticket's.
    post_cmd: NotifyCommand = ""
    timeout_minutes: Minutes = 2
    #: The ids whose words are the operator's own messages, as `canopy reply` records one (DESIGN §22, TRUST_MODEL
    #: T1): for a `slack` source, the Slack user ids whose replies in the sink's ticket threads are; for a `tracker`
    #: source, the tracker account ids whose comments on a private ticket are. Empty for none.
    operators: tuple[NonBlank, ...] = ()

    @model_validator(mode="after")
    def _a_command(self) -> Source:
        if not notify_words(self.cmd) and not notify_words(self.post_cmd):
            raise ValueError("set cmd, post_cmd, or both")
        if self.kind == "vcs" and not notify_words(self.cmd):
            raise ValueError("a vcs source needs cmd: drafts are checked against what it reads")
        if self.kind == "artifacts" and (not notify_words(self.cmd) or notify_words(self.post_cmd)):
            raise ValueError("an artifacts source needs cmd, and takes no post_cmd: workers reply through the store")
        if self.kind == "slack" and (not notify_words(self.cmd) or notify_words(self.post_cmd) or not self.operators):
            raise ValueError("a slack source needs cmd and operators, and takes no post_cmd: the sink posts")
        if self.kind not in ("slack", "tracker") and self.operators:
            raise ValueError(
                "operators is a slack or tracker source's: whose replies in the sink's threads, or comments on a "
                "private ticket, are the operator's",
            )
        if self.kind == "slack":
            for user in self.operators:
                _slack_user(user)
        return self


SourceName = Annotated[str, AfterValidator(_source_name)]


class Connect(Section):
    """The `[connect]` table: the programs canopy reads the world with and posts through (DESIGN §29, ROADMAP M36).

    Private: each runs a command on the operator's machine with the operator's credentials (TRUST_MODEL T7).
    """

    sources: Annotated[dict[SourceName, Source], Scope.PRIVATE] = {}
    #: An observation older than this is stale (DESIGN §30): `canopy status` marks it so.
    max_age_minutes: Annotated[Minutes, Scope.PRIVATE] = 30
    #: How often `canopy loop` polls the connectors between ticks, apart from how often it ticks (DESIGN §6).
    every_minutes: Annotated[Minutes, Scope.PRIVATE] = 2

    @model_validator(mode="after")
    def _one_per_kind(self) -> Connect:
        kinds = [source.kind for source in self.sources.values()]
        if len(kinds) != len(set(kinds)):
            raise ValueError("at most one source of each kind, tracker, vcs, artifacts, and slack")
        tracker = self._of("tracker")
        if tracker is None or not notify_words(tracker.cmd):
            raise ValueError(TRACKER_REQUIRED)
        if self.max_age_minutes < self.every_minutes:
            raise ValueError("max_age_minutes must be at least every_minutes")
        return self

    def named(self) -> dict[str, Source]:
        """Each source that reads, by name, in the order a tick runs them: `tracker`, `vcs`, `artifacts`, `slack`.

        Returns:
            The sources with a `cmd`, canopy's own GitHub reader named `github` when no `vcs` source is configured.
        """
        found = {name: s for name, s in self.sources.items() if notify_words(s.cmd)}
        if self._of("vcs") is None:
            found[DEFAULT_SOURCE if DEFAULT_SOURCE not in found else f"{DEFAULT_SOURCE}-vcs"] = self.vcs()
        return dict(sorted(found.items(), key=lambda item: (_SOURCE_ORDER.index(item[1].kind), item[0])))

    def vcs(self) -> Source:
        """The `vcs` source: the operator's, or canopy's own GitHub reader and poster.

        Returns:
            The source.
        """
        found = self._of("vcs")
        return found or Source(kind="vcs", cmd=GITHUB_READER, post_cmd=GITHUB_POSTER)

    def tracker(self) -> Source:
        """The `tracker` source, which config requires (`_one_per_kind`); canopy configures none of its own.

        Returns:
            The source.
        """
        return next(source for source in self.sources.values() if source.kind == "tracker")

    def _of(self, kind: str) -> Source | None:
        return next((source for source in self.sources.values() if source.kind == kind), None)


#: The tools of an artifact store an agent that publishes may call, by the names the store's contract gives them
#: (DESIGN §38, `packages/canopy-artifacts`): all but `comment_feed`, which is for the source that reads comments back.
ARTIFACT_TOOLS = (
    "artifact_publish",
    "artifact_read",
    "artifact_list",
    "thread_list",
    "comment_reply",
    "comment_create",
    "thread_resolve",
)
#: The agents `artifacts.publish_roles` may name, by the name it keys them by, as `runtime.allow_bash` keys them.
PUBLISH_ROLES: Mapping[str, str] = {"worker": agents.WORKER}
#: The agents that never publish, by that name, and why (DESIGN §38).
REFUSED_PUBLISH_ROLES: Mapping[str, str] = {
    "worker-private": "a private ticket's worker never publishes, so nothing of a private ticket reaches a store",
    "planner": "the planner writes one file, its plan, and nothing else",
}


def _publish_role(value: str) -> str:
    if value in REFUSED_PUBLISH_ROLES:
        raise ValueError(f"{value!r} cannot publish: {REFUSED_PUBLISH_ROLES[value]}")
    if value not in PUBLISH_ROLES:
        raise ValueError(f"{value!r} is not an agent that may publish; name one of {', '.join(PUBLISH_ROLES)}")
    return value


PublishRole = Annotated[StrictStr, AfterValidator(_publish_role)]


class Artifacts(Section):
    """The `[artifacts]` table: the store workers publish artifacts to, and which of canopy's agents may (DESIGN §38).

    Off unless `mcp_server` is set. Private (TRUST_MODEL T7): it chooses which agents may send what they read to a
    store off the machine, and whose comments there steer a worker.
    """

    #: The store's MCP server, as the operator's runtime config names it: Louvre's, or the local store's. Empty for
    #: none, and then no definition names one.
    mcp_server: Annotated[StrictStr, Scope.PRIVATE, AfterValidator(_server_name)] = ""
    #: The namespace canopy's artifacts are in, as the server's token or `--namespace` binds it. Empty for unset.
    namespace: Annotated[StrictStr, Scope.PRIVATE] = ""
    #: The store's ids of the people whose comments are authority, as an authorized replier's are (DESIGN §38).
    authorized_authors: Annotated[tuple[NonBlank, ...], Scope.PRIVATE] = ()
    #: The agents that may publish, by the names `PUBLISH_ROLES` keys them by. Every other one is denied the server.
    publish_roles: Annotated[tuple[PublishRole, ...], Scope.PRIVATE] = ()

    def publishing(self) -> agents.Publishing | None:
        """The store's server, the tools a publishing agent may call, and those agents, for their definitions.

        Returns:
            The rules to render, or None when no store is configured.
        """
        if not self.mcp_server:
            return None
        agent_names = frozenset(PUBLISH_ROLES[role] for role in self.publish_roles)
        return agents.Publishing(self.mcp_server, ARTIFACT_TOOLS, agent_names)


CHORE_DAYS = ("mon", "tue", "wed", "thu", "fri", "sat", "sun")  # by `datetime.weekday()`
ChoreDay = Literal["mon", "tue", "wed", "thu", "fri", "sat", "sun"]
_HOURS_RE = re.compile(r"([01]\d|2[0-3]):([0-5]\d)-([01]\d|2[0-4]):([0-5]\d)")
_DAY_MINUTES = 24 * 60


def chore_hours(value: str) -> tuple[int, int]:
    """Read a chore's `hours`, `HH:MM-HH:MM`, as minutes after midnight: the start, and the end, which may be 24:00.

    Returns:
        The start and the end, each in minutes after midnight. The end is after the start and at most 1440.

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
    #: Its own model, spelled as a `runtime.models` value, in place of `runtime.models.chore`: canopy runs it on a copy
    #: of the chore's agent made for it, `canopy-chore-<name>`, with this model (DESIGN §13, §19). Its command, its
    #: `cmd` or `runtime.chore_cmd`, must run the chore's agent; one of the operator's own takes its model in its own
    #: definition.
    model: ModelId | None = None
    every_minutes: Annotated[StrictInt, Field(ge=MIN_CHORE_EVERY_MINUTES)]
    when: StrictStr = ""
    # When a run may start, checked in code: the days of the week, empty for every day; the hours of each, as
    # `HH:MM-HH:MM`; and the zone they are in, an IANA name, by default this machine's local time.
    days: Annotated[tuple[ChoreDay, ...], AfterValidator(_days)] = ()
    hours: Annotated[StrictStr, AfterValidator(_chore_hours)] | None = None
    timezone: Annotated[StrictStr, AfterValidator(_time_zone)] | None = None
    # The most findings a run lists, the most important first; the rest it only counts (DESIGN §19).
    max_findings: Annotated[StrictInt, Field(ge=1, le=chore_result.MAX_FINDINGS)] = chore_result.DEFAULT_MAX_FINDINGS
    timeout_minutes: Minutes = 15
    cwd: UserPath | None = None
    # The workspaces it runs in, by name; empty means every workspace whose loop reads this file.
    workspaces: tuple[NonBlank, ...] = ()

    @model_validator(mode="after")
    def _model_and_cmd(self) -> Chore:
        # A model on the command line would beat the one canopy writes, so it is refused wherever canopy chooses one:
        # with `model`, or on the chore's agent, whose model is `runtime.models.chore`. An agent of the operator's own
        # is the operator's to run on any model, as before.
        if self.cmd is None:
            return self
        runs_chore = invocation.agent_of(self.cmd) == agents.CHORE
        if self.model is not None and not runs_chore:
            raise ValueError(
                f"model needs cmd to run canopy's chore agent, {agents.CHORE}, which canopy copies for this chore "
                "with its model; an agent of your own takes its model in its own definition. Drop model, or run "
                f"--agent {agents.CHORE}",
            )
        if self.model is not None and DEFINITIONS_DIR not in self.cmd:
            raise ValueError(
                f"with model, cmd must contain {DEFINITIONS_DIR}, where the chore's copy of {agents.CHORE} is (D040)",
            )
        if self.model is not None or runs_chore:
            try:
                _refuse_model_option(self.cmd, "Set model in this table instead")
            except ValueError as e:
                raise ValueError(f"cmd {e}") from None
        return self


ChoreName = Annotated[str, AfterValidator(_chore_name)]


class Config(Section):
    """The merged, validated configuration."""

    tracker: Tracker
    policy: Policy
    trust: Trust
    capacity: Capacity
    pools: Pools
    runtime: Runtime
    loop: Loop
    review: Review
    paths: Paths
    notify: Notify
    serve: Serve
    memory: Memory
    retention: Retention
    connect: Connect
    personas: Personas
    artifacts: Artifacts
    spend: Spend
    telemetry: Telemetry
    # Tables of tables, keyed by name; private as a whole (TABLE_SECTIONS).
    chores: Annotated[dict[ChoreName, Chore], Scope.PRIVATE] = {}

    @model_validator(mode="after")
    def _chore_models_run_the_chore_agent(self) -> Config:
        # A chore with a model and no `cmd` runs `runtime.chore_cmd` on its own copy of the chore's agent.
        if invocation.agent_of(self.runtime.chore_cmd) == agents.CHORE:
            return self
        for name, chore in self.chores.items():
            if chore.model is not None and chore.cmd is None:
                raise ValueError(
                    f"chores.{name}.model needs runtime.chore_cmd to run canopy's chore agent, {agents.CHORE}, which "
                    "canopy copies for the chore with its model, or a cmd of the chore's own that does",
                )
        return self

    @property
    def reviews_on(self) -> bool:
        """Whether reviews run at all: `max_reviews` above 0 and something to review (DESIGN §21)."""
        return self.capacity.max_reviews > 0 and (self.review.agent_prs or bool(self.review.query.strip()))


SECTIONS: dict[str, type[Section]] = {
    "tracker": Tracker,
    "policy": Policy,
    "trust": Trust,
    "capacity": Capacity,
    "pools": Pools,
    "runtime": Runtime,
    "loop": Loop,
    "review": Review,
    "paths": Paths,
    "notify": Notify,
    "serve": Serve,
    "memory": Memory,
    "retention": Retention,
    "connect": Connect,
    "personas": Personas,
    "artifacts": Artifacts,
    "spend": Spend,
    "telemetry": Telemetry,
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
    """`$XDG_CONFIG_HOME/canopy`, or `~/.config/canopy` when XDG_CONFIG_HOME is unset or empty.

    Returns:
        The directory the user config file and its prompt overrides are in, with `~` expanded. It may not exist.
    """
    base = os.environ.get("XDG_CONFIG_HOME") or str(Path.home() / ".config")
    return Path(base).expanduser() / "canopy"


def user_config_path() -> Path:
    """Return the user config file's path."""
    return user_config_dir() / CONFIG_FILE_NAME


def private_config_path(root: Path) -> Path:
    """Return the private config file's path for the workspace at `root`: in its state directory (DESIGN §12)."""
    return root.absolute() / WORKSPACE_STATE_DIR / CONFIG_FILE_NAME


def load(
    root: Path,
    user_file: Path | None = None,
    runner: procs.Runner | None = None,
    *,
    private_file: Path | None = None,
) -> Config:
    """Read and validate the layered config for the workspace at `root`: workspace file, user file, private file.

    No code repository's file is read (D016). The workspace file's map tables are `canopy.core.workspace`'s to read.
    `runner` runs the git that checks the state directory came from no checkout; None means the real one.
    `private_file` stands in for the private file, as the settings page's edited copy beside it does; None means the
    workspace's own.

    Returns:
        The validated config, each key from the last file that sets it.

    Raises:
        ConfigError: git tracks a file in the state directory, or cannot say whether it does; the workspace file sets
            a private key; neither the user file nor the private file exists; the private file is not the operator's
            alone; a file cannot be read or is not valid TOML; a key is unknown or removed; or a value does not
            validate.
    """
    files = config_files(root, user_file)
    shared_file, user_file, _ = files
    if private_file is not None:
        files = (shared_file, user_file, private_file)
    layers = _layers(root, files, runner)
    merged, origin = _merge(layers, shared_file)
    # Unset or empty: `prompts/` in the user config directory.
    if merged["paths"].get("prompt_overrides", "") == "":
        merged["paths"]["prompt_overrides"] = str(user_file.parent / "prompts")

    try:
        return Config.model_validate(merged)
    except ValidationError as e:
        raise ConfigError(_describe(e, origin, files)) from e


def config_files(root: Path, user_file: Path | None = None) -> tuple[Path, Path, Path]:
    """Return the files `load` reads for the workspace at `root`, in the order it merges them.

    Returns:
        The workspace file, the user file (`user_file`, or the one in the user config directory), and the private file.
        Any of them may not exist.
    """
    return root / WORKSPACE_FILE_NAME, user_file or user_config_path(), private_config_path(root)


def origins(root: Path, user_file: Path | None = None, runner: procs.Runner | None = None) -> dict[str, Path]:
    """Return the file each key's value comes from, as `load` merges them; a key set in no file is its default's.

    A table section, such as `chores`, is one key, from the last file that has it. A workspace file's policy value that
    does not tighten the default is not its value, so it is not its origin either.

    Returns:
        The file by `section.key` name, for each key some file sets.

    Raises:
        ConfigError: as `load` raises it for the files, before any value is validated.
    """
    files = config_files(root, user_file)
    return _merge(_layers(root, files, runner), files[0])[1]


def check_untracked(runner: procs.Runner, root: Path) -> None:
    """Refuse the workspace at `root` if git tracks any file in its state directory.

    D053 checks the state directory's permissions, not where it came from, and a `.canopy/` checked out under umask 077
    passes it. One from a checkout could hold a private file that runs commands, or a journal someone else wrote.

    Raises:
        ConfigError: git tracks a file there, or `root` is in a repository git cannot read.
    """
    state_dir = root.absolute() / WORKSPACE_STATE_DIR
    found = hostgit.tracked(runner, root, WORKSPACE_STATE_DIR)
    if found is None:
        raise ConfigError(
            f"{root} is in a git repository, and git could not list what it tracks in {state_dir}: canopy uses no "
            f"state that may have come from a checkout. Run `git ls-files {WORKSPACE_STATE_DIR}` there to see why.",
        )
    if found:
        raise ConfigError(
            f"{root / found[0]} is tracked by git: {state_dir} must be yours alone, and one from a checkout could run "
            f"commands or supply a journal. Remove it from the repository (`git rm -r --cached {WORKSPACE_STATE_DIR}`) "
            "and check what it holds before running canopy.",
        )


def _layers(
    root: Path,
    files: tuple[Path, Path, Path],
    runner: procs.Runner | None,
) -> tuple[tuple[Path, dict[str, object]], ...]:
    """Read each file `load` merges, checked as it checks them, into its keys by `section.key` name.

    Returns:
        Each file and its keys, in the order `load` merges them.

    Raises:
        ConfigError: as `load` raises it, for everything but a value that does not validate.
    """
    shared_file, user_file, private_file = files
    check_untracked(runner or procs.SubprocessRunner(), root)
    shared: dict[str, object] = _read(shared_file, skip=WORKSPACE_MAP_TABLES) if shared_file.exists() else {}
    for name in shared:
        if SPECS[name].scope is Scope.PRIVATE:
            raise ConfigError(
                f"{shared_file}: {name} is private and cannot be set in the workspace file; set it in {private_file}, "
                f"or in {user_file} for every workspace",
            )
    user_values = _read(user_file) if user_file.exists() else None
    private_values = _read_private(private_file)
    if user_values is None and private_values is None:
        raise ConfigError(f"no config at {private_file} or {user_file}; run `canopy init` in the workspace")
    private_values = {
        name: _in_state_dir(value, private_file.parent) if name.startswith("paths.") else value
        for name, value in (private_values or {}).items()
    }
    return ((shared_file, shared), (user_file, user_values or {}), (private_file, private_values))


def _merge(
    layers: Iterable[tuple[Path, Mapping[str, object]]],
    shared_file: Path,
) -> tuple[dict[str, dict[str, object]], dict[str, Path]]:
    """Merge the files' keys in order, later files winning. Returns the merged sections and each key's file.

    Returns:
        The merged keys by section, and the file each key's value came from by `section.key` name. A workspace file's
        policy value that does not tighten the default is left out of both.
    """
    merged: dict[str, dict[str, object]] = {section: {} for section in (*SECTIONS, *TABLE_SECTIONS)}
    origin: dict[str, Path] = {}
    for source, values in layers:
        for name, value in values.items():
            spec = SPECS[name]
            if source == shared_file and spec.tighten is not None and not _stricter(spec, value):
                continue
            origin[name] = source
            if isinstance(value, dict) and name in TABLE_SECTIONS:
                # A table of tables, such as every `[chores.<name>]`: the last file's replaces any other whole.
                merged[name] = {str(k): v for k, v in value.items()}
                continue
            section, key = name.split(".", 1)
            merged[section][key] = value
    return merged, origin


def _read(path: Path, *, skip: Collection[str] = ()) -> dict[str, object]:
    """Return the file's config keys as `section.key` names. Tables named in `skip` are someone else's to read.

    Raises:
        ConfigError: The file cannot be read or is not valid TOML, or it has a key that is unknown or was removed.
    """
    try:
        with path.open("rb") as f:
            doc = tomllib.load(f)
    except tomllib.TOMLDecodeError as e:
        raise ConfigError(f"{path}: {e}") from e
    except OSError as e:
        raise ConfigError(f"{path}: {e.strerror}") from e
    return _keys(path, doc, skip)


def _read_private(path: Path) -> dict[str, object] | None:
    """Return the private file's config keys, as `_read` does, or None if there is none.

    It is opened without following a symlink, and must be a regular file of the operator's that no one else can write.

    Raises:
        ConfigError: It is a symlink, not a regular file, someone else's, or group or world writable; or it cannot be
            read, is not valid TOML, or has a key that is unknown or was removed.
    """
    try:
        fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
    except FileNotFoundError:
        return None
    except OSError as e:
        why = "a symlink" if path.is_symlink() else e.strerror
        raise ConfigError(f"{path}: {why}; canopy reads it only as a regular file of yours") from e
    st = os.fstat(fd)
    if not stat.S_ISREG(st.st_mode) or st.st_uid != os.getuid() or st.st_mode & 0o022:
        os.close(fd)
        raise ConfigError(
            f"{path} is not private to you: canopy reads it only as a regular file of yours that no one else can "
            "write. If you did not write it, remove it; if you did, `chmod go-w` it.",
        )
    try:
        with os.fdopen(fd, "rb") as f:
            doc = tomllib.load(f)
    except tomllib.TOMLDecodeError as e:
        raise ConfigError(f"{path}: {e}") from e
    except OSError as e:
        raise ConfigError(f"{path}: {e.strerror}") from e
    return _keys(path, doc)


def _in_state_dir(value: object, state_dir: Path) -> object:
    """Resolve a private file's relative `paths.*` value against the state directory.

    Not the workspace root, which may be a shared checkout (TRUST_MODEL T7). Empty stays empty: for
    `paths.prompt_overrides` it means the default, and for any other key it is refused as it is in the user file.

    Returns:
        A relative path's string under `state_dir`; any other value as it is, for validation to judge.
    """
    if not isinstance(value, str) or not value or value.startswith("~") or Path(value).is_absolute():
        return value
    return str(state_dir / value)


def _keys(path: Path, doc: Mapping[str, object], skip: Collection[str] = ()) -> dict[str, object]:
    """Return a parsed file's config keys as `section.key` names, tables named in `skip` left out.

    Raises:
        ConfigError: it has a key that is unknown or was removed.
    """
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


def _describe(error: ValidationError, origin: Mapping[str, Path], files: tuple[Path, Path, Path]) -> str:
    shared_file, user_file, private_file = files
    lines: list[str] = []
    for e in error.errors():
        loc = [str(p) for p in e["loc"] if p != "[key]"]
        if not loc:
            # A check across sections, whose message names its keys.
            lines.append(e["msg"])
            continue
        if loc[0] in TABLE_SECTIONS:
            # A named table's errors are about one of its keys: `chores.build-health.every_minutes`.
            source = origin.get(loc[0])
            prefix = f"{source}: " if source is not None else ""
            lines.append(f"{prefix}{'.'.join(loc[:3])}{''.join(f'[{p}]' for p in loc[3:])}: {e['msg']}")
            continue
        name = ".".join(loc[:2])
        where = name + "".join(f"[{p}]" for p in loc[2:])
        if e["type"] == "missing":
            where_set = (
                f"{private_file} or {user_file}"
                if SPECS[name].scope is Scope.PRIVATE
                else f"{shared_file}, {private_file}, or {user_file}"
            )
            lines.append(f"missing required key {name}; set it in {where_set}")
        else:
            source = origin.get(name)
            prefix = f"{source}: " if source is not None else ""
            lines.append(f"{prefix}{where}: {e['msg']}")
    return "\n".join(lines)


def changed(old: Config, new: Config) -> list[str]:
    """The keys whose values differ from `old` to `new`, as `section.key` names, in the schema's order.

    A table section, such as `chores`, is one key: any change to any of its tables names it.

    Returns:
        The changed keys, empty when nothing changed.
    """
    return [name for name in SPECS if _value(old, name) != _value(new, name)]


def _value(cfg: Config, name: str) -> object:
    section, _, key = name.partition(".")
    values: object = getattr(cfg, section)
    return getattr(values, key) if key else values


@dataclass(frozen=True)
class Rendered:
    """A command template rendered for one run: what to start, and what to write on its stdin."""

    #: The argv to run, with every placeholder replaced.
    argv: Sequence[str]
    #: The prompt, when the template places no `{prompt}`; None when it is in `argv`, and stdin is `/dev/null`.
    stdin: str | None


def render_command(template: str, prompt: str, definitions_dir: Path, title: str) -> Rendered:
    """Turn a command template into argv, and the prompt into an argument or stdin. No shell runs (D023).

    The template is split with shell word rules, then `{prompt}`, `{definitions_dir}`, and `{title}` are replaced inside
    each word, in one pass, so no value is searched for another placeholder. The prompt therefore lands in exactly one
    argument, whatever it contains, or, when the template places none, on stdin, where no argument limit applies
    (Linux's is 128 KiB). Every title starts with a letter or digit, so even as a word of its own it is never read as
    an option.

    Returns:
        The argv to run, with every placeholder replaced, and the prompt as stdin when no argument carries it.
    """
    words = command_words(template)
    values = {PROMPT: prompt, DEFINITIONS_DIR: str(definitions_dir), TITLE: title}
    argv = [_PLACEHOLDER_RE.sub(lambda m: values[m.group(0)], w) for w in words]
    return Rendered(argv, None if any(PROMPT in w for w in words) else prompt)
