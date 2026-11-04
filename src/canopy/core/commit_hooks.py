"""canopy's git hooks: its marks on every commit a worker makes (TRUST_MODEL T5), and its checklist's hold on a push.

The marks are formed by the harness and added by git, not by the agent: a worker run's environment points git's
`core.hooksPath` at the hooks in canopy's snapshot (DESIGN §13), through `GIT_CONFIG_COUNT` and its keys, and names
the marks in `CANOPY_COMMIT_TRAILERS` and `CANOPY_COMMIT_PREFIX`. In a commit in one of the run's slots, which
`CANOPY_SLOTS` names, `prepare-commit-msg` puts the prefix before a subject that lacks it, but a `fixup!`, `squash!`,
or `amend!` one, which `--autosquash` matches by its subject, and adds each trailer the message lacks; git runs it
for a commit, an amend, a merge, a rebase, a cherry-pick, and a revert, `--no-verify` or not, and only plumbing such
as `commit-tree` makes a commit without it. Every hook, that one included, then runs the repository's own hook of its
name, the one git would have run without canopy's entry, so the operator's hooks run as before (docs/HOOKS.md).

`pre-push` holds a worker's first push of a stretch of work for its repository's checklist (DESIGN §42), when
`CANOPY_CHECKLISTS` names a list for the slot it runs in: it prints the list and fails, so git sends nothing, and marks
the hold, with `CANOPY_RUN_ID` and the time, in the slot's own git directory, since a slot outlives its run. A push of
the same run within `HOLD_WINDOW_SECONDS` of the hold goes through; one after it, or after another run's hold, is held
again. It holds only a push with something to send, by the refs git hands it on its input, which it hands on to the
repository's own hook, and in the run's last `LAST_STRETCH_SECONDS` by `CANOPY_DEADLINE` it prints the list and lets
the push through. It is a reminder, not a guard: what it cannot read or write lets the push through. Each time it shows
the list, and each push it lets through after a hold, it notes the commit in the slot's own git directory too, so the
harness can keep what the run changed after the list was shown (`pushes_after`).

canopy's entry is the last of the `GIT_CONFIG_*` ones, after any the operator's environment holds, so a hook finds
the repository's own hooks by asking git with one entry fewer, or more where a tool added its own after canopy's.
`GIT_CONFIG_COUNT` needs git 2.31; an older git ignores it and adds no marks, so each tick checks the git on `PATH`
(`git_too_old`), and the run's note names the commits. The variables reach every git the worker's tools run, in any
repository: what they run there is that repository's own hooks, and nothing of canopy's, so a test that makes a
repository of its own commits as it would without canopy.
"""

from __future__ import annotations

import contextlib
import os
import re
import stat
from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from typing import TYPE_CHECKING

from canopy.core import checklists, hostgit, prompts
from canopy.infra import procs

if TYPE_CHECKING:
    from collections.abc import Mapping
    from pathlib import Path

    from canopy.core.config import Config

