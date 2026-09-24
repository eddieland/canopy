"""Layered configuration: built-in defaults, then the repository's `canopy.toml`, then the user's `config.toml`.

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
from typing import TYPE_CHECKING, Annotated

from pydantic import AfterValidator, BaseModel, ConfigDict, Field, StrictInt, StrictStr, ValidationError

if TYPE_CHECKING:
    from pydantic.fields import FieldInfo

REPO_FILE_NAME = "canopy.toml"


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


class Trust(Section):
    """The `[trust]` table."""

    branch_prefix: Annotated[StrictStr, Scope.SHARED, AfterValidator(_branch_prefix)] = "agent/"
    pr_label: Annotated[NonBlank, Scope.SHARED] = "agent"
    authorized_repliers: Annotated[tuple[NonBlank, ...], Scope.USER] = ()


class Capacity(Section):
    """The `[capacity]` table."""

    max_workers: Annotated[Count, Scope.USER] = 2


class Runtime(Section):
    """The `[runtime]` table: agent command templates and timeouts."""

    overseer_cmd: Annotated[CommandTemplate, Scope.USER] = "opencode run --agent canopy-overseer {prompt}"
    worker_cmd: Annotated[CommandTemplate, Scope.USER] = "opencode run --agent canopy-worker {prompt}"
    overseer_timeout_minutes: Annotated[Minutes, Scope.USER] = 15
    worker_timeout_minutes: Annotated[Minutes, Scope.USER] = 45


class Loop(Section):
    """The `[loop]` table: how `canopy loop` paces ticks. Every tick runs the overseer, so this sets its spend."""

    interval_minutes: Annotated[Minutes, Scope.USER] = 15


class Paths(Section):
    """The `[paths]` table."""

    # No static default: `load` supplies `prompts/` next to the user file, which depends on XDG_CONFIG_HOME.
    prompt_overrides: Annotated[UserPath, Scope.USER]
    state_dir: Annotated[UserPath, Scope.USER] = Path("~/.canopy")


class Notify(Section):
    """The `[notify]` table."""

    # Receives the attention diff on stdin. Split into argv like the runtime templates, with no `{prompt}`.
    cmd: Annotated[NotifyCommand, Scope.USER] = ""


class Config(Section):
    """The merged, validated configuration."""

    tracker: Tracker
    policy: Policy
    trust: Trust
    capacity: Capacity
    runtime: Runtime
    loop: Loop
    paths: Paths
    notify: Notify


SECTIONS: dict[str, type[Section]] = {
    "tracker": Tracker,
    "policy": Policy,
    "trust": Trust,
    "capacity": Capacity,
    "runtime": Runtime,
    "loop": Loop,
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


def _spec(section: str, key: str, field: FieldInfo) -> KeySpec:
    scopes = [m for m in field.metadata if isinstance(m, Scope)]
    tightens = [m for m in field.metadata if isinstance(m, Tighten)]
    if len(scopes) != 1:
        raise TypeError(f"{section}.{key} must declare exactly one Scope")
    return KeySpec(f"{section}.{key}", scopes[0], tightens[0] if tightens else None, field)


SPECS: dict[str, KeySpec] = {
    f"{section}.{key}": _spec(section, key, field)
    for section, model in SECTIONS.items()
    for key, field in model.model_fields.items()
}


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
    """Read and validate the layered config for the repository at `repo_root`."""
    user_file = user_file or user_config_path()
    repo_file = repo_root / REPO_FILE_NAME

    repo_values: dict[str, object] = _read(repo_file) if repo_file.exists() else {}
    for name in repo_values:
        if SPECS[name].scope is Scope.USER:
            raise ConfigError(
                f"{repo_file}: {name} is user-only and cannot be set in the repository file; set it in {user_file}"
            )
    if not user_file.exists():
        raise ConfigError(f"no user config at {user_file}; run `canopy init`")
    user_values = _read(user_file)

    merged: dict[str, dict[str, object]] = {section: {} for section in SECTIONS}
    origin: dict[str, Path] = {}
    for source, values in ((repo_file, repo_values), (user_file, user_values)):
        for name, value in values.items():
            spec = SPECS[name]
            if source == repo_file and spec.tighten is not None and not _stricter(spec, value):
                continue
            section, key = name.split(".", 1)
            merged[section][key] = value
            origin[name] = source
    # Unset or empty: `prompts/` next to the user file.
    if merged["paths"].get("prompt_overrides", "") == "":
        merged["paths"]["prompt_overrides"] = str(user_file.parent / "prompts")

    try:
        return Config.model_validate(merged)
    except ValidationError as e:
        raise ConfigError(_describe(e, origin, repo_file, user_file)) from e


def _read(path: Path) -> dict[str, object]:
    try:
        with path.open("rb") as f:
            doc = tomllib.load(f)
    except tomllib.TOMLDecodeError as e:
        raise ConfigError(f"{path}: {e}") from e
    except OSError as e:
        raise ConfigError(f"{path}: {e.strerror}") from e

    values: dict[str, object] = {}
    for section, table in doc.items():
        if not isinstance(table, dict):
            raise ConfigError(f"{path}: unknown key {section}")
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
    if not isinstance(value, int) or isinstance(value, bool) or not isinstance(default, int):
        return True
    return value < default if spec.tighten is Tighten.LOWER else value > default


def _describe(error: ValidationError, origin: dict[str, Path], repo_file: Path, user_file: Path) -> str:
    lines: list[str] = []
    for e in error.errors():
        loc = [str(p) for p in e["loc"]]
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


def render_command(template: str, prompt: str) -> list[str]:
    """Turn a command template into argv. No shell runs (D023).

    The template is split with shell word rules, then `{prompt}` is replaced inside each word. The prompt therefore
    always lands in exactly one argument, whatever it contains.
    """
    return [w.replace("{prompt}", prompt) for w in command_words(template)]
