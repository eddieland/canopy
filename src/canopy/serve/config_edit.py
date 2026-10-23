"""The keys the web UI's settings page edits in the workspace's private config, and the save (DESIGN §12, §22, D128).

Only the keys `EDITABLE` names, never a section's wildcard: a key added to a section later is not editable until it
is named here. A limit may be raised or lowered, but the page cannot loosen one past its bound, a count's ceiling or a
pace's floor; the file can set any value, and the page may still tighten one the file set past its bound. A trust key
moves only toward stricter: a config write outlives the listener secret, so a replier added through a stolen session
would go on steering workers after a new secret ended it (TRUST_MODEL T8).

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
from typing import TYPE_CHECKING, Literal, get_args

import tomlkit
import tomlkit.exceptions
import tomlkit.items

from canopy.core import config, conversation
from canopy.infra import lock

if TYPE_CHECKING:
    from collections.abc import Mapping

    from canopy.core.config import Config

type Value = int | bool | str | tuple[str, ...] | dict[str, int] | None
type Source = Literal["private", "user", "workspace", "default"]

# Read by name from the request, so each guard's words are the operator's to act on.
NOT_EDITABLE = "not_editable"
PAST_BOUND = "past_bound"
NOT_STRICTER = "not_stricter"
STALE = "stale"
UNSAFE_FILE = "unsafe_file"
NOT_ROUNDTRIP = "not_roundtrip"
CONFIG_INVALID = "config_invalid"


@dataclass(frozen=True)
class Editable:
    """A key the settings page may change, and how far."""

    name: str
    # `limit`: raised or lowered, within `bound`. `stricter`: only toward stricter.
    kind: Literal["limit", "stricter"]
    # A limit's loosest value from the page: a count's ceiling, or a pace's floor in minutes.
    bound: int | None = None
    # Which way loosens a limit: a count's higher spends more, a pace's lower does.
    looser: Literal["higher", "lower"] | None = None


def _count(name: str, ceiling: int) -> Editable:
    return Editable(name, "limit", ceiling, "higher")


def _pace(name: str, floor: int) -> Editable:
    return Editable(name, "limit", floor, "lower")


# In the order the page shows them. The bounds stop a stolen session from turning one operator's spend up without limit:
# a raise within them outlives a new secret, a residual the page and the log show (TRUST_MODEL T8). They are set well
# above what one machine runs today, so the page is for the operator's real changes and the file for the rest.
EDITABLE: tuple[Editable, ...] = (
    _count("capacity.max_workers", 32),
    _count("capacity.max_chores", 16),
    _count("capacity.max_reviews", 16),
    _count("capacity.max_reviews_per_day", 500),
    _count("capacity.slots_per_repo", 32),
    # Each repository's entry is bounded alike; the request names only the repositories whose count changes.
    _count("capacity.repo_slots", 32),
    _count("policy.max_implement_attempts", 10),
    _count("policy.max_resume_attempts", 10),
    _count("policy.max_reviews_per_pr", 25),
    # The page's bound is the key's own ceiling: attachments cost a run reading them, never another run.
    _count("policy.max_attachments", config.ATTACHMENTS_CEILING),
    _count("policy.max_attachment_kib", config.ATTACHMENT_KIB_CEILING),
    _count("policy.max_attachments_total_kib", config.ATTACHMENTS_TOTAL_KIB_CEILING),
    _pace("policy.ci_cooldown_minutes", 5),
    _pace("loop.interval_minutes", 2),
    _pace("loop.idle_max_minutes", 2),
    # Spends nothing itself, but a raised budget keeps a sink from hearing the month reached it: bounded the same way.
    _count("spend.monthly_budget_usd", 10000),
    Editable("policy.stacking", "stricter"),
    Editable("trust.authorized_repliers", "stricter"),
    Editable("trust.trusted_reviewers", "stricter"),
    Editable("trust.rebase", "stricter"),
    Editable("trust.commit_trailer", "stricter"),
)
BY_NAME = {e.name: e for e in EDITABLE}
# The file as it was before the latest save, beside it: `config.toml.bak`. None when the save made the file.
BACKUP_SUFFIX = ".bak"
REPO_SLOTS = "capacity.repo_slots"
# A private file the save makes: the operator's alone, as `config.load` requires of it.
NEW_FILE_MODE = 0o600
# The trust switches, and the value each may move to from the page: the stricter one.
_STRICTER_BOOL = {"trust.rebase": False, "trust.commit_trailer": True}


@dataclass(frozen=True)
class Setting:
    """One editable key as the files say now: its value, and which file it comes from."""

    key: Editable
    value: Value
    source: Source


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
        settings=tuple(Setting(e, value(cfg, e.name), source(e.name)) for e in EDITABLE),
        private_file=private_file,
        user_file=user_file,
        workspace_file=shared_file,
        hash=digest(private_file.read_bytes() if private_file.exists() else b""),
    )


def save(root: Path, user_file: Path, expected: str, changes: Mapping[str, object]) -> Saved:
    """Write `changes` to the private file of the workspace at `root`, read with hash `expected`, if each is allowed.

    The private file is loaded over `user_file`, as the loop loads them, before and after. A list's value is the entries
    to keep, in the file's order; `capacity.repo_slots`'s is the repositories whose count changes. Nothing is written
    when every value is already so, or when anything is refused. The user file and the workspace file are never
    written.

    Returns:
        The keys changed, with their values before and after, and the file's hash now.

    Raises:
        Refused: `inside_run` inside one of canopy's own ticks or runs; `not_editable` for a key `EDITABLE` does not
            name; `unsafe_file` for a private file that is a symlink, not a regular file, or not the operator's
            (D053), or whose backup cannot be written; `not_roundtrip` for one tomlkit would not write back byte for
            byte; `stale` when the file's hash is not `expected`; `config_invalid` for a value of None, for a
            workspace with no state directory, or when the files, before or after, do not load; `past_bound` for a
            limit loosened past its bound; `not_stricter` for a trust key loosened.
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
            _set(doc, BY_NAME[name], wanted, old, target)
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
    found: object = getattr(getattr(cfg, section), key)
    if isinstance(found, dict):
        return {str(k): int(v) for k, v in found.items()}
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


