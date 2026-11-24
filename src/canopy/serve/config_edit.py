"""The keys the web UI's settings page edits in the workspace's private config, and the save (DESIGN §12, §22, D128).

Only the keys `EDITABLE` names, never a section's wildcard: a key added to a section later is not editable until it
is named here. A key may be set to anything the loader takes: the operator settled that the page's own bounds, and
then its rule that a trust key only tightens, cost more than what they guarded (TRUST_MODEL T8). A retention alone
keeps a floor, since what a shorter one removes cannot be brought back: the page cannot shorten one past it, 0 keeps
forever and may always be set, the file can set any value, and the page may still lengthen one the file set under its
floor.

A save writes the workspace's private file only (M49), never the workspace file (TRUST_MODEL T7) nor the user file,
which serves every workspace. A key whose value comes from the user file is written to the private file, where it
shadows the user file's for this workspace alone; a private file not there yet is made. The file is edited in place so
that the operator's comments and layout stay: a file tomlkit would not write back byte for byte is refused before
anything is changed, so only the values set differ, and the file as it was is kept beside it as `config.toml.bak`.
A lock beside the file is held from reading it to replacing it, so two saves made on the same read cannot both pass
the hash check; the hash is checked again just before the replace, so a hand edit is lost only if it lands in that
last moment. The edited copy is validated by `config.load`, as any `canopy` command would read it, before it replaces
the file atomically, with the file's mode kept.
"""

from __future__ import annotations

import hashlib
import os
import stat
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING, Final, Literal

import tomlkit
import tomlkit.exceptions
import tomlkit.items

from canopy.core import config, conversation
from canopy.infra import lock

if TYPE_CHECKING:
    from collections.abc import Mapping, Sequence

    from canopy.core.config import Config

type Value = int | bool | str | tuple[str, ...] | tuple[int, ...] | dict[str, int] | None
type Source = Literal["private", "user", "workspace", "default"]

#: Read by name from the request, so each guard's words are the operator's to act on.
NOT_EDITABLE: Final = "not_editable"
PAST_BOUND: Final = "past_bound"
STALE: Final = "stale"
UNSAFE_FILE: Final = "unsafe_file"
NOT_ROUNDTRIP: Final = "not_roundtrip"
CONFIG_INVALID: Final = "config_invalid"


@dataclass(frozen=True)
class Editable:
    """A key the settings page may change, and a retention's floor."""

    name: str
    #: A retention's floor from the page, in the key's own unit, days or, for the log's rotation, MiB and files: the
    #: least it may be made. None for every other key.
    bound: int | None = None
    #: A choice's values, in the order the page offers them.
    choices: Sequence[str] = ()
    #: Whether 0 keeps that kind forever, as a retention's does: the strictest value, which the page may always set,
    #: and one any number of days is shorter than.
    forever_at_zero: bool = False


def _keep(name: str, floor: int) -> Editable:
    return Editable(name, floor, forever_at_zero=True)


def _choice(name: str, *choices: str) -> Editable:
    return Editable(name, choices=choices)


