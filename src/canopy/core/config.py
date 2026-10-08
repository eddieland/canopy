"""Layered configuration: built-in defaults, then the shared file, then the user's `config.toml`.

The shared file is the workspace's `canopy-workspace.toml` in a workspace, and the repository's `canopy.toml` in a
workspace of one (DESIGN §18). Both are the "repository file" of what follows.

Every key has a scope (DESIGN §12). A shared key may be set in either file and the user file wins. A user-only key may
be set only in the user file; a repository file that sets one is an error, because anyone who can push to the
repository controls that file (TRUST_MODEL T7). Unknown keys are errors in both files. Repository `policy.*` values
apply only when stricter than the built-in defaults.

The models below are the schema: each field carries its type, default, and scope, and policy fields say which
direction is stricter. `load` enforces scopes and the tighten rule per file, merges, then lets pydantic validate
(D026).
"""

from __future__ import annotations

import os
import re
import shlex
import tomllib
from dataclasses import dataclass
from enum import Enum
from pathlib import Path
from typing import TYPE_CHECKING, Annotated, Literal, get_args

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

if TYPE_CHECKING:
    from pydantic.fields import FieldInfo

REPO_FILE_NAME = "canopy.toml"
WORKSPACE_FILE_NAME = "canopy-workspace.toml"
# A workspace's state is always here, under its root; `paths.state_dir` applies only to a workspace of one.
WORKSPACE_STATE_DIR = ".canopy"
# Tables of the workspace file that are its map, not config. `canopy.core.workspace` reads them.
WORKSPACE_MAP_TABLES = ("workspace", "repos")
PROMPT = "{prompt}"
# Replaced with the snapshot of canopy's agent definitions and skills (D040).
DEFINITIONS_DIR = "{definitions_dir}"
DEFINITIONS_ENV_PREFIX = f"env OPENCODE_CONFIG_DIR={DEFINITIONS_DIR} "
_PLACEHOLDER_RE = re.compile(r"\{prompt\}|\{definitions_dir\}")
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
    """For repository policy: which direction is stricter than the default."""

    LOWER = "lower"
    HIGHER = "higher"
    # For a field typed as a Literal of choices listed from loosest to strictest: a later choice is stricter.
    LATER = "later"


def _non_blank(value: str) -> str:
    if not value.strip():
        raise ValueError("must not be empty")
    return value


# One or more plain ref components, each followed by "/". Branch names reach git's argv, so none may start with "-" or
# hold anything git treats specially ("..", "@{", a leading "."). The repository file can set this key (TRUST_MODEL T7).
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


def _user_path(value: Path) -> Path:
    # A relative path would resolve against the working directory, which is the repository: its files would stand in
    # for the operator's prompts or state (TRUST_MODEL T7). `Path("")` is `.`, so an empty value is refused here too.
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
UserPath = Annotated[Path, AfterValidator(_user_path)]


class Section(BaseModel):
    """Base for config tables: unknown keys are errors, values are frozen, defaults are validated."""

    # validate_default: defaults go through the same validators as file values, so `~/.canopy` is expanded.
    model_config = ConfigDict(extra="forbid", frozen=True, validate_default=True)


class Tracker(Section):
    """The `[tracker]` table."""

    provider: Annotated[NonBlank, Scope.SHARED]
    query: Annotated[NonBlank, Scope.SHARED]
    needs_human_label: Annotated[NonBlank, Scope.SHARED] = "needs-human"
    labels: Annotated[tuple[NonBlank, ...], Scope.USER, Field(min_length=1)]


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
    # Whether the overseer may stack a ticket on its blocker's open PR (DESIGN §10, D054). Prompt policy, not a guard.
    stacking: Annotated[Literal["auto", "never"], Scope.SHARED, Tighten.LATER] = "auto"


class Trust(Section):
    """The `[trust]` table."""

    branch_prefix: Annotated[StrictStr, Scope.SHARED, AfterValidator(_branch_prefix)] = "agent/"
    pr_label: Annotated[NonBlank, Scope.SHARED] = "agent"
    authorized_repliers: Annotated[tuple[NonBlank, ...], Scope.USER] = ()
    # What every worker comment starts and ends with, when set (DESIGN §8, D069). They only take authority away, from
    # the comments that carry them; user-only, so a repository cannot pick marks that silence people's comments.
    comment_prefix: Annotated[StrictStr, Scope.USER, AfterValidator(_comment_mark)] = "CANOPY:"
    comment_suffix: Annotated[StrictStr, Scope.USER, AfterValidator(_comment_mark)] = ""

    @model_validator(mode="after")
    def _one_comment_mark(self) -> Trust:
        # With neither, a worker's comment reads as the operator's, and its PR replies as new review feedback.
        if not self.comment_prefix and not self.comment_suffix:
            raise ValueError("set trust.comment_prefix, trust.comment_suffix, or both: workers mark their comments")
        return self


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
        "env OPENCODE_CONFIG_DIR={definitions_dir} opencode run --agent canopy-overseer {prompt}"
    )
    worker_cmd: Annotated[AgentTemplate, Scope.USER] = (
        "env OPENCODE_CONFIG_DIR={definitions_dir} opencode run --agent canopy-worker --format json {prompt}"
    )
    # The splitter is its own agent, with no edit or shell tools (DESIGN §18); it shares the worker's timeout.
    split_cmd: Annotated[AgentTemplate, Scope.USER] = (
        "env OPENCODE_CONFIG_DIR={definitions_dir} opencode run --agent canopy-splitter --format json {prompt}"
    )
    # A chore's default command; a chore that runs the operator's own tools sets its own (DESIGN §19).
    chore_cmd: Annotated[AgentTemplate, Scope.USER] = (
        "env OPENCODE_CONFIG_DIR={definitions_dir} opencode run --agent canopy-chore {prompt}"
    )
    # The reviewer; pointing it at a different model from the worker's is recommended (DESIGN §21).
    review_cmd: Annotated[AgentTemplate, Scope.USER] = (
        "env OPENCODE_CONFIG_DIR={definitions_dir} opencode run --agent canopy-reviewer {prompt}"
    )
    review_timeout_minutes: Annotated[Minutes, Scope.USER] = 20
    overseer_timeout_minutes: Annotated[Minutes, Scope.USER] = 15
    worker_timeout_minutes: Annotated[Minutes, Scope.USER] = 45


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


