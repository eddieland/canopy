"""`canopy sandbox setup`: what running agents in a sandbox needs on this machine (DESIGN §24, docs/SANDBOX.md).

It copies `canopy-sandbox`'s policy templates to where the wrapper reads them, never over one already there, and says
when one already there lets a run write the operator's own caches, as templates from before `@CACHE@` did, or read
the operator's OpenCode data, or leaves out the run's own, as templates from before `@DATA@` did; installs
the `srt` that the wrapper's lockfile pins, with `npm ci`, into a directory of canopy's own, which no sandbox can
write; and checks what it cannot install, because that needs root: bubblewrap, socat, and ripgrep on Linux, ripgrep
on macOS, and unprivileged user namespaces. It also checks what srt itself only warns about, in a debug log nobody
reads: a bubblewrap older than srt fully supports, and a machine srt has no seccomp filter for. It changes no config:
the sandbox is opt-in until the operator prefixes the command templates, and `canopy init` prints the line for
`worker_cmd_prefix`.
"""

from __future__ import annotations

import json
import os
import re
import shutil
import sys
from collections.abc import Sequence
from dataclasses import dataclass, field
from pathlib import Path

import canopy_sandbox

from canopy.core import config
from canopy.infra import procs

# What Linux needs beside srt, each as a command that answers when it is installed, and the package that has it.
LINUX_TOOLS = (
    (("bwrap", "--version"), "bubblewrap"),
    (("socat", "-V"), "socat"),
    (("rg", "--version"), "ripgrep"),
)
# The oldest bubblewrap srt fully supports (its OLDEST_FULLY_SUPPORTED_BWRAP_VERSION). An older one still sandboxes.
OLDEST_BWRAP = (0, 5, 0)
OLD_BWRAP = """\
bubblewrap {version} is older than 0.5.0, the oldest srt fully supports. On it, srt cannot hide a socket, fifo, or
device that a template denies reading, and leaves on the host the mount points of a sandbox that was killed. Install
bubblewrap 0.5.0 or later, from your distribution's backports or a newer release of it."""
# The machines srt ships its seccomp helper for, by the name uname gives them. Without the helper, srt runs with no
# filter, and logs that only with --debug: nothing stops a sandboxed command making a Unix socket.
SECCOMP_MACHINES = ("x86_64", "aarch64")
NO_SECCOMP = """\
srt has no seccomp filter for {machine}, only for {machines}. Without it, a sandboxed command can connect to any
Unix socket it can see, such as your SSH agent's or Docker's. Do not rely on the sandbox on this machine."""
# Ubuntu 24.04 and later set this to 1, which leaves bubblewrap's user namespace without the capabilities it needs.
APPARMOR_USERNS = Path("/proc/sys/kernel/apparmor_restrict_unprivileged_userns")
USERNS_FIX = """\
bubblewrap cannot make a user namespace: AppArmor restricts unprivileged ones. Lift the restriction, now and at boot:
    sudo sysctl -w kernel.apparmor_restrict_unprivileged_userns=0
    echo 'kernel.apparmor_restrict_unprivileged_userns = 0' | sudo tee /etc/sysctl.d/60-canopy-sandbox.conf"""
WRAPPER_MISSING = """\
canopy-sandbox is not on PATH. It installs with canopy: run the install again, with --reinstall, and put uv's tool
directory on PATH (`uv tool update-shell`)."""
# npm ci installs exactly the lockfile, and checks each package's integrity hash. srt has no install scripts, and none
# of its dependencies may run one. A Node older than a package's `engines` fails the install instead of only warning.
NPM_CI = ("npm", "ci", "--ignore-scripts", "--engine-strict", "--no-audit", "--no-fund")
# The lockfile of the last install that finished and answered the pinned version, written only then: npm ci needs the
# lockfile itself in place before it runs, so that copy says nothing about whether the install behind it succeeded.
INSTALLED_LOCK = "canopy-installed.lock"
NPM_TIMEOUT = 600
SHARED_CACHE = """\
{template} lets a sandboxed run write {paths}: your own caches, whose packages and programs your tools run outside
the sandbox, the agent runtime's for the overseer included. Remove them from its allowWrite and allowRead, and
add @CACHE@ to both, as the shipped template does (docs/SANDBOX.md)."""
OPERATOR_DATA = """\
{template} lets a sandboxed run read {paths}: your own OpenCode data, whose logins and config your OpenCode, the
overseer's included, acts on outside the sandbox. Remove them from its allowRead and allowWrite, and add @DATA@ to
both, as the shipped template does: a run's OpenCode keeps its data there, with a copy of your logins
(docs/SANDBOX.md)."""
NO_DATA = """\
{template} leaves @DATA@ out of its allowRead or allowWrite, so a sandboxed run's OpenCode finds none of your logins.
Add it to both, as the shipped template does (docs/SANDBOX.md)."""
# The roles whose command is OpenCode, which keeps its data, logins included, in the run's own data directory.
RUNTIME_ROLES = ("worker", "chore", "review")