#: In the order the page shows them. None but a retention has a bound of the page's own: whoever holds a session can
#: set one as the file could, a residual the page and the log show (TRUST_MODEL T8).
EDITABLE: Final[tuple[Editable, ...]] = (
    Editable("capacity.max_workers"),
    Editable("capacity.max_chores"),
    Editable("capacity.max_reviews"),
    Editable("capacity.max_reviews_per_day"),
    Editable("review.agent_prs"),
    Editable("capacity.max_tasks"),
    Editable("loop.min_free_disk_mib"),
    Editable("capacity.slots_per_repo"),
    # The request names only the repositories whose count changes.
    Editable("capacity.repo_slots"),
    Editable("policy.max_implement_attempts"),
    Editable("policy.max_resume_attempts"),
    Editable("policy.max_reviews_per_pr"),
    Editable("policy.max_plan_attempts"),
    Editable("policy.max_feedback_plan_attempts"),
    Editable("policy.max_revisions_per_draft"),
    Editable("policy.max_follow_ups"),
    Editable("policy.max_epic_tickets"),
    Editable("policy.max_attachments"),
    Editable("policy.max_attachment_kib"),
    Editable("policy.max_attachments_total_kib"),
    Editable("policy.ci_cooldown_minutes"),
    Editable("policy.feedback_quiet_minutes"),
    Editable("policy.feedback_ci_wait_minutes"),
    Editable("review.settle_minutes"),
    Editable("loop.interval_minutes"),
    Editable("loop.idle_max_minutes"),
    Editable("loop.min_gap_minutes"),
    Editable("tracker.query_every_minutes"),
    # How often the operator's own remote is pushed to: a pace, as the others are.
    Editable("paths.plan_archive_every_minutes"),
    Editable("connect.every_minutes"),
    Editable("connect.max_age_minutes"),
    Editable("runtime.worker_timeout_minutes"),
    Editable("runtime.review_timeout_minutes"),
    Editable("runtime.overseer_timeout_minutes"),
    Editable("runtime.setup_timeout_minutes"),
    # A pool's upkeep (DESIGN §26): when a tick does it, never the command an idle slot runs, which stays the file's.
    Editable("pools.git_maintenance"),
    Editable("pools.git_max_packs"),
    Editable("pools.git_max_loose"),
    Editable("pools.git_every_hours"),
    Editable("pools.idle_after_days"),
    Editable("pools.idle_timeout_minutes"),
    # Shorter removes history sooner, the transcripts that show what a run did among it: a floor, and 0, forever,
    # always (TRUST_MODEL T8).
    _keep("retention.run_files_days", 7),
    _keep("retention.tick_files_days", 1),
    _keep("retention.journal_days", 30),
    _keep("retention.memory_days", 7),
    # The log names each change the page made, so its rotation's floors are the defaults: the page keeps more of
    # it, or all of it at 0, never less than a stock install does.
    _keep("retention.log_max_mib", 50),
    _keep("retention.log_keep", 3),
    Editable("spend.monthly_budget_usd"),
    # The 100% alert is always sent, whatever the list holds.
    Editable("spend.budget_alerts"),
    _choice("policy.stacking", "auto", "never"),
    _choice("policy.plan", "off", "approve"),
    _choice("policy.feedback_plan", "off", "approve"),
    _choice("policy.planner_may_approve", "lenient", "normal", "strict", "off"),
    Editable("trust.authorized_repliers"),
    Editable("trust.trusted_reviewers"),
    _choice("trust.review_replies", "post", "approve"),
    Editable("trust.rebase"),
    Editable("trust.max_flaky_kicks"),
    Editable("trust.commit_trailer"),
    _choice("memory.ticket_notes", "use", "record", "off"),
    _choice("memory.proposals", "use", "record", "off"),
    Editable("artifacts.authorized_authors"),
    Editable("artifacts.publish_roles"),
    _choice("sessions.search", "text", "titles", "off"),
    Editable("paths.plan_archive_prompts"),
    Editable("paths.plan_archive_conversations"),
    Editable("paths.plan_archive_comments"),
)
BY_NAME: Final = {e.name: e for e in EDITABLE}
#: The file as it was before the latest save, beside it: `config.toml.bak`. None when the save made the file.
BACKUP_SUFFIX: Final = ".bak"
REPO_SLOTS: Final = "capacity.repo_slots"
#: A private file the save makes: the operator's alone, as `config.load` requires of it.
NEW_FILE_MODE: Final = 0o600


@dataclass(frozen=True)
class Setting:
    """One editable key as the files say now: its value, which file it comes from, and its value when none sets it."""

    key: Editable
    value: Value
    source: Source
    #: The config model's default for the key, what it holds when no file sets it.
    default: Value


@dataclass(frozen=True)
class Settings:
    """Every editable key, the files they come from, and the private file's hash as read, which a save must carry."""

    settings: tuple[Setting, ...]
    private_file: Path
    user_file: Path
    workspace_file: Path
    hash: str


@dataclass(frozen=True)
class Change:
    """A key a save changed, with its value before and after."""

    name: str
    old: Value
    new: Value


@dataclass(frozen=True)
class Saved:
    """What a save wrote: the keys it changed, none when every value was already so, and the file's hash now."""

    changes: tuple[Change, ...]
    hash: str


