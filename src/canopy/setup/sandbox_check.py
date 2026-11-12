"""`canopy sandbox check`: whether the sandbox holds on this machine, for a worker (DESIGN §24, docs/SANDBOX.md).

It runs a plain script, no model, through `canopy-sandbox worker`, the operator's own `worker.json`, and the `srt`
`canopy sandbox setup` installed, in a worktree of a repository's primary clone that it makes for the check and
removes after: never one of canopy's slots, which nothing would tidy. The worktree has no files checked out, so
making it runs no filter the repository's attributes name, and costs a large repository nothing.

The script tries what a sandboxed worker must not do, and what it must still do, so a sandbox that refuses everything
fails as one that refuses nothing does.

A write is checked on the host, never by the script's own status: under a directory the policy denies, `srt` gives the
command a `tmpfs` that takes the write and drops it when the run ends. Each thing the check plants, the file it tries
to read and whatever a sandbox that did not hold let the script write, carries a name made for this check, and is
removed before it returns.

It is the short form of the canary (`tests/canopy_sandbox/test_sandbox_canary.py`), for an operator with canopy
installed and no checkout of it: one role, the worker's, and the denials an operator relies on first.
"""

from __future__ import annotations

import contextlib
import dataclasses
import secrets
import shutil
import tempfile
from collections.abc import Iterator, Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path

import canopy_sandbox

from canopy.core import config, hostgit, sandboxing
from canopy.infra import procs

#: The role checked: the one whose template `worker_cmd`, `private_worker_cmd`, and `plan_cmd` run under.
ROLE = "worker"
#: What every name the check plants starts with, before a token of the check's own.
PREFIX = "canopy-sandbox-check-"
#: A host the shipped templates do not allow, and no operator's is likely to.
DENIED_HOST = "example.com"
#: The allowed host tried first when the template lists it, as the shipped one does: one that answers anyone.
PREFERRED_HOST = "github.com"
_GIT_TIMEOUT = 60
_RUN_TIMEOUT = 180
# One line per attempt, `KEY 1` when the command succeeded inside the sandbox and `KEY 0` when it did not. Each
# attempt's one path, name, or URL is `$1` of its own shell, so none is ever read as shell. The commit runs no hook:
# one of the repository's could fail it for reasons of its own. `proxy-refused` asks whether srt's proxy answered the
# host off the allowlist with its 403, which tells a refusal from a host that could not be reached anyway.
_SCRIPT = """\
try() { if sh -c "$2" sh "$3" >/dev/null 2>&1; then echo "$1 1"; else echo "$1 0"; fi; }
try read-home 'cat "$1"' "$1"
try read-config 'cat "$1"' "$2"
try write-home 'echo x > "$1"' "$3"
try write-git 'echo x > "$1"' "$4"
try move-ref 'git branch "$1"' "$5"
try commit 'echo x > "$1" && git add -f "$1" && git -c user.name=canopy -c user.email=canopy@localhost \
    -c commit.gpgsign=false -c core.hooksPath=/dev/null commit -qm check' "$5"
if [ -n "$6" ]; then
    try reach-denied 'curl -sS -m 10 -o /dev/null "$1"' "$6"
    try proxy-refused '[ "$(curl -sS -m 10 -o /dev/null -w "%{http_connect}" "$1")" = 403 ]' "$6"
fi
if [ -n "$7" ]; then try reach-allowed 'curl -sS -m 10 -o /dev/null "$1"' "$7"; fi
"""


@dataclass(frozen=True)
class Attempt:
    """One thing the script tried inside the sandbox, and whether the sandbox let it."""

    #: What was tried, as the operator reads it.
    name: str
    #: Whether it happened: for a write, whether it reached the host.
    allowed: bool
    #: Whether a sandbox that holds allows it: True for a positive control.
    expected: bool

    @property
    def ok(self) -> bool:
        """Whether the sandbox did what it should."""
        return self.allowed == self.expected