#: The directory in canopy's snapshot that holds the hooks.
HOOKS_DIR = "git-hooks"
#: The trailers the hooks add, one to a line.
TRAILERS_ENV = "CANOPY_COMMIT_TRAILERS"
#: The text the hooks put before a commit's subject.
PREFIX_ENV = "CANOPY_COMMIT_PREFIX"
#: The run's slots, a top level to a line, whose commits alone the hooks mark.
SLOTS_ENV = "CANOPY_SLOTS"
#: The lists `pre-push` holds a push for: a line per slot, its top level and its list's file, split by a tab.
CHECKLISTS_ENV = "CANOPY_CHECKLISTS"
#: The file in a slot's own git directory where `pre-push` marks its hold: the run's id and the time, in Unix seconds.
HOLD_MARKER = "canopy-checklist-hold"
#: The file in a slot's own git directory where `pre-push` notes each time it showed the run its list, and each push it
#: let through after a hold: a line `<shown|sent> <run id> <commit>`, which the harness reads, and removes, as the run
#: ends (`pushes_after`).
PUSHES_LOG = "canopy-checklist-pushes"
#: How much of that file the harness reads: far more than a run's pushes fill.
MAX_PUSHES_BYTES = 64 * 1024
#: A commit id, as git names one: SHA-1, or SHA-256.
_COMMIT_RE = re.compile(r"[0-9a-f]{40}(?:[0-9a-f]{24})?")
#: How long after a hold a push of the same run goes through: past it, a push after a long stretch of work is held
#: again. Long enough to diff, fix, and commit; a push held a second time still goes through the time after.
HOLD_WINDOW_SECONDS = 30 * 60
#: The stretch before `CANOPY_DEADLINE` in which no push is held, since a held push then risks the run ending unpushed:
#: the clock's last stretch at its longest (DESIGN §33), as the hook knows the deadline, not when the run started.
LAST_STRETCH_SECONDS = 10 * 60
#: The oldest git that reads `GIT_CONFIG_COUNT`, through which a worker's git finds the hooks.
MIN_GIT = (2, 31)
#: How `git --version` names its version, as Linux, macOS, and Windows builds print it.
_GIT_VERSION_RE = re.compile(r"git version (\d+)\.(\d+)")
_GIT_VERSION_TIMEOUT_SECONDS = 30
#: The client-side hooks git runs from its hooks directory, each of which canopy's must hand on to the repository's.
NAMES = (
    "applypatch-msg",
    "commit-msg",
    "post-applypatch",
    "post-checkout",
    "post-commit",
    "post-index-change",
    "post-merge",
    "post-rewrite",
    "pre-applypatch",
    "pre-auto-gc",
    "pre-commit",
    "pre-merge-commit",
    "pre-push",
    "pre-rebase",
    "prepare-commit-msg",
    "reference-transaction",
    "sendemail-validate",
)
#: Each hook, under each name: POSIX sh, so a hook costs a shell and one git, not a Python start.
SCRIPT = (
    r"""#!/bin/sh
# canopy's git hook (TRUST_MODEL T5): puts canopy's prefix and trailers on the message, as prepare-commit-msg, holds a
# worker's push for its repository's checklist, as pre-push (DESIGN §42), then runs the repository's own hook of this
# name.
name=${0##*/}
read_refs=
# Holds a push of the refs in $1 for the list CANOPY_CHECKLISTS names for this slot: prints it and exits, or returns to
# let the push through. What it cannot read or write lets the push through, since the hold is a reminder, not a guard.
hold() {
    # Something to send: a ref whose local sha is not all zeros, as a deletion's is. Its commit is the one noted.
    sending=$(printf '%s\n' "$1" | while read -r _ sha _ _; do
        case $sha in *[!0]*) echo "$sha" && break ;; esac
    done)
    [ -n "$sending" ] || return 0
    # git runs pre-push at the top of the slot's working tree.
    top=$(pwd -P) || return 0
    tab=$(printf '\t')
    list=$(printf '%s\n' "$CANOPY_CHECKLISTS" | while IFS=$tab read -r slot file; do
        if [ "$slot" = "$top" ]; then printf '%s' "$file" && break; fi
    done)
    [ -n "$list" ] && [ -f "$list" ] && [ -r "$list" ] || return 0
    size=$(wc -c <"$list") || return 0
    [ $((size)) -le @MAX_BYTES@ ] || return 0
    now=$(date +%s) || return 0
    repo=${list##*/}
    repo=${repo%.md}
    # The slot's own git directory, which no other slot reads: a worktree's, not the one its pool shares.
    own=$(git rev-parse --absolute-git-dir 2>/dev/null) || own=
    case ${CANOPY_DEADLINE-} in
        "" | *[!0-9]*) ;;
        *)
            if [ $((CANOPY_DEADLINE - now)) -le @LAST_STRETCH@ ]; then
                {
                    echo "[canopy] Pushed, not held, as this run is near canopy's deadline. $repo's checklist is" \
                        "below, and in $list, should this output be cut short. Diff this branch against its base and" \
                        "hold each item of the checklist to the diff; if one fails and there is time, commit the" \
                        "fix and push it. Answer each item in your result line's \`checklist\`," \
                        "under $repo: pass, fixed, held with the reason, or n/a."
                    echo
                    cat "$list"
                } >&2
                note shown "$sending"
                return 0
            fi
            ;;
    esac
    [ -n "$own" ] || return 0
    marker=$own/@MARKER@
    held_run=
    held_at=
    if [ -f "$marker" ]; then
        read -r held_run held_at <"$marker" 2>/dev/null || :
    fi
    case $held_at in "" | *[!0-9]*) held_at=0 ;; esac
    # Held already in this run, a moment ago: this is the push after the hold. A marker another run left in the slot,
    # or one from before a long stretch of work, counts for nothing.
    if [ "$held_run" = "${CANOPY_RUN_ID-}" ] && [ $((now - held_at)) -lt @WINDOW@ ]; then
        note sent "$sending"
        return 0
    fi
    { printf '%s %s\n' "${CANOPY_RUN_ID-}" "$now" >"$marker"; } 2>/dev/null || return 0
    note shown "$sending"
    {
        echo "[canopy] Push held, not rejected: nothing was sent. $repo's checklist is below, and in $list," \
            "should this output be cut short. Before this branch goes up, diff it against its base and hold each" \
            "item of the checklist to the diff. Commit a fix for each item that fails, then push again: the next" \
            "push goes through. Answer each item in your result line's \`checklist\`," \
            "under $repo: pass, fixed, held with the reason, or n/a."
        echo
        cat "$list"
    } >&2
    exit 1
}
# Notes for the harness, which reads them as the run ends, that the run was shown its list with the branch at the
# commit $2, or pushed $2 through: a line `<shown|sent> <run id> <commit>` in the slot's own git directory. Best effort:
# a note it cannot write loses only the record.
note() {
    if [ -n "$own" ]; then
        { printf '%s %s %s\n' "$1" "${CANOPY_RUN_ID-}" "$2" >>"$own/@PUSHES@"; } 2>/dev/null || :
    fi
}
# The marks go on a commit in one of the run's slots alone, at whose top git runs this hook: a repository the worker's
# tools make or use elsewhere, as a test's, is not the run's work.
mark=
if [ "$name" = prepare-commit-msg ]; then
    top=$(pwd -P) && mark=$(printf '%s\n' "${CANOPY_SLOTS-}" | while IFS= read -r slot; do
        if [ "$slot" = "$top" ]; then echo yes && break; fi
    done)
fi
if [ -n "$mark" ] && [ -n "${CANOPY_COMMIT_PREFIX-}" ] && [ -s "$1" ]; then
    # Not an empty subject or a comment, which git drops, nor one --autosquash matches the commit it is for by.
    case $(head -n 1 "$1") in
        "$CANOPY_COMMIT_PREFIX"* | "" | "#"* | fixup!* | squash!* | amend!*) ;;
        *) { printf '%s' "$CANOPY_COMMIT_PREFIX" && cat "$1"; } >"$1.canopy" && mv "$1.canopy" "$1" || exit ;;
    esac
fi
if [ -n "$mark" ] && [ -n "${CANOPY_COMMIT_TRAILERS-}" ]; then
    # A message whose last line has no newline, as a merge's has, would take the trailers into its last paragraph.
    if [ -s "$1" ] && [ -n "$(tail -c 1 "$1")" ]; then
        echo >>"$1" || exit
    fi
    printf '%s\n' "$CANOPY_COMMIT_TRAILERS" | while IFS= read -r trailer; do
        if [ -n "$trailer" ]; then
            git interpret-trailers --in-place --if-exists addIfDifferent --trailer "$trailer" "$1" || exit
        fi
    done || exit
fi
if [ "$name" = pre-push ] && [ -n "${CANOPY_CHECKLISTS-}" ]; then
    # The refs git would send, a line each, `<local ref> <local sha> <remote ref> <remote sha>`, none when there is
    # nothing to send: read once here, and handed on below to the repository's own hook, which reads them too.
    refs=$(cat) || exit
    read_refs=yes
    hold "$refs"
fi
# The hooks directory git would use without canopy's entry: dropping GIT_CONFIG_COUNT's entries from the last, the
# first that is not this one's. A tool may have added its own after canopy's, and handing on to this hook again would
# never end. A repository git cannot read yet has no hook to hand on to: `git init` writes HEAD in a reference
# transaction, which a recent git runs `reference-transaction` for, before there is a HEAD to find it by.
here=$(cd -P "${0%/*}" && pwd) || exit
n=${GIT_CONFIG_COUNT:-0}
while [ "$n" -gt 0 ]; do
    n=$((n - 1))
    hooks=$(GIT_CONFIG_COUNT=$n git rev-parse --git-path hooks 2>/dev/null) || exit 0
    if [ "$(cd -P "$hooks" 2>/dev/null && pwd)" != "$here" ]; then
        if [ -x "$hooks/$name" ] && [ -n "$read_refs" ]; then
            # The refs read above, as git handed them: each line with its newline, and nothing for none.
            { if [ -n "$refs" ]; then printf '%s\n' "$refs"; fi; } | "$hooks/$name" "$@"
            exit
        elif [ -x "$hooks/$name" ]; then
            exec "$hooks/$name" "$@"
        fi
        exit 0
    fi
done
""".replace("@MAX_BYTES@", str(checklists.MAX_BYTES + 1))
    .replace("@LAST_STRETCH@", str(LAST_STRETCH_SECONDS))
    .replace("@WINDOW@", str(HOLD_WINDOW_SECONDS))
    .replace("@MARKER@", HOLD_MARKER)
    .replace("@PUSHES@", PUSHES_LOG)
)