@dataclass
class Report:
    """What setup wrote and kept, what it did about srt, and each thing left for the operator to do, as a paragraph."""

    written: list[Path] = field(default_factory=list)
    kept: list[Path] = field(default_factory=list)
    runtime: str = ""
    todo: list[str] = field(default_factory=list)


def run_setup(runner: procs.Runner, platform: str = sys.platform) -> Report:
    """Copy the policy templates, install the pinned srt, and check what needs root, on a `platform` machine.

    Returns:
        What was done, and what is left to do.
    """
    report = Report()
    _copy_templates(report)
    _install_runtime(runner, report)
    _check_platform(runner, platform, report)
    if os.geteuid() == 0:
        report.todo.append(
            "canopy is running as root. Run it as yourself: a root caller's sandbox needs CAP_SETFCAP, and its "
            "command keeps every capability inside the sandbox's namespace.",
        )
    if not _answers(runner, ["canopy-sandbox"]):
        report.todo.append(WRAPPER_MISSING)
    return report


def pinned_version() -> str:
    """Return the version of srt that the wrapper's lockfile pins.

    Returns:
        The version, as the lockfile's package.json names it.
    """
    spec = json.loads((canopy_sandbox.RUNTIME_SPEC / "package.json").read_text(encoding="utf-8"))
    version: str = spec["dependencies"][canopy_sandbox.SRT_PACKAGE]
    return version


def _copy_templates(report: Report) -> None:
    target = config.user_config_dir() / "sandbox"
    try:
        # Like the user config beside it, only the operator writes here; the templates deny every sandbox reading it.
        target.mkdir(mode=0o700, parents=True, exist_ok=True)
        for role in canopy_sandbox.ROLES:
            path = target / f"{role}.json"
            if path.exists():
                report.kept.append(path)
                if shared := _shared_caches(path):
                    report.todo.append(SHARED_CACHE.format(template=path, paths=", ".join(shared)))
                if (data := _data_todo(path, role)) is not None:
                    report.todo.append(data)
                continue
            path.write_text((canopy_sandbox.TEMPLATES / path.name).read_text(encoding="utf-8"), encoding="utf-8")
            report.written.append(path)
    except OSError as e:
        report.todo.append(f"the policy templates could not be copied: {e}")


def _shared_caches(template: Path) -> list[str]:
    """List what `template` lets a run write in the operator's cache directory, but inside a role's cache directory.

    The directory that holds every role's is flagged too: a run that can write it can write every role's.

    Returns:
        Each such `allowWrite` entry, as the template spells it; none for a template that cannot be read.
    """
    try:
        policy = json.loads(template.read_text(encoding="utf-8"))
        writable: object = policy["filesystem"]["allowWrite"]
    except (OSError, ValueError, KeyError, TypeError):
        return []
    if not isinstance(writable, list):
        return []
    xdg = Path(os.environ.get("XDG_CACHE_HOME", ""))
    roots = {Path.home() / ".cache", *([xdg] if xdg.is_absolute() else [])}
    entries: list[object] = writable
    return [
        entry
        for entry in entries
        if isinstance(entry, str)
        and any(_within(Path(entry).expanduser(), root, but=root / "canopy" / "sandbox") for root in roots)
    ]


def _data_todo(template: Path, role: str) -> str | None:
    """Say what `template`, for `role`, needs changed about OpenCode's data directory, if anything.

    It needs changing when it names the operator's OpenCode data directory, or anything in it, to read or write, or,
    for a role that runs OpenCode, when it does not name the run's own, `@DATA@`, in both.

    Returns:
        The paragraph for the operator, or None for a template that needs nothing, or cannot be read.
    """
    try:
        policy = json.loads(template.read_text(encoding="utf-8"))
        lists: list[object] = [policy["filesystem"].get(key, []) for key in ("allowRead", "allowWrite")]
    except (OSError, ValueError, KeyError, TypeError, AttributeError):
        return None
    entries = [[e for e in entries if isinstance(e, str)] for entries in lists if isinstance(entries, list)]
    if len(entries) != len(lists):
        return None
    operator = canopy_sandbox.data_home() / "opencode"
    roots = {operator, Path.home() / ".local" / "share" / "opencode"}
    named = [e for e in dict.fromkeys(e for es in entries for e in es) if any(_under(e, root) for root in roots)]
    if named:
        return OPERATOR_DATA.format(template=template, paths=", ".join(named))
    if role in RUNTIME_ROLES and not all("@DATA@" in es for es in entries):
        return NO_DATA.format(template=template)
    return None


def _under(entry: str, root: Path) -> bool:
    return not entry.startswith("@") and Path(entry).expanduser().is_relative_to(root)