@dataclass(frozen=True)
class Report:
    """What the check found."""

    #: Each attempt, in the order tried. Empty when the script never ran.
    attempts: Sequence[Attempt] = ()
    #: What was left unchecked, and why, each as a sentence.
    skipped: Sequence[str] = ()
    #: Why the script never ran inside the sandbox, when it did not.
    error: str = ""
    #: What the check made and could not remove, for the operator to remove by hand.
    left: Sequence[str] = ()

    @property
    def ok(self) -> bool:
        """Whether the script ran and the sandbox did what it should at every attempt."""
        return not self.error and bool(self.attempts) and all(attempt.ok for attempt in self.attempts)


def run_check(runner: procs.Runner, repo: Path, *, network: bool = True) -> Report:
    """Run the check in a worktree of the primary clone `repo`, made for it and removed after.

    Args:
        runner: Runs git and the wrapper.
        repo: A repository's primary clone, which must have a commit.
        network: Whether to try a host off the template's allowlist and one on it, which needs curl and a network.

    Returns:
        Each attempt, or why the script never ran.
    """
    try:
        return _check(runner, repo, network=network)
    except OSError as e:
        return Report(error=f"the check could not be set up: {e}")


def _check(runner: procs.Runner, repo: Path, *, network: bool) -> Report:
    token = secrets.token_hex(8)
    name = f"{PREFIX}{token}"
    common = _common_dir(runner, repo)
    if common is None:
        return Report(error=f"git could not read the repository at {repo}")
    hosts = _Hosts.choose(network=network)
    planted = _Planted(
        secret=Path.home() / f".{name}",
        config=_config_file(),
        written=Path.home() / f".{name}.written",
        shared=common / name,
        branch=name,
    )
    left: list[str] = []
    try:
        with _worktree(runner, repo, left) as made:
            if isinstance(made, str):
                return Report(error=made)
            slot, objects = made
            planted.secret.write_text(f"{token}\n", encoding="utf-8")
            planted.secret.chmod(0o600)
            outcome = _run_script(runner, slot, objects, planted, hosts)
            if isinstance(outcome, str):
                report = Report(skipped=hosts.skipped, error=outcome)
            else:
                attempts, unsure = _attempts(runner, repo, planted, hosts, outcome, objects=objects)
                report = Report(attempts, (*hosts.skipped, *unsure))
    finally:
        left += _clean(runner, repo, planted)
    return dataclasses.replace(report, left=tuple(left))


def _config_file() -> Path:
    """Return the file of canopy's config the script tries to read: the user file, or else the worker's template.

    The template is always there, since the wrapper refuses to run without it; the user file is the one a worker that
    read it would learn the most from.
    """
    user = config.user_config_path()
    return user if user.is_file() else canopy_sandbox.template_path(ROLE)


@dataclass(frozen=True)
class _Planted:
    """What the check plants for the script to try, each under a name of the check's own."""

    #: A file in the operator's home that the script tries to read.
    secret: Path
    #: A file of canopy's config that the script tries to read, which the check did not make and does not remove.
    config: Path
    #: A file in the operator's home that the script tries to write.
    written: Path
    #: A file in the repository's common git directory, beside its hooks and config, that the script tries to write.
    shared: Path
    #: A branch the script tries to make, and the file it commits in the worktree.
    branch: str


@dataclass(frozen=True)
class _Hosts:
    """The URLs the script tries to reach, each empty when it is not tried."""

    denied: str = ""
    allowed: str = ""
    skipped: Sequence[str] = ()

    @classmethod
    def choose(cls, *, network: bool) -> _Hosts:
        """Choose the hosts from the operator's worker template.

        Returns:
            A host off its allowlist and one on it, or neither, with why.
        """
        if not network:
            return cls(skipped=("the network was not checked, as asked.",))
        if shutil.which("curl") is None:
            return cls(skipped=("the network was not checked: curl is not on PATH.",))
        listed = _allowed_domains()
        skipped: list[str] = []
        denied = "" if any(_matches(entry, DENIED_HOST) for entry in listed) else f"https://{DENIED_HOST}"
        if not denied:
            skipped.append(f"a host off the allowlist was not tried: the template allows {DENIED_HOST}.")
        named = [host for host in listed if "*" not in host]
        allowed = PREFERRED_HOST if PREFERRED_HOST in named else next(iter(named), "")
        if not allowed:
            skipped.append("an allowed host was not tried: the template's allowedDomains names none without a `*`.")
        return cls(denied, f"https://{allowed}" if allowed else "", tuple(skipped))


