"""`canopy sandbox setup`: the templates, the pinned srt, and what needs root (docs/SANDBOX.md).

PATH holds only the commands a test puts there: small Python stubs that record their arguments, so whether bubblewrap
or npm is installed on the machine running the tests does not matter.
"""

import json
import os
import sys
from collections.abc import Iterator
from dataclasses import dataclass
from pathlib import Path
from typing import TypedDict
from unittest import mock

import canopy_sandbox
import pytest

from canopy.cli.main import main
from canopy.infra.procs import SubprocessRunner
from canopy.setup import sandbox
from tests.conftest import CanopyEnv, executable

# Records its arguments and working directory, prints $FAKE_STDOUT_<NAME>, then exits with $FAKE_EXIT_<NAME>, or 0.
STUB = """\
#!{python}
import json, os, sys
from pathlib import Path
name = Path(sys.argv[0]).name
with open({log!r}, "a") as f:
    f.write(json.dumps({{"argv": [name, *sys.argv[1:]], "cwd": os.getcwd()}}) + "\\n")
sys.stdout.write(os.environ.get("FAKE_STDOUT_" + name.upper(), ""))
sys.stderr.write(os.environ.get("FAKE_STDERR", ""))
sys.exit(int(os.environ.get("FAKE_EXIT_" + name.upper(), "0")))
"""
# `npm ci`: replaces node_modules, as npm does, with an srt from the lockfile that answers its version to --version.
NPM = STUB.replace(
    "sys.stderr.write",
    """if sys.argv[1:2] == ["ci"] and os.environ.get("FAKE_EXIT_NPM", "0") == "0":
    import shutil
    shutil.rmtree("node_modules", ignore_errors=True)
    lock = json.loads(Path("package-lock.json").read_text())
    version = lock["packages"]["node_modules/@anthropic-ai/sandbox-runtime"]["version"]
    srt = Path("node_modules/.bin/srt")
    srt.parent.mkdir(parents=True)
    srt.write_text("#!{python}\\nprint(" + repr(version) + ")\\n")
    srt.chmod(0o755)
sys.stderr.write""",
)
LINUX_COMMANDS = ("bwrap", "socat", "rg", "npm", "canopy-sandbox")


class Call(TypedDict):
    """One run of a stub."""

    argv: list[str]
    cwd: str


@dataclass(frozen=True)
class Machine:
    """The machine the stubs play.

    The stubs' directory, which is all of PATH, the log of what they were run with, the user's id, uname, and whether
    its kernel lacks IPv6.
    """

    bin: Path
    log: Path
    geteuid: mock.NonCallableMock
    uname: mock.NonCallableMock
    ipv6_missing: mock.NonCallableMock

    def install(self, *names: str) -> None:
        for name in names:
            path = self.bin / name
            executable(path, (NPM if name == "npm" else STUB).format(python=sys.executable, log=str(self.log)))

    def calls(self, name: str) -> list[Call]:
        if not self.log.exists():
            return []
        calls: list[Call] = [json.loads(line) for line in self.log.read_text().splitlines()]
        return [c for c in calls if c["argv"][0] == name]


@pytest.fixture
def machine(canopy_env: CanopyEnv, tmp_path: Path) -> Iterator[Machine]:
    """An x86_64 machine with IPv6 and nothing installed, run by a user who is not root, with HOME in `canopy_env`."""
    assert canopy_env.home.is_dir()
    (tmp_path / "bin").mkdir()
    with (
        mock.patch.dict(os.environ, {"PATH": str(tmp_path / "bin")}),
        mock.patch.object(os, "geteuid", autospec=True, return_value=1000) as geteuid,
        mock.patch.object(os, "uname", autospec=True, return_value=uname("x86_64")) as host,
        mock.patch.object(canopy_sandbox, "ipv6_missing", autospec=True, return_value=False) as ipv6_missing,
    ):
        yield Machine(tmp_path / "bin", tmp_path / "calls.jsonl", geteuid, host, ipv6_missing)


def uname(machine: str) -> os.uname_result:
    return os.uname_result(("Linux", "host", "6.8.0", "#1 SMP", machine))


def runtime(canopy_env: CanopyEnv) -> Path:
    return canopy_env.home / ".local" / "share" / "canopy" / "sandbox-runtime"


