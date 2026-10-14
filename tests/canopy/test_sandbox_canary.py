"""The canary (HOST_ISOLATION §6): the shipped wrapper and policy templates hold under the real `srt`.

Opt-in with `CANOPY_SANDBOX_CANARY=1`, since it needs what `canopy sandbox setup` installs and checks: the pinned
`srt` (or one on PATH), bubblewrap, socat, and ripgrep on Linux, and unprivileged user namespaces. It needs to reach
github.com, the shipped template's first allowed host, and to run as the operator, not root (docs/SANDBOX.md). Opted
in, a missing piece fails the run instead of skipping it, so a CI job cannot pass without sandboxing anything.

Each attempt below is a plain shell command run through `canopy-sandbox worker`, in a linked worktree under the HOME the
template denies, as a treehouse slot is. The attempts on HOME and the state directory run as `setup` there too, and as
`chore` in a chore's default directory under the state directory. Every attempt must fail, and a write is checked on
the host, never by the attempt's exit status: under a denied directory, `srt`'s tmpfs takes the write and drops it when
the run ends. The positive controls must succeed, so a sandbox that refuses everything cannot pass.
"""

import contextlib
import os
import shutil
import socket  # noqa: TID251  (the host's side of the loopback the sandbox must not reach)
import sqlite3
import sys
import tempfile
import time
from collections.abc import Iterator
from dataclasses import dataclass
from pathlib import Path
from unittest import mock

import canopy_sandbox
import pytest
from hypothesis import HealthCheck, given, settings
from hypothesis import strategies as st

from canopy.cli.main import main
from canopy.core import db
from canopy.infra import procs
from canopy.infra.procs import SubprocessRunner
from tests.canopy.helpers import InlineRunner, in_tick, journal, pool, slot_of, worker_does
from tests.conftest import HERMETIC_GIT, CanopyEnv, GitPool, git, user_toml

pytestmark = pytest.mark.skipif(
    os.environ.get("CANOPY_SANDBOX_CANARY") != "1", reason="the sandbox canary runs with CANOPY_SANDBOX_CANARY=1"
)

WRAPPER = Path(sys.executable).parent / "canopy-sandbox"
ROLES = ("worker", "setup", "chore")
# Where `canopy sandbox setup` put srt for the operator running the tests, found before a fixture moves HOME.
PINNED_SRT = canopy_sandbox.runtime_dir() / "node_modules" / ".bin" / "srt"
# Found before a fixture puts tests/fakes, and its fake srt, first on PATH.
SRT = str(PINNED_SRT) if PINNED_SRT.is_file() else shutil.which("srt")
# A parent short enough on Linux and macOS alike for the sockets srt makes under the wrapper's run directory; on macOS
# /tmp is a link to /private/tmp. And the temp directory the operator's own canopy runs with, found before a fixture
# moves TMPDIR, which on macOS is a deep one per user.
SHORT_TMP = os.path.realpath("/tmp")  # noqa: S108  (the run directories under it are private to the user)
SYSTEM_TMP = tempfile.gettempdir()
PLANTED = "canary-planted-7f3a"
# On the shipped template's allowlist, and not; and the cloud metadata address, which no policy should reach.
ALLOWED_URL = "https://github.com"
DENIED_URL = "https://example.com"
METADATA_URL = "http://169.254.169.254/latest/meta-data/"
# The two ways out: through srt's proxy, even for the addresses srt's NO_PROXY names (loopback, link-local), and around
# it. srt's proxy refuses with a header no other proxy sends, which curl prints with the response's; around it, the
# sandbox has no route, so the name does not resolve or the connection fails. Anything else, a certificate error or
# another proxy's 403 say, is not the policy refusing and fails the test.
VIA_PROXY = "--noproxy '' -D -"
DIRECT = "--noproxy '*'"
ROUTES = [pytest.param(VIA_PROXY, id="through-the-proxy"), pytest.param(DIRECT, id="direct")]
SRT_REFUSAL = "X-Proxy-Error: blocked-by-allowlist"
CURL_NO_HOST, CURL_NO_CONNECTION = 6, 7
# What a sleeping process left behind by a timed-out run would show in its command line.
LINGERER = "987.654321"
TIMEOUT = 3.0
# What every sandboxed command prints first, so an attempt that fails because nothing ran fails the test instead.
RAN = "canary-ran"