def files() -> dict[str, bytes]:
    """Return the hooks as the snapshot holds them, by relative path.

    Returns:
        The script under each of git's hook names, in `HOOKS_DIR`.
    """
    data = SCRIPT.encode()
    return {f"{HOOKS_DIR}/{name}": data for name in NAMES}


def is_hook(rel: str) -> bool:
    """Return whether `rel`, a path in the snapshot, is one of the hooks, which must be executable."""
    return rel.startswith(f"{HOOKS_DIR}/")


@dataclass(frozen=True)
class Marks:
    """What canopy's hooks put on each commit a run makes, as its prompt names them."""

    #: The trailers, each `Co-authored-by: <name> <<email>>`; none while `trust.commit_trailer` is off.
    trailers: Sequence[str] = ()
    #: What starts each subject, but a fixup's (`prompts.commit_prefix`); "" for none.
    prefix: str = ""


#: No marks: what a run that makes no commit gets.
NONE = Marks()


def marks(
    config: Config,
    *,
    key: str | None,
    model: str | None = None,
    planner_model: str | None = None,
) -> Marks:
    """Return what canopy puts on the commits of a run for ticket `key`, None for a task's.

    `model` is the worker's chosen model, which its trailer may name (`prompts.commit_trailer`), and `planner_model`
    that of the planner whose approved plan it follows, which a second trailer names (`prompts.planner_trailer`).

    Returns:
        The trailers and the prefix.
    """
    prefix = prompts.commit_prefix(config, key)
    if not config.trust.commit_trailer:
        return Marks(prefix=prefix)
    planner = prompts.planner_trailer(config, planner_model)
    return Marks((prompts.commit_trailer(config, model), *([planner] if planner is not None else [])), prefix)