def _matches(entry: str, host: str) -> bool:
    """Whether the allowlist entry `entry` allows `host`: by name, or as `*.name` allows every name under it.

    Returns:
        True when it does, on any port the entry names.
    """
    name = entry.rsplit(":", 1)[0] if entry.rsplit(":", 1)[-1].isdigit() else entry
    return name in {host, "*"} or (name.startswith("*.") and host.endswith(name[1:]))


def _allowed_domains() -> list[str]:
    """Return the hosts the operator's worker template allows, or none when it cannot be read: the wrapper says why."""
    try:
        template = canopy_sandbox.load_template(ROLE)
    except canopy_sandbox.SandboxError:
        return []
    network: object = template.get("network") if isinstance(template, dict) else None
    domains: object = network.get("allowedDomains") if isinstance(network, dict) else None
    if not isinstance(domains, list):
        return []
    entries: list[object] = domains
    return [entry for entry in entries if isinstance(entry, str)]


def _common_dir(runner: procs.Runner, repo: Path) -> Path | None:
    done = _git(runner, repo, "rev-parse", "--path-format=absolute", "--git-common-dir")
    return Path(done.stdout.strip()) if done is not None and done.ok and done.stdout.strip() else None


@contextlib.contextmanager
def _worktree(runner: procs.Runner, repo: Path, left: list[str]) -> Iterator[tuple[Path, Path] | str]:
    """Make a detached worktree of `repo`, with no files checked out, and an object directory, and remove both after.

    What could not be removed is added to `left`. Only this worktree's record is removed from the repository: pruning
    would take every stale one with it.

    Yields:
        The worktree and the object directory, or why the worktree could not be made.
    """
    root = Path(tempfile.mkdtemp(prefix="canopy-sandbox-check."))
    slot, objects = root / "slot", root / "objects"
    try:
        objects.mkdir()
        added = _git(runner, repo, "worktree", "add", "--quiet", "--no-checkout", "--detach", str(slot))
        if added is None or not added.ok:
            why = added.stderr.strip() if added is not None else "git is not on PATH"
            yield f"a worktree of {repo} could not be made for the check: {why}"
            return
        yield slot, objects
    finally:
        removed = _git(runner, repo, "worktree", "remove", "--force", str(slot))
        if slot.exists() and (removed is None or not removed.ok):
            left.append(f"the worktree {slot}, and its record in {repo} (`git worktree prune`)")
        shutil.rmtree(root, ignore_errors=True)
        if root.exists():
            left.append(str(root))


def _run_script(
    runner: procs.Runner,
    slot: Path,
    objects: Path,
    planted: _Planted,
    hosts: _Hosts,
) -> Mapping[str, bool] | str:
    """Run the script in `slot` through the wrapper, as canopy starts a worker.

    Returns:
        Whether each attempt's command succeeded inside the sandbox, by its key, or why the script did not run.
    """
    args = [str(planted.secret), str(planted.config), str(planted.written), str(planted.shared), planted.branch]
    command = ["sh", "-c", _SCRIPT, "sh", *args, hosts.denied, hosts.allowed]
    env = {canopy_sandbox.OBJECTS_ENV: str(objects)}
    try:
        done = runner.run([str(sandboxing.WRAPPER), ROLE, "--", *command], cwd=slot, env=env, timeout=_RUN_TIMEOUT)
    except procs.ProcError as e:
        return f"{sandboxing.WRAPPER} could not be run: {e}. It installs with canopy; run the install again."
    results = dict(line.split(" ") for line in done.stdout.splitlines() if line.count(" ") == 1)
    expected = {"read-home", "read-config", "write-home", "write-git", "move-ref", "commit"}
    expected |= {"reach-denied", "proxy-refused"} if hosts.denied else set()
    expected |= {"reach-allowed"} if hosts.allowed else set()
    if done.timed_out or not expected <= results.keys():
        said = done.stderr.strip() or done.stdout.strip() or f"it exited {done.returncode} and printed nothing"
        return f"the check did not run in the sandbox:\n    {'\n    '.join(said.splitlines()[-8:])}"
    return {key: value == "1" for key, value in results.items()}