@dataclass(frozen=True)
class Canary:
    """A HOME the template denies, holding a fake SSH key, the user config, a primary clone, and two of its slots."""

    home: Path
    state_dir: Path
    objects: Path
    primary: Path
    slot: Path
    other: Path
    runs_root: Path

    @property
    def common(self) -> Path:
        return self.primary / ".git"

    @property
    def own(self) -> Path:
        return self.common / "worktrees" / self.slot.name

    def run(
        self, script: str, *args: str, role: str = "worker", tmpdir: str | None = None, timeout: float | None = None
    ) -> procs.Result:
        """Run `sh -c script` in the slot as `role`, through the wrapper and srt, and check that it started.

        `tmpdir`, when given, is the TMPDIR the wrapper runs with, in place of the fixture's short one.
        """
        argv = [str(WRAPPER), role, "--", "sh", "-c", f"echo {RAN}\n{script}", "sh", *args]
        cwd = self.slot
        env: dict[str, str] = {"CANOPY_GIT_OBJECTS": str(self.objects)}
        if role == "chore":
            cwd = self.state_dir / "chores" / "canary"
            env = {}
            cwd.mkdir(parents=True, exist_ok=True)
        if tmpdir is not None:
            env["TMPDIR"] = tmpdir
        done = SubprocessRunner().run(argv, cwd=cwd, env=env, timeout=timeout)
        assert done.stdout.startswith(f"{RAN}\n"), done.stderr
        return done

    def shared(self) -> dict[str, bytes]:
        """Every file in the common git directory but the slot's own: what every slot, and the host's git, reads."""
        files = (p for p in self.common.rglob("*") if p.is_file() and not p.is_relative_to(self.own))
        return {str(p.relative_to(self.common)): p.read_bytes() for p in files}


@pytest.fixture
def sandbox_runtime(fakes_on_path: Path) -> Iterator[Path]:
    """The real srt on PATH, the operator's own user, and a temp directory of the test's for the wrapper's runs.

    Under /tmp, not tmp_path or the system temp directory, which on macOS is deep too: srt makes its Unix sockets in
    the run's temp directory, and a deep path is too long for one.
    """
    assert os.geteuid() != 0, "run the canary as yourself: under root, srt's sandbox keeps every capability"
    assert SRT is not None, "srt is not installed; run `canopy sandbox setup`"
    path = os.pathsep.join([str(Path(SRT).parent), os.environ["PATH"]])
    with (
        tempfile.TemporaryDirectory(prefix="canary.", dir=SHORT_TMP) as tmp,
        mock.patch.dict(os.environ, {"PATH": path, "TMPDIR": tmp, **HERMETIC_GIT}),
    ):
        yield Path(tmp)


