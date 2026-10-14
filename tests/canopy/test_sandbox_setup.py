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
from tests.conftest import CanopyEnv

# Records its arguments and working directory, then exits with $FAKE_EXIT_<NAME>, or 0.
STUB = """\
#!{python}
import json, os, sys
from pathlib import Path
name = Path(sys.argv[0]).name
with open({log!r}, "a") as f:
    f.write(json.dumps({{"argv": [name, *sys.argv[1:]], "cwd": os.getcwd()}}) + "\\n")
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
    """The stubs' directory, which is all of PATH, the log of what they were run with, and the user's id."""

    bin: Path
    log: Path
    geteuid: mock.MagicMock

    def install(self, *names: str) -> None:
        for name in names:
            path = self.bin / name
            path.write_text((NPM if name == "npm" else STUB).format(python=sys.executable, log=str(self.log)))
            path.chmod(0o755)

    def calls(self, name: str) -> list[Call]:
        if not self.log.exists():
            return []
        calls: list[Call] = [json.loads(line) for line in self.log.read_text().splitlines()]
        return [c for c in calls if c["argv"][0] == name]


@pytest.fixture
def machine(canopy_env: CanopyEnv, tmp_path: Path) -> Iterator[Machine]:
    """A machine with nothing installed, run by a user who is not root, with HOME in `canopy_env`."""
    assert canopy_env.home.is_dir()
    (tmp_path / "bin").mkdir()
    with (
        mock.patch.dict(os.environ, {"PATH": str(tmp_path / "bin")}),
        mock.patch.object(os, "geteuid", autospec=True, return_value=1000) as geteuid,
    ):
        yield Machine(tmp_path / "bin", tmp_path / "calls.jsonl", geteuid)


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


def test_a_lockfile_that_changed_is_installed_again(machine: Machine, canopy_env: CanopyEnv) -> None:
    machine.install(*LINUX_COMMANDS)
    sandbox.run_setup(SubprocessRunner(), "linux")
    (runtime(canopy_env) / sandbox.INSTALLED_LOCK).write_text("{}")

    report = sandbox.run_setup(SubprocessRunner(), "linux")

    assert report.runtime.startswith("installed srt")
    assert len([c for c in machine.calls("npm") if c["argv"][1:2] == ["ci"]]) == 2


def test_an_install_that_failed_is_tried_again_though_its_lockfile_is_in_place(
    machine: Machine, canopy_env: CanopyEnv
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
    machine: Machine, tmp_path: Path, restricted: str, says: str
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


def test_macos_needs_ripgrep_and_no_bubblewrap(machine: Machine) -> None:
    machine.install("npm", "canopy-sandbox")

    report = sandbox.run_setup(SubprocessRunner(), "darwin")

    assert report.todo == ["srt needs ripgrep: brew install ripgrep"]
    assert machine.calls("bwrap") == []


def test_root_and_a_release_without_the_wrapper_on_path_are_told_what_to_do(machine: Machine) -> None:
    machine.install("bwrap", "socat", "rg", "npm")
    machine.geteuid.return_value = 0

    report = sandbox.run_setup(SubprocessRunner(), "linux")

    assert report.todo == [mock.ANY, sandbox.RELEASE_LAUNCHER]
    assert report.todo[0].startswith("canopy is running as root")


@pytest.mark.skipif(not sys.platform.startswith("linux"), reason="the command checks the machine it runs on")
def test_the_command_prints_what_it_did_and_the_line_for_worker_cmd(
    machine: Machine, capsys: pytest.CaptureFixture[str]
) -> None:
    machine.install(*LINUX_COMMANDS)

    assert main(["sandbox", "setup"]) == 0
    out = capsys.readouterr().out
    assert "wrote   " in out
    assert "installed srt" in out
    assert "To do" not in out
    assert "worker_cmd = '''canopy-sandbox worker --read {definitions_dir} --" in out

    (machine.bin / "rg").unlink()
    assert main(["sandbox", "setup"]) == 1
    assert "To do: srt needs ripgrep" in capsys.readouterr().out