def _attempts(
    runner: procs.Runner,
    repo: Path,
    planted: _Planted,
    hosts: _Hosts,
    succeeded: Mapping[str, bool],
    *,
    objects: Path,
) -> tuple[list[Attempt], list[str]]:
    """Say what the sandbox let the script do: its reads and requests by their status, its writes by the host.

    The commit counts when its objects are in the run's object directory on the host, where canopy reads them to push.
    A host off the allowlist that could not be reached, and not because srt's proxy refused it, shows nothing either
    way.

    Returns:
        Each attempt, the denials first, and what could not be told, each as a sentence.
    """
    ref = _git(runner, repo, "show-ref", "--verify", "--quiet", f"refs/heads/{planted.branch}")
    attempts = [
        Attempt("read a file in your home directory", succeeded["read-home"], expected=False),
        Attempt(f"read canopy's config, {planted.config.name}", succeeded["read-config"], expected=False),
        Attempt("write a file in your home directory", _there(planted.written), expected=False),
        Attempt("write beside the repository's hooks and git config", _there(planted.shared), expected=False),
        Attempt("make a branch, in the refs every slot shares", ref is not None and ref.ok, expected=False),
    ]
    unsure: list[str] = []
    if hosts.denied and (succeeded["reach-denied"] or succeeded["proxy-refused"]):
        attempts.append(Attempt(f"reach {hosts.denied}, off the allowlist", succeeded["reach-denied"], expected=False))
    elif hosts.denied:
        unsure.append(f"{hosts.denied} could not be reached, and not because the sandbox refused it: not checked.")
    committed = succeeded["commit"] and any(objects.iterdir())
    attempts.append(Attempt("commit in the worktree, its objects in the run's own directory", committed, expected=True))
    if hosts.allowed:
        attempts.append(Attempt(f"reach {hosts.allowed}, on the allowlist", succeeded["reach-allowed"], expected=True))
    return attempts, unsure


def _there(path: Path) -> bool:
    # A link counts, wherever it leads.
    return path.is_symlink() or path.exists()


def _clean(runner: procs.Runner, repo: Path, planted: _Planted) -> list[str]:
    """Remove what the check planted, and what a sandbox that did not hold let the script leave.

    Returns:
        What is still there, for the operator to remove.
    """
    left: list[str] = []
    for path in (planted.secret, planted.written, planted.shared):
        with contextlib.suppress(OSError):
            path.unlink(missing_ok=True)
        if _there(path):
            left.append(str(path))
    ref = f"refs/heads/{planted.branch}"
    _git(runner, repo, "update-ref", "-d", ref)
    kept = _git(runner, repo, "show-ref", "--verify", "--quiet", ref)
    if kept is not None and kept.ok:
        left.append(f"the branch {planted.branch} in {repo}")
    return left


def _git(runner: procs.Runner, repo: Path, *args: str) -> procs.Result | None:
    """Run git in `repo` as the harness does on the host.

    Returns:
        What came back, or None when git could not be started.
    """
    try:
        return runner.run(hostgit.argv(*args), cwd=repo, env=hostgit.ENV, timeout=_GIT_TIMEOUT)
    except procs.ProcError:
        return None