@pytest.fixture
def canary(canopy_env: CanopyEnv, sandbox_runtime: Path, tmp_path: Path) -> Canary:
    """The shipped templates, unchanged, and a primary clone with two linked worktrees, all under HOME."""
    home = canopy_env.home
    templates = home / ".config" / "canopy" / "sandbox"
    templates.mkdir(parents=True)
    for role in ROLES:
        shutil.copy(canopy_sandbox.TEMPLATES / f"{role}.json", templates)
    (home / ".ssh").mkdir(mode=0o700)
    (home / ".ssh" / "id_ed25519").write_text(f"{PLANTED}\n")
    (home / ".bashrc").write_text("# the operator's\n")
    (canopy_env.state_dir / "secret").write_text(f"{PLANTED}\n")
    objects = canopy_env.state_dir / "runs" / "1.objects"
    objects.mkdir(parents=True)

    primary = home / "src" / "repo"
    primary.mkdir(parents=True)
    git("init", "--quiet", "--initial-branch=main", cwd=primary)
    (primary / "README").write_text("canary\n")
    git("add", "README", cwd=primary)
    git("commit", "--quiet", "-m", "initial", cwd=primary)
    git("branch", "other-branch", cwd=primary)
    pool = home / ".cache" / "treehouse" / "repo"
    slot, other = pool / "1", pool / "2"
    git("worktree", "add", "--quiet", "--detach", str(slot), cwd=primary)
    git("worktree", "add", "--quiet", str(other), "other-branch", cwd=primary)
    return Canary(
        home=home,
        state_dir=canopy_env.state_dir,
        objects=objects,
        primary=primary,
        slot=slot,
        other=other,
        runs_root=sandbox_runtime / f"canopy-sandbox-{os.getuid()}",
    )


@pytest.mark.parametrize(
    "script",
    [
        pytest.param('cat "$HOME/.ssh/id_ed25519"', id="ssh-key"),
        pytest.param('cat "$1/secret"', id="state-dir"),
        pytest.param(f'grep -r {PLANTED.removeprefix("canary-")} "$HOME" "$1"', id="search"),
    ],
)
@pytest.mark.parametrize("role", ROLES)
def test_a_run_cannot_read_home_or_the_state_dir(canary: Canary, script: str, role: str) -> None:
    done = canary.run(script, str(canary.state_dir), role=role)

    assert PLANTED not in done.stdout + done.stderr


@pytest.mark.parametrize(
    ("script", "target"),
    [
        pytest.param('echo pwned > "$HOME/canary"', "~/canary", id="home"),
        pytest.param('echo pwned >> "$HOME/.bashrc"', "~/.bashrc", id="bashrc"),
        pytest.param('echo pwned >> "$HOME/.config/canopy/config.toml"', "~/.config/canopy/config.toml", id="config"),
        pytest.param('echo pwned > "$1/planted"', "{state}/planted", id="state-dir"),
        pytest.param('echo pwned > "$1/runs/planted"', "{state}/runs/planted", id="state-runs"),
    ],
)
@pytest.mark.parametrize("role", ROLES)
def test_a_run_cannot_write_home_or_the_state_dir(canary: Canary, script: str, target: str, role: str) -> None:
    path = Path(target.replace("~", str(canary.home)).replace("{state}", str(canary.state_dir)))
    before = path.read_bytes() if path.exists() else None

    canary.run(script, str(canary.state_dir), role=role)

    assert (path.read_bytes() if path.exists() else None) == before


@pytest.mark.parametrize(
    "script",
    [
        pytest.param(
            "git commit --quiet --allow-empty -m x && git update-ref refs/heads/other-branch HEAD",
            id="another-slots-branch",
        ),
        pytest.param("git update-ref refs/heads/planted HEAD", id="a-new-ref"),
        pytest.param("git tag planted", id="a-tag"),
        pytest.param("git commit --quiet --allow-empty -m x && git update-ref refs/heads/main HEAD", id="main"),
        pytest.param("git -C ../2 commit --quiet --allow-empty -m x", id="commit-in-another-slot"),
        pytest.param("git -C ../2 checkout --quiet --detach", id="checkout-in-another-slot"),
        pytest.param("git pack-refs --all", id="pack-refs"),
        pytest.param("git gc --quiet --prune=now", id="gc"),
    ],
)
def test_a_worker_cannot_change_what_the_slots_share(canary: Canary, script: str) -> None:
    shared = canary.shared()

    canary.run(script)

    assert canary.shared() == shared