def _set(doc: tomlkit.TOMLDocument, key: Editable, wanted: object, old: Config, path: Path) -> None:
    """Set `key` to `wanted` in `doc`, the private file's tree, keeping every comment and line around it.

    A key the tree does not set yet takes its whole value there, as the files give it now with `wanted` applied, so a
    key from the user file keeps what the page did not change: a list's other entries, another repository's slots.

    Raises:
        Refused: `not_stricter` for a list given an entry it does not have. A value of the wrong type is written as
            it is, for `config.load` to refuse with the loader's message.
    """
    section, _, name = key.name.partition(".")
    table = doc.get(section)
    if not isinstance(table, tomlkit.items.Table | tomlkit.items.InlineTable):
        table = tomlkit.table()
        doc[section] = table
    if key.name == REPO_SLOTS and isinstance(wanted, dict):
        _set_slots(table, name, wanted, value(old, key.name))
        return
    current = value(old, key.name)
    if isinstance(current, tuple) and isinstance(wanted, list):
        added = [str(v) for v in wanted if v not in current]
        if added:
            raise conversation.Refused(
                NOT_STRICTER,
                f"{key.name} may only lose entries from the web UI; add {', '.join(added)} in {path}",
            )
        entries = table.get(name)
        if isinstance(entries, tomlkit.items.Array):
            # Removed in place, so the entries kept keep their comments and the file's order.
            for i in reversed(range(len(entries))):
                if entries[i] not in wanted:
                    del entries[i]
            return
    table[name] = wanted


def _set_slots(
    table: tomlkit.items.Table | tomlkit.items.InlineTable,
    name: str,
    wanted: dict[object, object],
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
    """Refuse a change that loosens `key` further than the page may.

    Raises:
        Refused: `past_bound` for a limit past its bound and looser than before; `not_stricter` for a trust key
            loosened.
    """
    if key.kind == "limit":
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
        return
    if not _stricter(key, change.old, change.new):
        raise conversation.Refused(
            NOT_STRICTER,
            f"{key.name} may only be made stricter from the web UI; loosen it in {path}",
        )


def _past(key: Editable, was: object, now: object) -> bool:
    """Whether `now` is past `key`'s bound and looser than `was`.

    Returns:
        True when the page may not set `now`. An unmanaged pool (None) bounds nothing, so any count past the bound is.
    """
    if not isinstance(now, int) or key.bound is None:
        return False
    if key.looser == "higher":
        return now > key.bound and (not isinstance(was, int) or now > was)
    return now < key.bound and (not isinstance(was, int) or now < was)


def _past_reason(key: Editable, name: str, path: Path) -> str:
    if key.looser == "higher":
        return f"{name} may be at most {key.bound} from the web UI; set more in {path}"
    return f"{name} may be at least {key.bound} from the web UI; set less in {path}"


def _stricter(key: Editable, was: Value, now: Value) -> bool:
    """Whether `now` is `was` or stricter, for a key that may move only toward stricter.

    Returns:
        True for the same value, a switch moved to its stricter side, a list that only lost entries, or a later choice.
    """
    if now == was:
        return True
    if key.name in _STRICTER_BOOL:
        return now is _STRICTER_BOOL[key.name]
    if isinstance(was, tuple) and isinstance(now, tuple):
        return set(now) <= set(was)
    # A choice listed loosest first, as `policy.stacking`'s.
    choices = get_args(config.SPECS[key.name].field.annotation)
    return was in choices and now in choices and choices.index(now) > choices.index(was)