def _within(path: Path, root: Path, *, but: Path) -> bool:
    """Whether `path` is `root` or under it, and not under `but`, though it may be `but` itself.

    Returns:
        True when it is.
    """
    return path.is_relative_to(root) and not (path.is_relative_to(but) and path != but)


def _install_runtime(runner: procs.Runner, report: Report) -> None:
    """Install the pinned srt into the wrapper's runtime directory, unless it is there and runs."""
    target = canopy_sandbox.runtime_dir()
    version = pinned_version()
    lock = canopy_sandbox.RUNTIME_SPEC / "package-lock.json"
    installed = target / INSTALLED_LOCK
    if installed.is_file() and installed.read_bytes() == lock.read_bytes() and _srt_version(runner, target) == version:
        report.runtime = f"kept    srt {version} in {target}"
        return
    if not _answers(runner, ["npm", "--version"]):
        report.todo.append(
            f"npm is not on PATH, so srt {version} is not installed. Install Node 22.12 or later with npm, then run "
            "`canopy sandbox setup` again.",
        )
        return
    try:
        target.mkdir(mode=0o700, parents=True, exist_ok=True)
        installed.unlink(missing_ok=True)
        for name in ("package.json", "package-lock.json"):
            shutil.copyfile(canopy_sandbox.RUNTIME_SPEC / name, target / name)
    except OSError as e:
        report.todo.append(f"srt {version} is not installed: {e}")
        return
    done = runner.run(list(NPM_CI), cwd=target, timeout=NPM_TIMEOUT)
    if not done.ok:
        report.todo.append(f"npm could not install srt {version} in {target}:\n    {_tail(done.stderr or done.stdout)}")
        return
    found = _srt_version(runner, target)
    if found != version:
        report.todo.append(f"srt in {target} answers {found or 'nothing'} to --version, not {version}.")
        return
    try:
        shutil.copyfile(lock, installed)
    except OSError as e:
        report.todo.append(f"srt {version} is installed in {target}, but {installed} could not be written: {e}")
        return
    report.runtime = f"installed srt {version} in {target}"


def _srt_version(runner: procs.Runner, target: Path) -> str | None:
    srt = target / "node_modules" / ".bin" / "srt"
    if not srt.is_file():
        return None
    try:
        done = runner.run([str(srt), "--version"], timeout=60)
    except procs.ProcError:
        return None
    return done.stdout.strip() if done.ok else None


def _check_platform(runner: procs.Runner, platform: str, report: Report) -> None:
    if platform == "darwin":
        if not _answers(runner, ["rg", "--version"]):
            report.todo.append("srt needs ripgrep: brew install ripgrep")
        return
    if not platform.startswith("linux"):
        report.todo.append(f"srt sandboxes on Linux and macOS, not on {platform}.")
        return
    missing = [package for args, package in LINUX_TOOLS if not _answers(runner, list(args))]
    if missing:
        packages = " ".join(missing)
        report.todo.append(
            f"srt needs {', '.join(missing)}. Install them with your package manager, such as:\n"
            f"    sudo apt-get install {packages}",
        )
    if "bubblewrap" not in missing:
        _check_bwrap_version(runner, report)
        _check_userns(runner, report)
    machine = os.uname().machine
    if machine not in SECCOMP_MACHINES:
        report.todo.append(NO_SECCOMP.format(machine=machine, machines=" and ".join(SECCOMP_MACHINES)))


def _check_bwrap_version(runner: procs.Runner, report: Report) -> None:
    """Check that bubblewrap is one srt fully supports. A version it does not say is not guessed at, as srt does not."""
    done = runner.run(["bwrap", "--version"], timeout=30)
    found = re.search(r"(\d+)\.(\d+)(?:\.(\d+))?", done.stdout) if done.ok else None
    if found is None:
        return
    major, minor, patch = found.groups()
    if (int(major), int(minor), int(patch or 0)) < OLDEST_BWRAP:
        report.todo.append(OLD_BWRAP.format(version=found.group()))


def _check_userns(runner: procs.Runner, report: Report) -> None:
    """Check that bubblewrap can make a sandbox, which needs an unprivileged user namespace with its capabilities."""
    done = runner.run(["bwrap", "--ro-bind", "/", "/", "true"], timeout=30)
    if done.ok:
        return
    try:
        restricted = APPARMOR_USERNS.read_text(encoding="utf-8").strip() == "1"
    except OSError:
        restricted = False
    report.todo.append(
        USERNS_FIX if restricted else f"bubblewrap cannot make a sandbox here:\n    {_tail(done.stderr)}",
    )


def _answers(runner: procs.Runner, args: Sequence[str]) -> bool:
    """Whether the command `args` names is installed: found on PATH and started. Its exit status does not matter.

    Returns:
        True when it started.
    """
    try:
        runner.run(args, timeout=30)
    except procs.ProcError:
        return False
    return True


def _tail(text: str) -> str:
    lines = text.strip().splitlines()
    return "\n    ".join(lines[-5:]) if lines else "(no output)"
