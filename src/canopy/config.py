"""Layered configuration: built-in defaults, then the repository's `canopy.toml`, then the user's `config.toml`.

Every key has a scope (DESIGN §12). A shared key may be set in either file and the user file wins. A user-only key may
be set only in the user file; a repository file that sets one is an error, because anyone who can push to the
repository controls that file (TRUST_MODEL T7). Unknown keys are errors in both files. Repository `policy.*` values
apply only when stricter than the built-in defaults.
"""

from __future__ import annotations

import os
import shlex
import tomllib
from dataclasses import dataclass
from enum import Enum
from pathlib import Path
from typing import Literal

REPO_FILE_NAME = "canopy.toml"


class ConfigError(Exception):
    """The configuration cannot be used. The message names the file and key."""


class Scope(Enum):
    """Where a key may be set: either file, or only the user file."""

    SHARED = "shared"
    USER = "user-only"


type Kind = Literal["str", "int", "strlist"]
type Value = str | int | list[str]
type Tighten = Literal["lower", "higher"] | None


@dataclass(frozen=True)
class KeySpec:
    """One config key: its type, default, scope, and which direction is stricter for policy."""

    name: str
    scope: Scope
    kind: Kind
    default: Value | None  # None: no default; the key must be set.
    tighten: Tighten = None  # For repository policy: which direction is stricter.


KEYS: tuple[KeySpec, ...] = (
    KeySpec("tracker.provider", Scope.SHARED, "str", None),
    KeySpec("tracker.query", Scope.SHARED, "str", None),
    KeySpec("tracker.needs_human_label", Scope.SHARED, "str", "needs-human"),
    KeySpec("tracker.labels", Scope.USER, "strlist", None),
    KeySpec("policy.max_fix_ci_attempts", Scope.SHARED, "int", 2, "lower"),
    KeySpec("policy.fix_ci_cooldown_minutes", Scope.SHARED, "int", 30, "higher"),
    KeySpec("policy.max_resume_attempts", Scope.SHARED, "int", 3, "lower"),
    KeySpec("trust.branch_prefix", Scope.SHARED, "str", "agent/"),
    KeySpec("trust.pr_label", Scope.SHARED, "str", "agent"),
    KeySpec("trust.authorized_repliers", Scope.USER, "strlist", []),
    KeySpec("capacity.max_workers", Scope.USER, "int", 2),
    KeySpec("runtime.overseer_cmd", Scope.USER, "str", "opencode run --agent canopy-overseer {prompt}"),
    KeySpec("runtime.worker_cmd", Scope.USER, "str", "opencode run --agent canopy-worker {prompt}"),
    KeySpec("runtime.overseer_timeout_minutes", Scope.USER, "int", 15),
    KeySpec("runtime.worker_timeout_minutes", Scope.USER, "int", 45),
    # Empty means "prompts/ next to the user file"; resolved in `load`, since it depends on XDG_CONFIG_HOME.
    KeySpec("paths.prompt_overrides", Scope.USER, "str", ""),
    KeySpec("paths.state_dir", Scope.USER, "str", "~/.canopy"),
    KeySpec("notify.cmd", Scope.USER, "str", ""),
)
SPECS: dict[str, KeySpec] = {k.name: k for k in KEYS}


@dataclass(frozen=True)
class Tracker:
    """The `[tracker]` table."""

    provider: str
    query: str
    needs_human_label: str
    labels: tuple[str, ...]


@dataclass(frozen=True)
class Policy:
    """The `[policy]` table: attempt limits and cooldowns."""

    max_fix_ci_attempts: int
    fix_ci_cooldown_minutes: int
    max_resume_attempts: int


@dataclass(frozen=True)
class Trust:
    """The `[trust]` table."""

    branch_prefix: str
    pr_label: str
    authorized_repliers: tuple[str, ...]


@dataclass(frozen=True)
class Runtime:
    """The `[runtime]` table: agent command templates and timeouts."""

    overseer_cmd: str
    worker_cmd: str
    overseer_timeout_minutes: int
    worker_timeout_minutes: int


@dataclass(frozen=True)
class Paths:
    """The `[paths]` table."""

    prompt_overrides: Path
    state_dir: Path


@dataclass(frozen=True)
class Config:
    """The merged, validated configuration."""

    tracker: Tracker
    policy: Policy
    trust: Trust
    max_workers: int
    runtime: Runtime
    paths: Paths
    notify_cmd: str


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

    repo_values: dict[str, Value] = _read(repo_file) if repo_file.exists() else {}
    for name in repo_values:
        if SPECS[name].scope is Scope.USER:
            raise ConfigError(
                f"{repo_file}: {name} is user-only and cannot be set in the repository file; set it in {user_file}"
            )
    if not user_file.exists():
        raise ConfigError(f"no user config at {user_file}; run `canopy init`")
    user_values = _read(user_file)

    merged: dict[str, Value] = {}
    for spec in KEYS:
        if spec.default is not None:
            merged[spec.name] = spec.default
        if spec.name in repo_values:
            value = repo_values[spec.name]
            if spec.tighten is None or _stricter(spec, value):
                merged[spec.name] = value
        if spec.name in user_values:
            merged[spec.name] = user_values[spec.name]

    missing = [s.name for s in KEYS if s.name not in merged]
    if missing:
        raise ConfigError(f"missing required key(s): {', '.join(missing)}; set them in {repo_file} or {user_file}")
    return _build(merged, user_file)