def test_setup_installs_what_it_can_and_keeps_it_on_the_next_run(machine: Machine, canopy_env: CanopyEnv) -> None:
    machine.install(*LINUX_COMMANDS)

    report = sandbox.run_setup(SubprocessRunner(), "linux")

    assert report.todo == []
    templates = canopy_env.home / ".config" / "canopy" / "sandbox"
    assert report.written == [templates / f"{role}.json" for role in canopy_sandbox.ROLES]
    assert templates.stat().st_mode & 0o777 == 0o700
    for path in report.written:
        assert path.read_text() == (canopy_sandbox.TEMPLATES / path.name).read_text()
    version = sandbox.pinned_version()
    assert report.runtime == f"installed srt {version} in {runtime(canopy_env)}"
    [npm] = machine.calls("npm")[-1:]
    assert npm == {"argv": list(sandbox.NPM_CI), "cwd": str(runtime(canopy_env))}
    lock = canopy_sandbox.RUNTIME_SPEC / "package-lock.json"
    assert (runtime(canopy_env) / "package-lock.json").read_bytes() == lock.read_bytes()
    assert (runtime(canopy_env) / sandbox.INSTALLED_LOCK).read_bytes() == lock.read_bytes()
    assert machine.calls("bwrap")[-1]["argv"] == ["bwrap", "--ro-bind", "/", "/", "true"]

    again = sandbox.run_setup(SubprocessRunner(), "linux")

    assert (again.written, again.kept, again.todo) == ([], report.written, [])
    assert again.runtime == f"kept    srt {version} in {runtime(canopy_env)}"
    assert [c for c in machine.calls("npm") if c["argv"][1:2] == ["ci"]] == [npm]


def test_a_template_already_there_is_kept_as_it_is(machine: Machine, canopy_env: CanopyEnv) -> None:
    machine.install(*LINUX_COMMANDS)
    mine = canopy_env.home / ".config" / "canopy" / "sandbox" / "worker.json"
    mine.parent.mkdir(parents=True)
    mine.write_text('{"edited": true}')

    report = sandbox.run_setup(SubprocessRunner(), "linux")

    assert mine in report.kept
    assert mine.read_text() == '{"edited": true}'


def test_a_template_kept_that_lets_a_run_write_the_operators_caches_is_to_be_changed(
    machine: Machine,
    canopy_env: CanopyEnv,
) -> None:
    """Templates from before `@CACHE@` let a worker write `~/.cache/opencode`, which the overseer runs code from."""
    machine.install(*LINUX_COMMANDS)
    templates = canopy_env.home / ".config" / "canopy" / "sandbox"
    templates.mkdir(parents=True)
    old = json.loads((canopy_sandbox.TEMPLATES / "worker.json").read_text())
    uv = str(canopy_env.home / ".cache" / "uv")
    every_roles = "~/.cache/canopy/sandbox/"
    old["filesystem"]["allowWrite"] = ["@TMPDIR@", "~/.cache/opencode", uv, every_roles, "~/.cache/canopy/sandbox/x"]
    (templates / "worker.json").write_text(json.dumps(old))

    report = sandbox.run_setup(SubprocessRunner(), "linux")

    [todo] = report.todo
    paths = f"~/.cache/opencode, {uv}, {every_roles}:"
    assert todo.startswith(f"{templates / 'worker.json'} lets a sandboxed run write {paths}")
    assert "add @CACHE@" in todo


def test_a_lockfile_that_changed_is_installed_again(machine: Machine, canopy_env: CanopyEnv) -> None:
    machine.install(*LINUX_COMMANDS)
    sandbox.run_setup(SubprocessRunner(), "linux")
    (runtime(canopy_env) / sandbox.INSTALLED_LOCK).write_text("{}")

    report = sandbox.run_setup(SubprocessRunner(), "linux")

    assert report.runtime.startswith("installed srt")
    assert len([c for c in machine.calls("npm") if c["argv"][1:2] == ["ci"]]) == 2


def test_an_install_that_failed_is_tried_again_though_its_lockfile_is_in_place(
    machine: Machine,
    canopy_env: CanopyEnv,
) -> None:
    """A new canopy's lockfile, copied in before npm ci failed, beside the srt an older canopy installed."""
    machine.install(*LINUX_COMMANDS)
    sandbox.run_setup(SubprocessRunner(), "linux")
    (runtime(canopy_env) / sandbox.INSTALLED_LOCK).write_text("{}")  # what an older canopy installed
    with mock.patch.dict(os.environ, {"FAKE_EXIT_NPM": "1"}):
        failed = sandbox.run_setup(SubprocessRunner(), "linux")
    assert (runtime(canopy_env) / "package-lock.json").is_file()
    assert (runtime(canopy_env) / "node_modules" / ".bin" / "srt").is_file()

    again = sandbox.run_setup(SubprocessRunner(), "linux")

    assert failed.todo[0].startswith("npm could not install srt")
    assert again.runtime.startswith("installed srt")
    assert len([c for c in machine.calls("npm") if c["argv"][1:2] == ["ci"]]) == 3


def test_what_is_missing_is_said_and_nothing_else_is_tried(machine: Machine, canopy_env: CanopyEnv) -> None:
    machine.install("bwrap", "canopy-sandbox")

    report = sandbox.run_setup(SubprocessRunner(), "linux")

    assert [t.split(". ")[0] for t in report.todo] == [
        f"npm is not on PATH, so srt {sandbox.pinned_version()} is not installed",
        "srt needs socat, ripgrep",
    ]
    assert "sudo apt-get install socat ripgrep" in report.todo[1]
    assert report.runtime == ""
    assert not runtime(canopy_env).exists()