class Paths(Section):
    """The `[paths]` table."""

    # No static default: `load` supplies `prompts/` next to the user file, which depends on XDG_CONFIG_HOME.
    prompt_overrides: Annotated[UserPath, Scope.USER]
    state_dir: Annotated[UserPath, Scope.USER] = Path("~/.canopy")


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
    timeout_minutes: Minutes = 15
    cwd: UserPath | None = None
    # The workspaces it runs in, by name; empty means every workspace whose loop reads this file (D063).
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


def find_repo_root(start: Path) -> Path:
    """The nearest directory at or above `start` that contains `.git` (a directory, or a file in a worktree)."""
    start = start.resolve()
    for d in (start, *start.parents):
        if (d / ".git").exists():
            return d
    raise ConfigError(f"{start} is not inside a git repository")


def load(repo_root: Path, user_file: Path | None = None) -> Config:
    """Read and validate the layered config for the workspace at `repo_root`.

    A `canopy-workspace.toml` at `repo_root` is the shared layer, and its state directory is `<repo_root>/.canopy`
    whatever `paths.state_dir` says. Without one, the repository's `canopy.toml` is, as it always was.
    """
    user_file = user_file or user_config_path()
    workspace_file = repo_root / WORKSPACE_FILE_NAME
    in_workspace = workspace_file.is_file()
    repo_file = workspace_file if in_workspace else repo_root / REPO_FILE_NAME

    skip = WORKSPACE_MAP_TABLES if in_workspace else ()
    repo_values: dict[str, object] = _read(repo_file, skip=skip) if repo_file.exists() else {}
    for name in repo_values:
        if SPECS[name].scope is Scope.USER:
            raise ConfigError(
                f"{repo_file}: {name} is user-only and cannot be set in the repository file; set it in {user_file}"
            )
    if not user_file.exists():
        raise ConfigError(f"no user config at {user_file}; run `canopy init`")
    user_values = _read(user_file)

    merged, origin = _merge(((repo_file, repo_values), (user_file, user_values)), repo_file)
    # Unset or empty: `prompts/` next to the user file.
    if merged["paths"].get("prompt_overrides", "") == "":
        merged["paths"]["prompt_overrides"] = str(user_file.parent / "prompts")
    if in_workspace:
        # Each workspace has its own journal and locks, so two workspaces never share a queue's state (DESIGN §18).
        merged["paths"]["state_dir"] = str(repo_root.absolute() / WORKSPACE_STATE_DIR)

    try:
        return Config.model_validate(merged)
    except ValidationError as e:
        raise ConfigError(_describe(e, origin, repo_file, user_file)) from e


def _merge(
    layers: tuple[tuple[Path, dict[str, object]], ...], repo_file: Path
) -> tuple[dict[str, dict[str, object]], dict[str, Path]]:
    """Merge the files' keys in order, later files winning. Returns the merged sections and each key's file."""
    merged: dict[str, dict[str, object]] = {section: {} for section in (*SECTIONS, *TABLE_SECTIONS)}
    origin: dict[str, Path] = {}
    for source, values in layers:
        for name, value in values.items():
            spec = SPECS[name]
            if source == repo_file and spec.tighten is not None and not _stricter(spec, value):
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
            if name not in SPECS:
                raise ConfigError(f"{path}: unknown key {name}")
            values[name] = raw
    return values


def _stricter(spec: KeySpec, value: object) -> bool:
    """Return whether a repository policy value may replace the default.

    A value of the wrong type is kept, so that validation reports it against the repository file instead of silently
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


def _describe(error: ValidationError, origin: dict[str, Path], repo_file: Path, user_file: Path) -> str:
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
            files = str(user_file) if SPECS[name].scope is Scope.USER else f"{repo_file} or {user_file}"
            lines.append(f"missing required key {name}; set it in {files}")
        else:
            source = origin.get(name)
            prefix = f"{source}: " if source is not None else ""
            lines.append(f"{prefix}{where}: {e['msg']}")
    return "\n".join(lines)


def render_command(template: str, prompt: str, definitions_dir: Path) -> list[str]:
    """Turn a command template into argv. No shell runs (D023).

    The template is split with shell word rules, then `{prompt}` and `{definitions_dir}` are replaced inside each word,
    in one pass, so neither value is searched for the other placeholder. The prompt therefore always lands in exactly
    one argument, whatever it contains.
    """
    values = {PROMPT: prompt, DEFINITIONS_DIR: str(definitions_dir)}
    return [_PLACEHOLDER_RE.sub(lambda m: values[m.group(0)], w) for w in command_words(template)]