def _read(path: Path) -> dict[str, Value]:
    try:
        with path.open("rb") as f:
            doc = tomllib.load(f)
    except tomllib.TOMLDecodeError as e:
        raise ConfigError(f"{path}: {e}") from e
    except OSError as e:
        raise ConfigError(f"{path}: {e.strerror}") from e

    values: dict[str, Value] = {}
    for section, table in doc.items():
        if not isinstance(table, dict):
            raise ConfigError(f"{path}: unknown key {section}")
        for key, raw in table.items():
            name = f"{section}.{key}"
            spec = SPECS.get(name)
            if spec is None:
                raise ConfigError(f"{path}: unknown key {name}")
            values[name] = _check_type(path, spec, raw)
    return values


def _check_type(path: Path, spec: KeySpec, raw: object) -> Value:
    if spec.kind == "str" and isinstance(raw, str):
        return raw
    # bool is a subclass of int; `max_workers = true` is a mistake, not 1.
    if spec.kind == "int" and isinstance(raw, int) and not isinstance(raw, bool):
        if raw < 0:
            raise ConfigError(f"{path}: {spec.name} must not be negative")
        return raw
    if spec.kind == "strlist" and isinstance(raw, list):
        items: list[str] = []
        for item in raw:
            if not isinstance(item, str):
                break
            items.append(item)
        else:
            return items
    expected = {"str": "a string", "int": "an integer", "strlist": "a list of strings"}[spec.kind]
    raise ConfigError(f"{path}: {spec.name} must be {expected}")


def _stricter(spec: KeySpec, value: Value) -> bool:
    if not isinstance(value, int) or not isinstance(spec.default, int):
        raise TypeError(f"{spec.name}: policy keys are integers")
    return value < spec.default if spec.tighten == "lower" else value > spec.default


# Typed reads from the merged values, which `_check_type` has already checked per key.


def _str(v: dict[str, Value], name: str) -> str:
    value = v[name]
    if not isinstance(value, str):
        raise TypeError(name)
    return value


def _int(v: dict[str, Value], name: str) -> int:
    value = v[name]
    if not isinstance(value, int):
        raise TypeError(name)
    return value


def _list(v: dict[str, Value], name: str) -> tuple[str, ...]:
    value = v[name]
    if not isinstance(value, list):
        raise TypeError(name)
    return tuple(value)


def _validate(v: dict[str, Value], user_file: Path) -> None:
    labels = _list(v, "tracker.labels")
    if not labels:
        raise ConfigError(f"{user_file}: tracker.labels must list at least one label")
    if not all(label.strip() for label in labels):
        raise ConfigError(f"{user_file}: tracker.labels entries must not be empty")
    for name in ("tracker.provider", "tracker.query", "tracker.needs_human_label"):
        if not _str(v, name).strip():
            raise ConfigError(f"{name} must not be empty")
    prefix = _str(v, "trust.branch_prefix")
    if not prefix or not prefix.endswith("/"):
        raise ConfigError(f"trust.branch_prefix must be non-empty and end in '/', got {prefix!r}")
    for name in ("runtime.overseer_cmd", "runtime.worker_cmd"):
        check_command_template(name, _str(v, name))
    for name in ("runtime.overseer_timeout_minutes", "runtime.worker_timeout_minutes"):
        if _int(v, name) == 0:
            raise ConfigError(f"{name} must be at least 1")


def _build(v: dict[str, Value], user_file: Path) -> Config:
    _validate(v, user_file)

    def s(name: str) -> str:
        return _str(v, name)

    def i(name: str) -> int:
        return _int(v, name)

    overrides = s("paths.prompt_overrides")
    return Config(
        tracker=Tracker(
            provider=s("tracker.provider"),
            query=s("tracker.query"),
            needs_human_label=s("tracker.needs_human_label"),
            labels=_list(v, "tracker.labels"),
        ),
        policy=Policy(
            max_fix_ci_attempts=i("policy.max_fix_ci_attempts"),
            fix_ci_cooldown_minutes=i("policy.fix_ci_cooldown_minutes"),
            max_resume_attempts=i("policy.max_resume_attempts"),
        ),
        trust=Trust(
            branch_prefix=s("trust.branch_prefix"),
            pr_label=s("trust.pr_label"),
            authorized_repliers=_list(v, "trust.authorized_repliers"),
        ),
        max_workers=i("capacity.max_workers"),
        runtime=Runtime(
            overseer_cmd=s("runtime.overseer_cmd"),
            worker_cmd=s("runtime.worker_cmd"),
            overseer_timeout_minutes=i("runtime.overseer_timeout_minutes"),
            worker_timeout_minutes=i("runtime.worker_timeout_minutes"),
        ),
        paths=Paths(
            prompt_overrides=Path(overrides).expanduser() if overrides else user_file.parent / "prompts",
            state_dir=Path(s("paths.state_dir")).expanduser(),
        ),
        notify_cmd=s("notify.cmd"),
    )


def check_command_template(name: str, template: str) -> list[str]:
    """Split a command template into words, as `render_command` will. It must mention `{prompt}`."""
    try:
        words = shlex.split(template)
    except ValueError as e:
        raise ConfigError(f"{name}: {e}") from e
    if not words:
        raise ConfigError(f"{name} must not be empty")
    if not any("{prompt}" in w for w in words):
        raise ConfigError(f"{name} must contain {{prompt}}")
    return words


def render_command(template: str, prompt: str) -> list[str]:
    """Turn a command template into argv. No shell runs.

    The template is split with shell word rules, then `{prompt}` is replaced inside each word. The prompt therefore
    always lands in exactly one argument, whatever it contains.
    """
    return [w.replace("{prompt}", prompt) for w in check_command_template("command", template)]