@pytest.mark.parametrize(
    ("script", "target"),
    [
        pytest.param("git config core.hooksPath /tmp", "{common}/config", id="config"),
        pytest.param('echo pwned >> "$1/config"', "{common}/config", id="config-directly"),
        pytest.param('printf "#!/bin/sh\\necho pwned\\n" > "$1/hooks/post-checkout"', "{common}/hooks/post-checkout"),
        pytest.param('echo "[core] hooksPath = /tmp" > "$2/config.worktree"', "{own}/config.worktree"),
        pytest.param('echo "gitdir: /tmp" > .git', "{slot}/.git", id="git-link"),
        pytest.param("echo pwned > ../2/planted", "{other}/planted", id="another-slots-files"),
        pytest.param('echo pwned > "$1/info/exclude"', "{common}/info/exclude", id="info-exclude"),
    ],
)
def test_a_worker_cannot_write_what_runs_on_the_host_or_in_another_slot(
    canary: Canary, script: str, target: str
) -> None:
    places = {"{common}": canary.common, "{own}": canary.own, "{slot}": canary.slot, "{other}": canary.other}
    for name, place in places.items():
        target = target.replace(name, str(place))
    path = Path(target)
    before = path.read_bytes() if path.exists() else None

    canary.run(script, str(canary.common), str(canary.own))

    assert (path.read_bytes() if path.exists() else None) == before


@pytest.mark.parametrize("route", ROUTES)
@pytest.mark.parametrize("url", [DENIED_URL, METADATA_URL], ids=["host-not-allowed", "metadata"])
def test_a_worker_cannot_reach_a_host_off_the_allowlist(canary: Canary, route: str, url: str) -> None:
    done = canary.run(f"curl -sS -m 10 -o /dev/null {route} {url}")

    assert refused(done, route), done.stderr


@pytest.mark.parametrize("route", ROUTES)
def test_a_worker_cannot_reach_the_hosts_loopback(canary: Canary, route: str) -> None:
    with listening() as server:
        port = server.getsockname()[1]

        done = canary.run(f"curl -sS -m 5 -o /dev/null {route} http://127.0.0.1:{port}/")

        assert refused(done, route), done.stderr
        with pytest.raises(BlockingIOError):
            server.accept()[0].close()


def test_a_worker_commits_in_its_slot(canary: Canary) -> None:
    """A positive control: the commit lands in the slot's own HEAD, and its objects in the run's object directory."""
    done = canary.run("echo work > work.txt && git add work.txt && git commit --quiet -m work")

    assert done.ok, done.stderr
    head = git("rev-parse", "HEAD", cwd=canary.slot)
    assert head != git("rev-parse", "main", cwd=canary.primary)
    assert not SubprocessRunner().run(["git", "cat-file", "-e", head], cwd=canary.primary).ok
    in_objects = {"GIT_OBJECT_DIRECTORY": str(canary.objects)}
    assert SubprocessRunner().run(["git", "cat-file", "-e", head], cwd=canary.slot, env=in_objects).ok
    assert list(canary.runs_root.iterdir()) == []


def test_a_worker_runs_under_the_system_temp_directory(canary: Canary) -> None:
    """A positive control: the wrapper's run directory, under the TMPDIR canopy runs with, leaves srt room for its
    sockets. The rest of the canary runs under a short one of its own, so that this is the only test that depends on it
    (HOST_ISOLATION §7, the temp directory on macOS)."""
    done = canary.run("true", tmpdir=SYSTEM_TMP)

    assert done.ok, done.stderr


def test_a_worker_reaches_an_allowed_host(canary: Canary) -> None:
    """A positive control: the allowlist lets through what it names."""
    done = canary.run(f"curl -sS -m 30 -o /dev/null {ALLOWED_URL}")

    assert done.ok, done.stderr


@settings(max_examples=25, deadline=None, suppress_health_check=[HealthCheck.function_scoped_fixture])
@given(prompt=st.text(st.characters(blacklist_categories=["Cs"], blacklist_characters="\x00")))
def test_a_worker_receives_its_prompt_byte_for_byte(canary: Canary, prompt: str) -> None:
    """Through the wrapper, srt, and the shell srt runs the command in (HOST_ISOLATION §5.3)."""
    out = canary.slot / "prompt.out"

    done = canary.run('printf %s "$1" > prompt.out', prompt)

    assert done.ok, done.stderr
    assert out.read_bytes() == os.fsencode(prompt)
    out.unlink()