def read(root: Path, user_file: Path) -> Settings:
    """Every editable key's value as the workspace at `root`, `user_file`, and the private file say now.

    Returns:
        Each key in `EDITABLE`'s order, with its source, and the private file's hash: an empty file's when there is
        none yet.

    Raises:
        ConfigError: the files do not load. The message names the file.
    """
    cfg = config.load(root, user_file)
    origin = config.origins(root, user_file)
    shared_file = root / config.WORKSPACE_FILE_NAME
    private_file = config.private_config_path(root)

    def source(name: str) -> Source:
        found = origin.get(name)
        if found is None:
            return "default"
        if found == shared_file:
            return "workspace"
        return "private" if found == private_file else "user"

    return Settings(
        settings=tuple(Setting(e, value(cfg, e.name), source(e.name), default(cfg, e.name)) for e in EDITABLE),
        private_file=private_file,
        user_file=user_file,
        workspace_file=shared_file,
        hash=digest(private_file.read_bytes() if private_file.exists() else b""),
    )


def save(root: Path, user_file: Path, expected: str, changes: Mapping[str, object]) -> Saved:
    """Write `changes` to the private file of the workspace at `root`, read with hash `expected`, if each is allowed.

    The private file is loaded over `user_file`, as the loop loads them, before and after. A list's value is its new
    value whole; `capacity.repo_slots`'s is the repositories whose count changes. Nothing is written when every value is
    already so, or when anything is refused. The user file and the workspace file are never written.

    Returns:
        The keys changed, with their values before and after, and the file's hash now.

    Raises:
        Refused: `inside_run` inside one of canopy's own ticks or runs; `not_editable` for a key `EDITABLE` does not
            name; `unsafe_file` for a private file that is a symlink, not a regular file, or not the operator's
            (D053), or whose backup cannot be written; `not_roundtrip` for one tomlkit would not write back byte for
            byte; `stale` when the file's hash is not `expected`; `config_invalid` for a value of None, for a
            workspace with no state directory, or when the files, before or after, do not load; `past_bound` for a
            retention shortened past its floor.
    """
    conversation.check_operator()
    target = config.private_config_path(root)
    unknown = sorted(n for n in changes if n not in BY_NAME)
    if unknown:
        raise conversation.Refused(
            NOT_EDITABLE,
            f"the web UI cannot change {', '.join(unknown)}; edit {target} for that",
        )
    unset = sorted(n for n, v in changes.items() if v is None)
    if unset:
        # Unsetting a key could loosen it to its default, as an unmanaged pool is: that is the file's to do.
        raise conversation.Refused(
            CONFIG_INVALID,
            f"{', '.join(unset)} needs a value; unset it in {target} if that is what you want",
        )
    if not target.parent.is_dir():
        raise conversation.Refused(CONFIG_INVALID, f"no state directory at {target.parent}; run `canopy init`")
    with lock.hold(target.with_name(target.name + ".lock"), wait=True):
        text, mode = _read_own(target)
        _check_hash(target, text, expected)
        old = _load(root, user_file, None, target)
        doc = _parse_exactly(text, target)
        for name, wanted in changes.items():
            _set(doc, BY_NAME[name], wanted, old)
        written = tomlkit.dumps(doc).encode()
        # Beside the file, so a relative `paths.*` value in it resolves as the file's own does.
        fd, temp = tempfile.mkstemp(dir=target.parent, prefix=f".{target.name}.", suffix=".tmp")
        copy = Path(temp)
        try:
            with os.fdopen(fd, "wb") as f:
                os.fchmod(f.fileno(), mode or NEW_FILE_MODE)
                f.write(written)
            new = _load(root, user_file, copy, target)
            _check_rest(old, new, changes, target)
            found = tuple(Change(n, value(old, n), value(new, n)) for n in BY_NAME if value(old, n) != value(new, n))
            for change in found:
                _check(BY_NAME[change.name], change, old, target)
            if not found:
                return Saved((), expected)
            # Again just before the replace: a hand edit since the first read is kept, and this save refused.
            _check_hash(target, _read_own(target)[0], expected)
            if mode is not None:
                _back_up(target, text, mode)
            copy.replace(target)
        finally:
            copy.unlink(missing_ok=True)
    return Saved(found, digest(written))


def digest(text: bytes) -> str:
    """The hash a save must carry: SHA-256 of the private file's bytes, in hex, an empty file's when there is none.

    Returns:
        The hex digest.
    """
    return hashlib.sha256(text).hexdigest()


def value(cfg: Config, name: str) -> Value:
    """The value `cfg` gives key `name`, as `section.key`.

    Returns:
        A count, a switch, a choice, a list's entries, or `capacity.repo_slots`'s counts by repository.

    Raises:
        TypeError: the key holds something else, such as a table of tables: no editable key does.
    """
    section, _, key = name.partition(".")
    return _as_value(name, getattr(getattr(cfg, section), key))