def test_a_failed_npm_install_is_reported(machine: Machine) -> None:
    machine.install(*LINUX_COMMANDS)
    with mock.patch.dict(os.environ, {"FAKE_EXIT_NPM": "1", "FAKE_STDERR": "npm error 404 Not Found\n"}):
        report = sandbox.run_setup(SubprocessRunner(), "linux")

    [todo] = report.todo
    assert todo.startswith(f"npm could not install srt {sandbox.pinned_version()}")
    assert todo.endswith("npm error 404 Not Found")


@pytest.mark.parametrize(("restricted", "says"), [("1", "AppArmor restricts unprivileged ones"), ("0", "no userns")])
def test_bubblewrap_that_cannot_make_a_sandbox_says_why(
    machine: Machine,
    tmp_path: Path,
    restricted: str,
    says: str,
) -> None:
    machine.install(*LINUX_COMMANDS)
    setting = tmp_path / "apparmor_restrict_unprivileged_userns"
    setting.write_text(f"{restricted}\n")
    with (
        mock.patch.object(sandbox, "APPARMOR_USERNS", setting),
        mock.patch.dict(os.environ, {"FAKE_EXIT_BWRAP": "1", "FAKE_STDERR": "bwrap: no userns\n"}),
    ):
        report = sandbox.run_setup(SubprocessRunner(), "linux")

    [todo] = [t for t in report.todo if "bubblewrap" in t]
    assert says in todo
    assert ("sudo sysctl -w kernel.apparmor_restrict_unprivileged_userns=0" in todo) is (restricted == "1")


@pytest.mark.parametrize(
    ("says", "too_old"),
    [("bubblewrap 0.4.0\n", "0.4.0"), ("0.5\n", None), ("bubblewrap 0.9.0\n", None)],
)
def test_a_bubblewrap_older_than_srt_fully_supports_is_to_be_upgraded(
    machine: Machine,
    says: str,
    too_old: str | None,
) -> None:
    machine.install(*LINUX_COMMANDS)
    with mock.patch.dict(os.environ, {"FAKE_STDOUT_BWRAP": says}):
        report = sandbox.run_setup(SubprocessRunner(), "linux")

    if too_old is None:
        assert report.todo == []
        return
    [todo] = report.todo
    assert todo.startswith(f"bubblewrap {too_old} is older than 0.5.0, the oldest srt fully supports.")
    assert "Install\nbubblewrap 0.5.0 or later" in todo


def test_a_machine_srt_has_no_seccomp_filter_for_is_said(machine: Machine) -> None:
    machine.install(*LINUX_COMMANDS)
    machine.uname.return_value = uname("riscv64")

    report = sandbox.run_setup(SubprocessRunner(), "linux")

    [todo] = report.todo
    assert todo.startswith("srt has no seccomp filter for riscv64, only for x86_64 and aarch64.")
    assert "SSH agent" in todo


def test_a_kernel_without_ipv6_is_noted_and_left_to_the_wrapper(machine: Machine) -> None:
    machine.install(*LINUX_COMMANDS)
    machine.ipv6_missing.return_value = True

    report = sandbox.run_setup(SubprocessRunner(), "linux")

    assert report.notes == [sandbox.NO_IPV6]
    assert report.todo == []


def test_macos_needs_ripgrep_and_no_bubblewrap(machine: Machine) -> None:
    machine.install("npm", "canopy-sandbox")
    machine.uname.return_value = uname("arm64")  # macOS's name for it, which needs no seccomp filter
    machine.ipv6_missing.return_value = True  # srt runs no socat bridge there

    report = sandbox.run_setup(SubprocessRunner(), "darwin")

    assert report.todo == ["srt needs ripgrep: brew install ripgrep"]
    assert report.notes == []
    assert machine.calls("bwrap") == []


def test_root_and_an_install_without_the_wrapper_on_path_are_told_what_to_do(machine: Machine) -> None:
    machine.install("bwrap", "socat", "rg", "npm")
    machine.geteuid.return_value = 0

    report = sandbox.run_setup(SubprocessRunner(), "linux")

    assert report.todo == [mock.ANY, sandbox.WRAPPER_MISSING]
    assert report.todo[0].startswith("canopy is running as root")


@pytest.mark.skipif(not sys.platform.startswith("linux"), reason="the command checks the machine it runs on")
def test_the_command_prints_what_it_did_and_the_line_for_the_prefix(
    machine: Machine,
    capsys: pytest.CaptureFixture[str],
) -> None:
    machine.install(*LINUX_COMMANDS)

    assert main(["sandbox", "setup"]) == 0
    out = capsys.readouterr().out
    assert "wrote   " in out
    assert "installed srt" in out
    assert "To do" not in out
    assert "Note" not in out
    assert "worker_cmd_prefix = 'canopy-sandbox worker --read {definitions_dir} --'" in out

    machine.ipv6_missing.return_value = True
    assert main(["sandbox", "setup"]) == 0
    assert f"\nNote: {sandbox.NO_IPV6}\n" in capsys.readouterr().out

    (machine.bin / "rg").unlink()
    assert main(["sandbox", "setup"]) == 1
    assert "To do: srt needs ripgrep" in capsys.readouterr().out