def env(
    snapshot: Path,
    added: Marks,
    inherited: Mapping[str, str],
    lists: Mapping[Path, Path] | None = None,
    *,
    slots: Iterable[Path],
) -> dict[str, str]:
    """Return what a worker's environment needs for git to put `added` on its commits, through the hooks in `snapshot`.

    `slots` are the run's worktrees, whose commits alone get `added`: a repository the worker makes elsewhere, as a
    test of its own does, gets nothing of canopy's.
    `inherited` is the environment the worker would otherwise get, whose `GIT_CONFIG_*` entries come first. `lists`
    names, by each of the run's slots, the file in its answers directory that holds its repository's checklist, which
    `pre-push` holds the slot's push for (`checklists.file_of`); git is pointed at the hooks for those too, with no
    mark to add.

    Returns:
        The variables to merge over `inherited`, or none when there is nothing to add or hold.
    """
    # The hook matches its slot by `pwd -P`, so the slot's path is resolved. A path with a tab or a line feed cannot be
    # named on a line of the variable, and holds or marks nothing; canopy's slots and state directory have none.
    held = [
        f"{slot.resolve()}\t{file.absolute()}"
        for slot, file in (lists or {}).items()
        if not any(c in f"{slot}{file}" for c in "\t\n")
    ]
    marked = [str(slot.resolve()) for slot in slots if not any(c in str(slot) for c in "\t\n")]
    if not added.trailers and not added.prefix and not held:
        return {}
    count = inherited.get("GIT_CONFIG_COUNT", "")
    # git refuses a count that is not a number, whatever canopy adds, so one that is not is replaced, not kept.
    index = int(count) if count.isdigit() else 0
    return {
        "GIT_CONFIG_COUNT": str(index + 1),
        f"GIT_CONFIG_KEY_{index}": "core.hooksPath",
        f"GIT_CONFIG_VALUE_{index}": str(snapshot.absolute() / HOOKS_DIR),
        **({SLOTS_ENV: "\n".join(marked)} if added.trailers or added.prefix else {}),
        **({TRAILERS_ENV: "\n".join(added.trailers)} if added.trailers else {}),
        **({PREFIX_ENV: added.prefix} if added.prefix else {}),
        **({CHECKLISTS_ENV: "\n".join(held)} if held else {}),
    }