def default(cfg: Config, name: str) -> Value:
    """The value key `name`, as `section.key`, holds when no file sets it: its config model's default.

    Returns:
        The default as `value` gives a value read.

    Raises:
        TypeError: the default is something else, as `value` raises for a value read.
    """
    section, _, key = name.partition(".")
    field = type(getattr(cfg, section)).model_fields[key]
    return _as_value(name, field.get_default(call_default_factory=True, validated_data={}))


def _as_value(name: str, found: object) -> Value:
    """`found`, the value of key `name` or its default, as the settings page shows one.

    Returns:
        A count, a switch, a choice, a list's entries, or counts by repository.

    Raises:
        TypeError: it is something else.
    """
    if isinstance(found, dict):
        return {str(k): int(v) for k, v in found.items()}
    if isinstance(found, tuple) and all(isinstance(v, int) for v in found):
        return tuple(int(v) for v in found)
    if isinstance(found, tuple):
        return tuple(str(v) for v in found)
    if found is None or isinstance(found, bool | int | str):
        return found
    raise TypeError(f"{name} is not a value the settings page shows")


def _read_own(path: Path) -> tuple[bytes, int | None]:
    """The private file's bytes and permission bits, once it is a regular file of the operator's (D053's check).

    Returns:
        Its bytes, and its mode's permission bits, which the replacement keeps; no bytes and None when there is no file
        yet, which the save makes.

    Raises:
        Refused: `unsafe_file` when it is a symlink, not a regular file, or someone else's.
    """
    try:
        st = path.lstat()
    except FileNotFoundError:
        return b"", None
    if not stat.S_ISREG(st.st_mode) or st.st_uid != os.getuid():
        raise conversation.Refused(
            UNSAFE_FILE,
            f"{path} is a symlink, not a regular file, or not yours; the web UI writes only a file of your own",
        )
    fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW)
    with os.fdopen(fd, "rb") as f:
        return f.read(), stat.S_IMODE(st.st_mode)


def _parse_exactly(text: bytes, path: Path) -> tomlkit.TOMLDocument:
    """The private file's tree, once it is known to write back byte for byte, so a save changes only what it sets.

    Returns:
        The parsed document.

    Raises:
        Refused: `not_roundtrip` for a file that is not UTF-8, or that tomlkit would not write back exactly as it is.
    """
    try:
        source = text.decode()
        doc = tomlkit.parse(source)
    except (UnicodeDecodeError, tomlkit.exceptions.TOMLKitError):
        doc, source = None, None
    if doc is None or tomlkit.dumps(doc) != source:
        raise conversation.Refused(
            NOT_ROUNDTRIP,
            f"{path} would not be written back exactly as it is; change it in the file instead",
        )
    return doc


def _back_up(path: Path, text: bytes, mode: int) -> None:
    """Keep the file as it was beside it, as `<name>.bak` with its mode, replacing the last save's.

    Raises:
        Refused: `unsafe_file` when the backup's path is a symlink or cannot be written.
    """
    backup = path.with_name(path.name + BACKUP_SUFFIX)
    try:
        fd = os.open(backup, os.O_WRONLY | os.O_CREAT | os.O_TRUNC | os.O_NOFOLLOW, mode)
    except OSError as e:
        raise conversation.Refused(UNSAFE_FILE, f"cannot keep a backup at {backup}: {e.strerror}") from None
    with os.fdopen(fd, "wb") as f:
        os.fchmod(f.fileno(), mode)
        f.write(text)


def _check_hash(path: Path, text: bytes, expected: str) -> None:
    if digest(text) != expected:
        raise conversation.Refused(STALE, f"{path} changed since the page read it; read it again and redo the change")


def _load(root: Path, user_file: Path, private_file: Path | None, shown: Path) -> Config:
    """`config.load` with `private_file` as the private file, its errors naming `shown`, the file the operator knows.

    Returns:
        The config the workspace file, `user_file`, and `private_file` (None: the workspace's own) make.

    Raises:
        Refused: `config_invalid`, with the loader's message.
    """
    try:
        return config.load(root, user_file, private_file=private_file)
    except config.ConfigError as e:
        message = str(e) if private_file is None else str(e).replace(str(private_file), str(shown))
        raise conversation.Refused(CONFIG_INVALID, message) from None


