"""Workspaces (DESIGN §18, ROADMAP M6): the map, its config layer, pools under the root, and `--repo`."""

import json
import os
import sqlite3
from dataclasses import dataclass
from pathlib import Path

import pytest

from canopy.cli.main import main
from canopy.core import config, db, definitions, workspace
from canopy.infra import resources
from canopy.loop import attention
from canopy.setup import workspace as setup_workspace
from tests.canopy.helpers import InlineRunner, commit_and_push, wait_for_run, worker_does
from tests.conftest import CanopyEnv, git

LABEL = "agent-ready-tester"


def map_text(*repos: tuple[str, str], extra: str = "") -> str:
    tables = "".join(f'\n[repos.{name}]\nurl = "{url}"\nsummary = "The {name} repository."\n' for name, url in repos)
    return f"""\
[workspace]
name = "acme"
{tables}
[tracker]
provider = "github"
query = "is:issue is:open"
{extra}"""


@dataclass(frozen=True)
class Ws:
    """A workspace of two repositories, `api` and `web`, each cloned from a bare origin under tmp_path."""

    root: Path
    origins: dict[str, Path]
    state_dir: Path

    def journal(self) -> sqlite3.Connection:
        self.state_dir.mkdir(mode=0o700, exist_ok=True)  # as canopy creates it; anything wider is refused
        conn = db.connect(self.state_dir / "canopy.db")
        db.migrate(conn, resources.migrations_dir())
        return conn

    def clone(self, name: str) -> Path:
        return self.root / "repos" / name

    def remote_head(self, name: str, branch: str) -> str | None:
        out = git("for-each-ref", "--format=%(objectname)", f"refs/heads/{branch}", cwd=self.origins[name])
        return out or None


def bare_origin(path: Path, tmp_path: Path) -> Path:
    path.mkdir(parents=True)
    git("init", "--quiet", "--bare", "--initial-branch=main", cwd=path)
    seed = tmp_path / f"seed-{path.stem}"
    seed.mkdir()
    git("init", "--quiet", "--initial-branch=main", cwd=seed)
    git("commit", "--quiet", "--allow-empty", "-m", f"initial {path.stem}", cwd=seed)
    git("push", "--quiet", str(path), "main", cwd=seed)
    return path