def pushes_after(git_dir: Path, run_id: str) -> list[tuple[str, str | None]]:
    """Take what `pre-push` noted of run `run_id` in the slot whose own git directory is `git_dir`, and remove it.

    The notes are the run's to write, so untrusted: a line that is not `<shown|sent> <run id> <commit>`, or names
    another run, counts for nothing, and only the first `MAX_PUSHES_BYTES` are read. Each showing of the list opens a
    stretch, and the next push let through closes it; one shown again while open keeps the first commit, since all
    that follows it came after the list. The file is removed, so a later run in the slot starts with none.

    Returns:
        Each stretch, oldest first: the commit the branch was at when the list was shown, and the commit of the next
        push let through, or None for one no push closed.
    """
    path = git_dir / PUSHES_LOG
    text = _read_bounded(path, MAX_PUSHES_BYTES)
    with contextlib.suppress(OSError):
        path.unlink(missing_ok=True)
    found: list[tuple[str, str | None]] = []
    opened: str | None = None
    for line in text.splitlines():
        match line.split():
            case [event, run, sha] if run == run_id and _COMMIT_RE.fullmatch(sha):
                if event == "shown" and opened is None:
                    opened = sha
                elif event == "sent" and opened is not None:
                    found.append((opened, sha))
                    opened = None
            case _:
                pass
    if opened is not None:
        found.append((opened, None))
    return found


def git_too_old(config: Config, runner: procs.Runner) -> str | None:
    """Return why canopy's marks cannot reach a worker's commits, when the git on `PATH` is older than `MIN_GIT`.

    Only while there are marks to add: canopy's trailer, or a prefix. A git that does not say its version, or cannot be
    run, is no finding here: a run's own git steps fail on it, and say so.

    Returns:
        The attention item's detail, or None.
    """
    if not config.trust.commit_trailer and not config.trust.commit_prefix:
        return None
    try:
        result = runner.run(hostgit.argv("--version"), env=hostgit.ENV, timeout=_GIT_VERSION_TIMEOUT_SECONDS)
    except procs.ProcError:
        return None
    found = _GIT_VERSION_RE.search(result.stdout) if result.ok else None
    if found is None or (int(found[1]), int(found[2])) >= MIN_GIT:
        return None
    least = ".".join(map(str, MIN_GIT))
    return (
        f"git {found[1]}.{found[2]} on PATH is older than {least}, which canopy's commit hooks need: workers' commits "
        f"get no trailer or prefix, and each run's note names them; install git {least} or later"
    )


def _read_bounded(path: Path, limit: int) -> str:
    # The first `limit` bytes of the regular file at `path`, its last partial line dropped; "" for none, a link's
    # included, since the file is in a directory the run may write.
    try:
        fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
    except OSError:
        return ""
    with os.fdopen(fd, "rb") as f:
        if not stat.S_ISREG(os.fstat(f.fileno()).st_mode):
            return ""
        data = f.read(limit + 1)
    if len(data) > limit:
        data = data[: data.rfind(b"\n", 0, limit) + 1]
    return data.decode("ascii", errors="replace")