def _set(doc: tomlkit.TOMLDocument, key: Editable, wanted: object, old: Config) -> None:
    """Set `key` to `wanted` in `doc`, the private file's tree, keeping every comment and line around it.

    A key the tree does not set yet takes its whole value there, as the files give it now with `wanted` applied, so a
    key from the user file keeps what the page did not change: another repository's slots. A value of the wrong type
    is written as it is, for `config.load` to refuse with the loader's message.
    """
    section, _, name = key.name.partition(".")
    table = doc.get(section)
    if not isinstance(table, tomlkit.items.Table | tomlkit.items.InlineTable):
        table = tomlkit.table()
        doc[section] = table
    if key.name == REPO_SLOTS and isinstance(wanted, dict):
        _set_slots(table, name, wanted, value(old, key.name))
        return
    entries = table.get(name)
    if isinstance(entries, tomlkit.items.Array) and isinstance(wanted, list) and _keeps_order(entries, wanted):
        # Removed and added in place, so the entries kept keep their comments and the file's layout.
        for i in reversed(range(len(entries))):
            if entries[i] not in wanted:
                del entries[i]
        for entry in wanted[len(entries) :]:
            entries.append(entry)
        return
    table[name] = wanted


def _keeps_order(entries: Sequence[object], wanted: Sequence[object]) -> bool:
    """Whether `wanted` is `entries` with some dropped and others added at its end, so it can be edited in place.

    Returns:
        True when the entries of `entries` that `wanted` keeps open it, in the file's order.
    """
    kept = [e for e in entries if e in wanted]
    return list(wanted[: len(kept)]) == kept and not any(e in kept for e in wanted[len(kept) :])


def _set_slots(
    table: tomlkit.items.Table | tomlkit.items.InlineTable,
    name: str,
    wanted: Mapping[object, object],
    now: Value,
) -> None:
    """Set `capacity.repo_slots`'s counts for the repositories in `wanted`, keeping every other repository's.

    It is one key, so a private file's table replaces the user file's whole: one the private file does not have yet
    starts from the counts the files give now (`now`).
    """
    slots = table.get(name)
    if not isinstance(slots, tomlkit.items.Table | tomlkit.items.InlineTable):
        slots = tomlkit.inline_table()
        if isinstance(now, dict):
            slots.update(now)
        table[name] = slots
    for repo, count in wanted.items():
        slots[str(repo)] = count


def _check_rest(old: Config, new: Config, changes: Mapping[str, object], path: Path) -> None:
    """Refuse when the edit changed a key the request did not name: no key outside `EDITABLE` moves.

    Raises:
        Refused: `not_editable`, naming the keys that would have changed.
    """
    others = [n for n in config.changed(old, new) if n not in changes]
    if others:
        raise conversation.Refused(
            NOT_EDITABLE,
            f"the change would also change {', '.join(others)}; edit {path} for that",
        )


def _check(key: Editable, change: Change, old: Config, path: Path) -> None:
    """Refuse a change that shortens a retention further than the page may.

    Raises:
        Refused: `past_bound` for a retention under its floor and shorter than before.
    """
    pairs: list[tuple[str, object, object]]
    if isinstance(change.new, dict):
        before = change.old if isinstance(change.old, dict) else {}
        pairs = [
            (f"{key.name}.{repo}", before.get(repo, old.capacity.slots_for(repo)), n)
            for repo, n in change.new.items()
            if before.get(repo) != n
        ]
    else:
        pairs = [(key.name, change.old, change.new)]
    for name, was, now in pairs:
        if _past(key, was, now):
            raise conversation.Refused(PAST_BOUND, _past_reason(key, name, path))


def _past(key: Editable, was: object, now: object) -> bool:
    """Whether `now` is under `key`'s floor and shorter than `was`.

    Returns:
        True when the page may not set `now`. A key with no floor refuses nothing. 0, forever, is never past, and any
        count of days under the floor is past from 0.
    """
    if not isinstance(now, int) or key.bound is None:
        return False
    return now != 0 and now < key.bound and (not isinstance(was, int) or was == 0 or now < was)


def _past_reason(key: Editable, name: str, path: Path) -> str:
    return f"{name} may be at least {key.bound}, or 0 to keep forever, from the web UI; set less in {path}"