@pytest.fixture
def ws(canopy_env: CanopyEnv, treehouse_state: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Ws:
    for var in ("GIT_AUTHOR_NAME", "GIT_COMMITTER_NAME"):
        monkeypatch.setenv(var, "canopy test")
    for var in ("GIT_AUTHOR_EMAIL", "GIT_COMMITTER_EMAIL"):
        monkeypatch.setenv(var, "test@example.test")
    monkeypatch.setenv("GIT_CONFIG_GLOBAL", os.devnull)
    monkeypatch.setenv("GIT_CONFIG_NOSYSTEM", "1")

    root = tmp_path / "acme"
    root.mkdir()
    origins = {name: bare_origin(tmp_path / "origins" / f"{name}.git", tmp_path) for name in ("api", "web")}
    for name, origin in origins.items():
        git("clone", "--quiet", str(origin), str(root / "repos" / name), cwd=tmp_path)
    (root / config.WORKSPACE_FILE_NAME).write_text(map_text(*((n, str(o)) for n, o in origins.items())))
    monkeypatch.chdir(root)
    return Ws(root, origins, root / ".canopy")


def seed_pools(ws: Ws, treehouse_state: Path) -> None:
    """Give each repository's pool one slot, a clone of its origin, where canopy's pinned layout puts it."""
    pools: dict[str, object] = {}
    for name, origin in ws.origins.items():
        slot = ws.root / ".treehouse" / f"{name}-fake" / "1" / name
        slot.parent.mkdir(parents=True)
        git("clone", "--quiet", str(origin), str(slot), cwd=ws.root)
        git("checkout", "--quiet", "--detach", cwd=slot)
        pools[str(ws.clone(name))] = {"slots": [{"name": "1", "path": str(slot), "status": "available"}]}
    treehouse_state.write_text(json.dumps({"pools": pools}))


def th(treehouse_state: Path) -> dict[str, list[object]]:
    state: dict[str, list[object]] = json.loads(treehouse_state.read_text())
    return state


def in_tick(conn: sqlite3.Connection, monkeypatch: pytest.MonkeyPatch, *, dry_run: bool = False) -> int:
    tick_id = db.start_tick(conn, dry_run=dry_run)
    monkeypatch.setenv("CANOPY_TICK_ID", str(tick_id))
    return tick_id


def decisions(conn: sqlite3.Connection, tick_id: int) -> list[tuple[str, str]]:
    return [(str(d["action"]), str(d["rationale"])) for d in db.decisions_for_tick(conn, tick_id)]


def dispatch(key: str, *args: str) -> list[str]:
    return ["dispatch", key, "--label", LABEL, "--kind", "implement", *args]


# The map and the config layer


def test_the_workspace_is_found_from_below_and_replaces_the_repository_file(
    ws: Ws, canopy_env: CanopyEnv, monkeypatch: pytest.MonkeyPatch
) -> None:
    (ws.clone("api") / "canopy.toml").write_text('[tracker]\nprovider = "jira"\nquery = "project = API"\n')
    deep = ws.clone("api") / "src"
    deep.mkdir()
    found = workspace.find(deep)
    assert found.root == ws.root
    assert (found.name, found.single, found.map_file) == ("acme", False, ws.root / config.WORKSPACE_FILE_NAME)
    assert [(r.name, r.path, r.summary, r.cloned) for r in found.repos] == [
        ("api", ws.clone("api"), "The api repository.", True),
        ("web", ws.clone("web"), "The web repository.", True),
    ]
    cfg = config.load(found.root, canopy_env.user_file)
    # The repositories' own canopy.toml files are not read inside a workspace: one tracker, one queue.
    assert (cfg.tracker.provider, cfg.tracker.query) == ("github", "is:issue is:open")
    # State is always under the workspace, whatever the user file's paths.state_dir says.
    assert cfg.paths.state_dir == ws.state_dir


def test_the_workspace_file_is_a_repository_file_for_scopes_and_policy(ws: Ws, canopy_env: CanopyEnv) -> None:
    ws_file = ws.root / config.WORKSPACE_FILE_NAME
    ws_file.write_text(map_text(extra="\n[capacity]\nmax_workers = 50\n"))
    with pytest.raises(config.ConfigError, match=r"canopy-workspace.toml: capacity.max_workers is user-only"):
        config.load(ws.root, canopy_env.user_file)
    ws_file.write_text(map_text(extra="\n[policy]\nmax_fix_ci_attempts = 9\nmax_resume_attempts = 1\n"))
    policy = config.load(ws.root, canopy_env.user_file).policy
    assert (policy.max_fix_ci_attempts, policy.max_resume_attempts) == (2, 1)  # only tightening applies


def load_both(root: Path, user_file: Path) -> None:
    """Read the map, then the config layers: what opening a command in the workspace does."""
    workspace.load(root)
    config.load(root, user_file)


@pytest.mark.parametrize(
    ("table", "error"),
    [
        ('[repos.API]\nurl = "https://x.test/a.git"\n', "repository name 'API'"),
        ('[repos.api]\nurl = "--upload-pack=touch x"\n', "repos.api.url"),
        ('[repos.api]\nurl = "https://x.test/a.git"\nsummary = "' + "x" * 201 + '"\n', "repos.api.summary"),
        ('[repos.api]\nurl = "https://x.test/a.git"\nowner = "me"\n', "repos.api.owner"),
        ("[desks]\nx = 1\n", "unknown key desks.x"),
    ],
)
def test_the_map_is_validated(ws: Ws, canopy_env: CanopyEnv, table: str, error: str) -> None:
    (ws.root / config.WORKSPACE_FILE_NAME).write_text(map_text() + "\n" + table)
    with pytest.raises(config.ConfigError, match=error):
        load_both(ws.root, canopy_env.user_file)


def test_a_repository_with_no_workspace_file_is_a_workspace_of_one(canopy_env: CanopyEnv) -> None:
    found = workspace.find(canopy_env.repo)
    assert (found.root, found.name, found.single, found.map_prose) == (canopy_env.repo, "repo", True, None)
    assert [r.path for r in found.repos] == [canopy_env.repo]
    assert workspace.one_name(Path("/x/2024_My.Repo")) == "my-repo"
    assert workspace.one_name(Path("/x/___")) == "repo"


def test_the_state_directory_must_be_private(ws: Ws, capsys: pytest.CaptureFixture[str]) -> None:
    ws.state_dir.mkdir(mode=0o755)
    ws.state_dir.chmod(0o755)  # as a checkout would create it
    assert main(["status"]) == 2
    assert "is not private to you" in capsys.readouterr().err
    ws.state_dir.rmdir()
    assert main(["status"]) == 0
    assert ws.state_dir.stat().st_mode & 0o777 == 0o700


def test_a_definitions_snapshot_canopy_did_not_make_is_refused(tmp_path: Path) -> None:
    planted = tmp_path / definitions.RUNTIME_DIR / definitions.digest()
    (planted / "agents").mkdir(parents=True)
    planted.chmod(0o755)
    with pytest.raises(definitions.DefinitionsError, match="not a snapshot canopy made"):
        definitions.ensure(tmp_path)
    planted.chmod(0o700)
    assert definitions.ensure(tmp_path) == planted


# The tick


def test_a_dry_run_tick_reads_every_pool_and_lists_repositories(
    ws: Ws, treehouse_state: Path, agent_log: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    (ws.root / config.WORKSPACE_FILE_NAME).write_text(
        map_text(("api", str(ws.origins["api"])), ("docs", "https://x.test/docs.git"), ("web", str(ws.origins["web"])))
    )
    (ws.root / "MAP.md").write_text("# map\n")
    monkeypatch.setenv(
        "FAKE_AGENT_COMMANDS",
        json.dumps([["canopy", *dispatch("PROJ-1", "--repo", "api")], ["canopy", *dispatch("PROJ-2")]]),
    )
    monkeypatch.setenv("FAKE_AGENT_RESULT", "tick complete")
    assert main(["tick", "--dry-run"]) == 0

    [run] = [json.loads(line) for line in agent_log.read_text().splitlines()]
    assert run["cwd"] == str(ws.root)
    prompt = run["argv"][3]
    state = json.loads(prompt.split("```json\n", 1)[1].split("\n```", 1)[0])
    assert state["workspace"] == {"name": "acme", "single_repository": False, "map": str(ws.root / "MAP.md")}
    assert [(r["name"], r["summary"], r["cloned"], r["leased_slots"]) for r in state["repositories"]] == [
        ("api", "The api repository.", True, []),
        ("docs", "The docs repository.", False, []),
        ("web", "The web repository.", True, []),
    ]
    # Each cloned repository's pool is read in its clone, with the pools kept under the workspace.
    pools = th(treehouse_state)
    assert pools["calls"] == [["status", "--json"], ["status", "--json"]]
    assert pools["contexts"] == [
        {"cwd": str(ws.clone("api")), "treehouse_root": str(ws.root)},
        {"cwd": str(ws.clone("web")), "treehouse_root": str(ws.root)},
    ]

    conn = ws.journal()
    assert decisions(conn, 1) == [
        (
            "attention:repo_missing",
            f"{ws.root / 'repos' / 'docs'} has no clone; run `canopy workspace sync` in {ws.root}",
        ),
        ("dispatch:implement", f"dry run: not dispatched; would work on agent/PROJ-1-work in api; label {LABEL}"),
        ("refused:unknown_repo", "--repo is required in a workspace: name the repository for PROJ-2 (api, docs, web)"),
    ]
    [item] = attention.current(conn)
    assert (item.ticket_key, item.reason, item.repo, item.subject) == (None, "repo_missing", "docs", "docs")
    assert "- docs, " in (ws.state_dir / "attention.md").read_text()


def test_items_about_two_repositories_are_two_items(
    ws: Ws, treehouse_state: Path, agent_log: Path, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    (ws.root / config.WORKSPACE_FILE_NAME).write_text(map_text(("a", "https://x.test/a"), ("b", "https://x.test/b")))
    notified = tmp_path / "notified.txt"
    user = Path(os.environ["XDG_CONFIG_HOME"]) / "canopy" / "config.toml"
    user.write_text(user.read_text() + f"\n[notify]\ncmd = 'sh -c \"cat >> {notified}\"'\n")
    monkeypatch.setenv("FAKE_AGENT_RESULT", "tick complete")
    assert main(["tick", "--dry-run"]) == 0
    assert [(i.subject, i.reason) for i in attention.current(ws.journal())] == [
        ("a", "repo_missing"),
        ("b", "repo_missing"),
    ]
    assert notified.read_text().startswith("canopy attention: 2 new, 0 resolved\n+ a repo_missing: ")

    git("clone", "--quiet", str(ws.origins["api"]), str(ws.root / "repos" / "a"), cwd=ws.root)
    assert main(["tick", "--dry-run"]) == 0
    assert "canopy attention: 0 new, 1 resolved\n- a repo_missing\n" in notified.read_text()


# Dispatch


def test_dispatch_names_one_repository_and_leases_from_its_pool(
    ws: Ws, treehouse_state: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    (ws.root / config.WORKSPACE_FILE_NAME).write_text(
        map_text(("api", str(ws.origins["api"])), ("docs", "https://x.test/docs.git"), ("web", str(ws.origins["web"])))
    )
    conn = ws.journal()
    tick_id = in_tick(conn, monkeypatch)
    runner = InlineRunner()
    assert main(dispatch("PROJ-1"), runner=runner) == 1
    assert main(dispatch("PROJ-1", "--repo", "nope"), runner=runner) == 1
    assert main(dispatch("PROJ-1", "--repo", "docs"), runner=runner) == 1
    assert main(dispatch("PROJ-1", "--repo", "Bad"), runner=runner) == 2  # not a name at all: a usage error
    assert main(dispatch("PROJ-1", "--repo", "api", "--slug", "login"), runner=runner) == 0
    assert "dispatch refused (unknown_repo)" in capsys.readouterr().err

    run = db.get_run(conn, 1)
    assert run is not None
    assert (run["repo"], run["branch"]) == ("api", "agent/PROJ-1-login")
    assert Path(run["slot_path"]) == ws.root / ".treehouse" / "api-fake" / "1" / "api"
    state = th(treehouse_state)
    assert state["calls"][-1] == [
        "get",
        "--lease",
        "--lease-holder",
        "canopy:PROJ-1",
        "--json",
        "--worktree-path",
        "{pool}/{slot}/{repo}",
    ]
    assert state["contexts"][-1] == {"cwd": str(ws.clone("api")), "treehouse_root": str(ws.root)}
    assert [a for a, _ in decisions(conn, tick_id)] == [
        "refused:unknown_repo",
        "refused:unknown_repo",
        "refused:unknown_repo",
        "dispatch:implement",
    ]
    assert decisions(conn, tick_id)[1][1] == "'nope' is not a repository in this workspace (api, docs, web)"
    assert decisions(conn, tick_id)[2][1].startswith("docs has no clone at ")
    assert decisions(conn, tick_id)[3][1] == f"run 1: agent/PROJ-1-login in api at {run['slot_path']}; label {LABEL}"

    # The ticket's work is in api now: another repository is refused until joint runs (D052).
    db.finish_run(conn, 1, "done", "{}")
    resume = ["dispatch", "PROJ-1", "--label", LABEL, "--kind", "resume", "--repo", "web"]
    assert main(resume, runner=runner) == 1
    assert decisions(conn, tick_id)[-1] == (
        "refused:unknown_repo",
        "PROJ-1 is worked in api; a ticket stays in the repository of its first dispatch (D052)",
    )
    assert main([*resume[:-1], "api"], runner=runner) == 0


def test_two_tickets_in_two_repositories_end_to_end(
    ws: Ws, treehouse_state: Path, agent_log: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    seed_pools(ws, treehouse_state)
    conn = ws.journal()
    in_tick(conn, monkeypatch)
    worker_does(monkeypatch, *commit_and_push("agent/PROJ-1-work"))
    assert main(dispatch("PROJ-1", "--repo", "api")) == 0
    first = wait_for_run(conn, 1)
    worker_does(monkeypatch, *commit_and_push("agent/PROJ-2-work"))
    assert main(dispatch("PROJ-2", "--repo", "web")) == 0
    second = wait_for_run(conn, 2)

    for run in (first, second):
        assert run["status"] == "done", Path(run["log_path"]).read_text()
        # Every worktree is under the workspace root.
        assert Path(run["slot_path"]).is_relative_to(ws.root / ".treehouse")
    assert (first["repo"], second["repo"]) == ("api", "web")
    assert ws.remote_head("api", "agent/PROJ-1-work") is not None
    assert ws.remote_head("web", "agent/PROJ-2-work") is not None
    assert ws.remote_head("web", "agent/PROJ-1-work") is None
    pools = json.loads(treehouse_state.read_text())["pools"]
    assert [s["status"] for p in pools.values() for s in p["slots"]] == ["available", "available"]
    workers = [json.loads(line) for line in agent_log.read_text().splitlines()]
    assert [w["cwd"] for w in workers] == [first["slot_path"], second["slot_path"]]


def test_reconcile_returns_leases_in_each_pool(
    ws: Ws, treehouse_state: Path, agent_log: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    seed_pools(ws, treehouse_state)
    runner = InlineRunner()
    conn = ws.journal()
    in_tick(conn, monkeypatch)
    assert main(dispatch("PROJ-1", "--repo", "api"), runner=runner) == 0
    # A lease in web's pool that no run holds, left by a dispatch that died between lease and journal.
    assert runner.run(
        ["treehouse", "get", "--lease", "--lease-holder", "canopy:PROJ-9", "--json"],
        cwd=ws.clone("web"),
        env={"TREEHOUSE_ROOT": str(ws.root)},
    ).ok
    conn.execute("UPDATE runs SET pid = 999999999")  # _run is gone
    monkeypatch.delenv("CANOPY_TICK_ID")
    monkeypatch.setenv("FAKE_AGENT_RESULT", "tick complete")
    assert main(["tick", "--dry-run"]) == 0

    run = db.get_run(conn, 1)
    assert run is not None
    assert run["status"] == "crashed"
    state = json.loads(treehouse_state.read_text())
    assert [s["status"] for p in state["pools"].values() for s in p["slots"]] == ["available", "available"]
    returns = [(c, x) for c, x in zip(state["calls"], state["contexts"], strict=True) if c[0] == "return"]
    assert [(c[-1], x["cwd"]) for c, x in returns] == [
        (run["slot_path"], str(ws.clone("api"))),
        (str(ws.root / ".treehouse" / "web-fake" / "1" / "web"), str(ws.clone("web"))),
    ]


# init --workspace and workspace sync


def test_init_workspace_writes_the_skeleton(
    canopy_env: CanopyEnv, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    root = tmp_path / "acme"
    root.mkdir()
    (root / ".gitignore").write_text("*.pyc")
    monkeypatch.chdir(root)
    assert main(["init", "--workspace", "--provider", "github"]) == 0
    out = capsys.readouterr().out
    assert f"wrote   {root / config.WORKSPACE_FILE_NAME}" in out
    assert f"updated {root / '.gitignore'}" in out
    assert "The map lists no repositories yet." in out
    assert (root / ".gitignore").read_text() == "*.pyc\n/repos/\n/.treehouse/\n/desks/\n/.canopy/\n"
    assert (root / "MAP.md").read_text().startswith("# Workspace map")
    found = workspace.load(root)
    assert (found.name, found.repos) == ("acme", ())
    assert config.load(root, canopy_env.user_file).tracker.provider == "github"

    # Inside a workspace, plain `canopy init` sets up the workspace, and nothing is overwritten.
    (root / config.WORKSPACE_FILE_NAME).write_text(map_text(("api", "https://x.test/api.git")))
    (root / "repos" / "api").mkdir(parents=True)
    monkeypatch.chdir(root / "repos" / "api")
    assert main(["init"]) == 0
    out = capsys.readouterr().out
    assert f"kept    {root / '.gitignore'}" in out
    assert "  - api\n" in out
    assert "x.test" not in out  # clone URLs are for `canopy workspace sync` alone
    assert not (root / "repos" / "api" / "canopy.toml").exists()


def test_sync_clones_missing_repositories_and_reports_a_different_origin(
    ws: Ws, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    extra = bare_origin(tmp_path / "origins" / "docs.git", tmp_path)
    (ws.root / config.WORKSPACE_FILE_NAME).write_text(
        map_text(("api", str(ws.origins["api"])), ("docs", str(extra)), ("web", "https://x.test/web.git"))
    )
    assert main(["workspace", "sync"]) == 0
    out = capsys.readouterr().out
    assert f"docs: cloning {extra} into {ws.clone('docs')}\ndocs: cloned\n" in out
    assert "api: present\n" in out
    assert f"web: present: origin is {ws.origins['web']}, but the map says https://x.test/web.git" in out
    assert git("log", "--format=%s", cwd=ws.clone("docs")) == "initial docs"

    (ws.root / config.WORKSPACE_FILE_NAME).write_text(map_text(("gone", str(tmp_path / "nowhere.git"))))
    assert main(["workspace", "sync"]) == 1
    assert "gone: failed: git clone exited 128" in capsys.readouterr().out


def test_sync_refuses_a_path_that_is_not_a_clone_and_never_prints_a_credential(
    ws: Ws, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    (ws.root / config.WORKSPACE_FILE_NAME).write_text(
        map_text(("docs", "https://someone:s3cret@x.invalid/docs.git"), ("notes", str(ws.origins["api"])))
    )
    (ws.root / "repos" / "notes").write_text("a file where the clone should be")
    assert main(["workspace", "sync"]) == 1
    out = capsys.readouterr().out
    assert "notes: failed: " in out
    assert "exists and is not a clone" in out
    assert "docs: cloning https://***@x.invalid/docs.git into " in out
    assert "docs: failed: git clone exited 128" in out
    assert "s3cret" not in out
    assert setup_workspace.shown("git@github.com:acme/api.git") == "git@github.com:acme/api.git"


def test_sync_outside_a_workspace_refuses(canopy_env: CanopyEnv, capsys: pytest.CaptureFixture[str]) -> None:
    assert main(["workspace", "sync"]) == 1
    assert "run `canopy init --workspace` first" in capsys.readouterr().err