def test_a_timed_out_run_leaves_no_process_behind(canary: Canary) -> None:
    """canopy kills a timed-out run's process group; what the sandbox started, in a session of its own too, ends."""
    # Not holding the run's output, so a process the sandbox lets outlive it fails the test instead of hanging it.
    script = f"setsid sleep {LINGERER} >/dev/null 2>&1 & sleep {LINGERER} >/dev/null 2>&1 & sleep {LINGERER}"

    done = canary.run(script, timeout=TIMEOUT)

    assert done.timed_out
    deadline = time.monotonic() + 10
    while lingering() and time.monotonic() < deadline:
        time.sleep(0.1)
    assert not lingering()


def test_canopys_sandboxed_worker_is_pushed(
    canopy_env: CanopyEnv,
    git_pool: GitPool,
    worktree_pool: tuple[Path, list[Path]],
    treehouse_state: Path,
    sandbox_runtime: Path,
) -> None:
    """`_run` with the wrapper as `worker_cmd`'s prefix, as docs/SANDBOX.md writes it, and the shipped template."""
    templates = canopy_env.home / ".config" / "canopy" / "sandbox"
    templates.mkdir(parents=True)
    shutil.copy(canopy_sandbox.TEMPLATES / "worker.json", templates)
    prefix = f"{WRAPPER} worker --read {{definitions_dir}} -- env"
    canopy_env.write_user(user_toml().replace("\nworker_cmd = 'env", f"\nworker_cmd = '{prefix}"))
    conn: sqlite3.Connection = journal(canopy_env)
    commit = ["git", "-c", "core.hooksPath=/dev/null", "commit", "--quiet", "--allow-empty", "-m", "PROJ-1: work"]
    with worker_does(commit):
        runner = InlineRunner()
        with in_tick(conn) as tick_id:
            args = ["dispatch", "PROJ-1", "--repo", "repo", "--label", "agent-ready-tester", "--kind", "implement"]
            assert main([*args, "--slug", "work"], runner=runner) == 0
            db.finish_tick(conn, tick_id, "ok", "test")
        run_id = int(conn.execute("SELECT max(id) FROM runs").fetchone()[0])
        assert main(["_run", str(run_id)], runner=runner) == 0

    run = db.get_run(conn, run_id)
    assert run is not None
    assert run["status"] == "done"
    pushed = git_pool.remote_head("agent/PROJ-1-work")
    assert pushed is not None
    primary, _ = worktree_pool
    assert not SubprocessRunner().run(["git", "cat-file", "-e", pushed], cwd=primary).ok
    slot = Path(slot_of(conn, run_id)["slot_path"])
    assert git("rev-parse", "HEAD", cwd=slot) == git_pool.remote_head("main")
    assert all(s["status"] == "available" for s in pool(treehouse_state))
    assert list((sandbox_runtime / f"canopy-sandbox-{os.getuid()}").iterdir()) == []


@contextlib.contextmanager
def listening() -> Iterator[socket.socket]:
    """A TCP server on the host's loopback that accepts nothing on its own, so a test can see whether one connected."""
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as server:
        server.bind(("127.0.0.1", 0))
        server.listen()
        server.setblocking(False)  # noqa: FBT003
        yield server


def refused(done: procs.Result, route: str) -> bool:
    """Whether curl was refused the way `route` refuses: by srt's proxy, or for want of a route."""
    if route == VIA_PROXY:
        return SRT_REFUSAL in done.stdout
    return done.returncode in {CURL_NO_HOST, CURL_NO_CONNECTION}


def lingering() -> bool:
    return SubprocessRunner().run(["pgrep", "-f", LINGERER.replace(".", "[.]")]).ok
