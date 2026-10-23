"""Workspaces (DESIGN §18, ROADMAP M6): the map, its config layer, pools under the root, and `--repo`."""

import contextlib
import json
from pathlib import Path

import pytest

from canopy.cli.main import main
from canopy.core import config, db, definitions, workspace
from canopy.core.vocab import ResumeReason, RunKind
from canopy.loop import attention
from canopy.setup import workspace as setup_workspace
from tests.canopy.conftest import Ws, bare_origin, map_text, th, turn_off_auto_maintenance
from tests.canopy.helpers import (
    LABEL,
    InlineRunner,
    agent_runs,
    canopy,
    decisions,
    present,
    waits,
)
from tests.canopy.scenario_helpers import Scenario, dispatches, pushes
from tests.conftest import CanopyEnv, git


def dispatch(key: str, *args: str) -> list[str]:
    return ["dispatch", key, "--label", LABEL, "--kind", "implement", *args]


def with_docs(ws: Ws) -> None:
    """Map a third repository, `docs`, between api and web, with no clone."""
    (ws.root / config.WORKSPACE_FILE_NAME).write_text(
        map_text(("api", str(ws.origins["api"])), ("docs", "https://x.test/docs.git"), ("web", str(ws.origins["web"]))),
    )


# The map and the config layer


def test_the_workspace_is_found_from_below_and_its_repositories_files_are_not_read(
    ws: Ws,
    canopy_env: CanopyEnv,
) -> None:
    (ws.clone("api") / "canopy.toml").write_text('[tracker]\nprovider = "jira"\nquery = "project = API"\n')
    deep = ws.clone("api") / "src"
    deep.mkdir()
    found = workspace.find(deep)
    assert found.root == ws.root
    assert (found.name, found.map_file) == ("acme", ws.root / config.WORKSPACE_FILE_NAME)
    assert [(r.name, r.path, r.summary, r.cloned) for r in found.repos] == [
        ("api", ws.clone("api"), "The api repository.", True),
        ("web", ws.clone("web"), "The web repository.", True),
    ]
    cfg = config.load(found.root, canopy_env.user_file)
    # The repositories' own canopy.toml files are not read inside a workspace: one tracker, one queue.
    assert (cfg.tracker.provider, cfg.tracker.query) == ("github", "is:issue is:open")
    # Each workspace keeps its own state.
    assert found.state_dir == ws.state_dir


def test_the_workspace_file_is_a_repository_file_for_scopes_and_policy(ws: Ws, canopy_env: CanopyEnv) -> None:
    ws_file = ws.root / config.WORKSPACE_FILE_NAME
    ws_file.write_text(map_text(extra="\n[capacity]\nmax_workers = 50\n"))
    with pytest.raises(config.ConfigError, match=r"canopy-workspace.toml: capacity.max_workers is private"):
        config.load(ws.root, canopy_env.user_file)
    ws_file.write_text(map_text(extra="\n[policy]\nci_cooldown_minutes = 9\nmax_resume_attempts = 1\n"))
    policy = config.load(ws.root, canopy_env.user_file).policy
    assert (policy.ci_cooldown_minutes, policy.max_resume_attempts) == (30, 1)  # only tightening applies


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
        (
            '[repos.api]\nurl = "https://x.test/a.git"\nbranch_url = "https://x.test/a/tree/main"\n',
            "repos.api.branch_url",
        ),
        ('[repos.api]\nurl = "https://x.test/a.git"\nbranch_url = "http://x.test/a/tree/{branch}"\n', "plain https://"),
        ('[repos.api]\nurl = "https://x.test/a.git"\nbranch_url = "https://x.test/{repo}/tree/{branch}"\n', "braces"),
        ('[repos.api]\nurl = "https://x.test/a.git"\nhuman_checks = [""]\n', "repos.api.human_checks"),
        ("[desks]\nx = 1\n", "unknown key desks.x"),
    ],
)
def test_the_map_is_validated(ws: Ws, canopy_env: CanopyEnv, table: str, error: str) -> None:
    (ws.root / config.WORKSPACE_FILE_NAME).write_text(map_text() + "\n" + table)
    with pytest.raises(config.ConfigError, match=error):
        load_both(ws.root, canopy_env.user_file)


def test_a_repositorys_branch_url_comes_from_its_github_url_unless_the_map_sets_one(ws: Ws) -> None:
    template = "https://git.example/api/-/tree/{branch}"
    (ws.root / config.WORKSPACE_FILE_NAME).write_text(
        map_text(("web", "git@github.com:acme/web.git"), ("docs", "https://github.com/acme/docs"))
        + f'\n[repos.api]\nurl = "https://github.com/acme/api.git"\nbranch_url = "{template}"\n'
        + '\n[repos.ops]\nurl = "https://github.com/acme/ops.git"\nbranch_url = ""\n',
    )
    assert [(r.name, r.branch_url) for r in workspace.load(ws.root).repos] == [
        ("api", template),
        ("docs", "https://github.com/acme/docs/tree/{branch}"),
        # Empty turns the link off, even for a GitHub URL.
        ("ops", ""),
        ("web", "https://github.com/acme/web/tree/{branch}"),
    ]


@pytest.mark.parametrize(
    ("url", "expected"),
    [
        ("https://github.com/acme/api", "https://github.com/acme/api/tree/{branch}"),
        ("https://github.com/acme/api.git", "https://github.com/acme/api/tree/{branch}"),
        ("https://github.com/acme/api/", "https://github.com/acme/api/tree/{branch}"),
        ("https://GitHub.com/acme/my.repo.git", "https://github.com/acme/my.repo/tree/{branch}"),
        # A credential in the clone URL never reaches the link.
        ("https://x-access-token:secret@github.com/acme/api.git", "https://github.com/acme/api/tree/{branch}"),
        ("git@github.com:acme/api.git", "https://github.com/acme/api/tree/{branch}"),
        ("ssh://git@github.com/acme/api.git", "https://github.com/acme/api/tree/{branch}"),
        ("http://github.com/acme/api.git", ""),
        ("https://github.example.com/acme/api.git", ""),
        ("https://gitlab.com/acme/api.git", ""),
        ("https://github.com/acme/api/tree/main", ""),
        ("https://github.com/acme/..", ""),
        ("/srv/git/api.git", ""),
    ],
)
def test_only_a_github_clone_url_implies_a_branch_url(url: str, expected: str) -> None:
    assert workspace.github_branch_url(url) == expected


def test_canopy_runs_only_in_a_workspace_and_reads_no_repository_file(tmp_path: Path) -> None:
    """D016: a code repository is never a workspace, and a `canopy.toml` left in one is named, not read."""
    checkout = tmp_path / "code"
    (checkout / ".git").mkdir(parents=True)
    with pytest.raises(config.ConfigError, match=r"no canopy-workspace\.toml here or above") as e:
        workspace.find(checkout)
    assert "is not read" not in str(e.value)
    (checkout / "canopy.toml").write_text('[tracker]\nprovider = "jira"\n')
    (checkout / "src").mkdir()
    with pytest.raises(config.ConfigError, match=r"canopy\.toml is not read: move its keys"):
        workspace.find(checkout / "src")


def test_a_workspace_without_a_name_is_named_after_its_directory() -> None:
    assert workspace.default_name(Path("/x/2024_My.Repo")) == "my-repo"
    assert workspace.default_name(Path("/x/___")) == "workspace"


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
    ws_scenario: Scenario,
    ws: Ws,
    treehouse_state: Path,
    agent_log: Path,
) -> None:
    with_docs(ws)
    (ws.root / "MAP.md").write_text("# map\n")
    ticked = ws_scenario.tick(dispatches(repo="api"), canopy(*dispatch("PROJ-2")), dry_run=True)

    [run] = agent_runs(agent_log)
    assert run["cwd"] == str(ws.root)
    state = ws_scenario.state()
    assert state["workspace"] == {"name": "acme", "map": str(ws.root / "MAP.md")}
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

    conn = ws_scenario.conn
    assert decisions(conn, ticked.tick.id) == [
        (
            "attention:repo_missing",
            f"{ws.root / 'repos' / 'docs'} has no clone; run `canopy workspace sync` in {ws.root}",
        ),
        ("queried", "the query returned no open ticket"),
        ("dispatch:implement", f"dry run: not dispatched; would work on agent/PROJ-1-work in api; label {LABEL}"),
        (
            "refused:unknown_repo",
            "repos is required (--repo): name the repositories for PROJ-2 (api, docs, web)",
        ),
    ]
    [item] = attention.current(conn)
    assert (item.ticket_key, item.reason, item.repo, item.subject) == (None, "repo_missing", "docs", "docs")
    assert "- docs, " in (ws.state_dir / "attention.md").read_text()


def test_items_about_two_repositories_are_two_items(ws_scenario: Scenario, ws: Ws, tmp_path: Path) -> None:
    (ws.root / config.WORKSPACE_FILE_NAME).write_text(map_text(("a", "https://x.test/a"), ("b", "https://x.test/b")))
    notified = tmp_path / "notified.txt"
    ws_scenario.configures(notify={"cmd": f'sh -c "cat >> {notified}"'})
    ws_scenario.tick(dry_run=True)
    assert [(i.subject, i.reason) for i in attention.current(ws_scenario.conn)] == [
        ("a", "repo_missing"),
        ("b", "repo_missing"),
    ]
    assert notified.read_text().startswith("canopy attention: 2 new, 0 resolved\n+ a repo_missing: ")

    git("clone", "--quiet", str(ws.origins["api"]), str(ws.root / "repos" / "a"), cwd=ws.root)
    turn_off_auto_maintenance(ws.root / "repos" / "a")
    ws_scenario.tick(dry_run=True)
    assert "canopy attention: 0 new, 1 resolved\n- a repo_missing\n" in notified.read_text()


# Dispatch


def test_dispatch_names_one_repository_and_leases_from_its_pool(
    ws_scenario: Scenario,
    ws: Ws,
    treehouse_state: Path,
) -> None:
    with_docs(ws)
    conn = ws_scenario.conn
    assert ws_scenario.refuses(canopy(*dispatch("PROJ-1"))) == [
        ("refused:unknown_repo", "repos is required (--repo): name the repositories for PROJ-1 (api, docs, web)"),
    ]
    assert ws_scenario.refuses(dispatches(repo="nope")) == [
        ("refused:unknown_repo", "'nope' is not a repository in this workspace (api, docs, web)"),
    ]
    no_clone = ws_scenario.refuses(dispatches(repo="docs"))
    [(action, rationale)] = no_clone
    assert action == "refused:unknown_repo"
    assert rationale.startswith("docs has no clone at ")
    assert "dispatch refused (unknown_repo)" in no_clone.printed.err
    ws_scenario.overseer(*dispatch("PROJ-1", "--repo", "Bad"), code=2)  # not a name at all: a usage error

    run = ws_scenario.run(dispatches(repo="api", slug="login"), worker=pushes("agent/PROJ-1-login"))
    [slot] = db.run_slots(conn, run.id)
    assert (slot.repo, run.branch) == ("api", "agent/PROJ-1-login")
    assert Path(slot.slot_path) == ws.root / ".treehouse" / "api-fake" / "1" / "api"
    state = json.loads(treehouse_state.read_text())
    [(lease, where)] = [(c, x) for c, x in zip(state["calls"], state["contexts"], strict=True) if c[0] == "get"]
    assert lease == [
        "get",
        "--lease",
        "--lease-holder",
        "canopy:PROJ-1",
        "--json",
        "--worktree-path",
        "{pool}/{slot}/{repo}",
    ]
    assert where == {"cwd": str(ws.clone("api")), "treehouse_root": str(ws.root)}
    assert decisions(conn, int(run.row["tick_id"])) == [
        ("dispatch:implement", f"run {run.id}: agent/PROJ-1-login in api at {slot.slot_path}; label {LABEL}"),
    ]

    # The ticket has a unit in api only: resuming it in web has no branch to continue there (DESIGN §18).
    def resume(repo: str) -> list[str]:
        return dispatches(kind=RunKind.RESUME, reasons=[ResumeReason.CI], repo=repo)

    assert ws_scenario.refuses(resume("web")) == [
        (
            "refused:no_branch",
            "PROJ-1 has no branch in web for resume to continue; dispatch implement with repos web (--repo web)",
        ),
    ]
    assert ws_scenario.run(resume("api"), worker=pushes("agent/PROJ-1-login")).status == "done"


def test_two_tickets_in_two_repositories_end_to_end(
    ws_scenario: Scenario,
    ws: Ws,
    treehouse_state: Path,
    agent_log: Path,
) -> None:
    conn = ws_scenario.conn
    # Each ticket's worker pushes its own branch, in the repository its run was dispatched to.
    ticked = ws_scenario.tick(dispatches("PROJ-1", repo="api"), dispatches("PROJ-2", repo="web"), worker=pushes())

    slots = [db.run_slots(conn, run.id)[0] for run in ticked.runs]
    for run, slot in zip(ticked.runs, slots, strict=True):
        assert run.status == "done", Path(run.row["log_path"]).read_text()
        # Every worktree is under the workspace root.
        assert Path(slot.slot_path).is_relative_to(ws.root / ".treehouse")
    assert [s.repo for s in slots] == ["api", "web"]
    assert ws.remote_head("api", "agent/PROJ-1-work") is not None
    assert ws.remote_head("web", "agent/PROJ-2-work") is not None
    assert ws.remote_head("web", "agent/PROJ-1-work") is None
    pools = json.loads(treehouse_state.read_text())["pools"]
    assert [s["status"] for p in pools.values() for s in p["slots"]] == ["available", "available"]
    # The tick's overseer ran first, in the workspace root; each worker in its run's slot, though the order the two
    # workers started in is theirs.
    workers = [w for w in agent_runs(agent_log) if w["argv"][:3] == ["run", "--agent", "canopy-worker"]]
    assert sorted(w["cwd"] for w in workers) == sorted(s.slot_path for s in slots)


def test_reconcile_returns_leases_in_each_pool(ws_scenario: Scenario, ws: Ws, treehouse_state: Path) -> None:
    conn = ws_scenario.conn
    working = ws_scenario.starts(dispatches(repo="api"))
    # A lease in web's pool that no run holds, left by a dispatch that died between lease and journal.
    assert (
        InlineRunner()
        .run(
            ["treehouse", "get", "--lease", "--lease-holder", "canopy:PROJ-9", "--json"],
            cwd=ws.clone("web"),
            env={"TREEHOUSE_ROOT": str(ws.root)},
        )
        .ok
    )
    working.dies()  # _run is gone
    ws_scenario.tick(*waits("PROJ-1", rationale="its run crashed"), dry_run=True)

    run = present(db.get_run(conn, working.id))
    assert run["status"] == "crashed"
    state = json.loads(treehouse_state.read_text())
    assert [s["status"] for p in state["pools"].values() for s in p["slots"]] == ["available", "available"]
    returns = [(c, x) for c, x in zip(state["calls"], state["contexts"], strict=True) if c[0] == "return"]
    assert [(c[-1], x["cwd"]) for c, x in returns] == [
        (db.run_slots(conn, 1)[0].slot_path, str(ws.clone("api"))),
        (str(ws.root / ".treehouse" / "web-fake" / "1" / "web"), str(ws.clone("web"))),
    ]


# init --workspace and workspace sync


def test_init_workspace_writes_the_skeleton(
    canopy_env: CanopyEnv,
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    root = tmp_path / "acme"
    root.mkdir()
    (root / ".gitignore").write_text("*.pyc")
    with contextlib.chdir(root):
        assert main(["init", "--workspace", "--provider", "github"]) == 0
        out = capsys.readouterr().out
        assert f"wrote   {root / config.WORKSPACE_FILE_NAME}" in out
        assert f"updated {root / '.gitignore'}" in out
        assert "The map lists no repositories yet." in out
        assert (root / ".gitignore").read_text() == "*.pyc\n/repos/\n/.treehouse/\n/pools/\n/desks/\n/.canopy/\n"
        assert (root / "MAP.md").read_text().startswith("# Workspace map")
        found = workspace.load(root)
        assert (found.name, found.repos) == ("acme", ())
        assert config.load(root, canopy_env.user_file).tracker.provider == "github"
        # Defaults are not written, so a later canopy's reach the workspace.
        assert "[trust]" not in (root / config.WORKSPACE_FILE_NAME).read_text()

    # Inside a workspace, plain `canopy init` sets up the workspace, and nothing is overwritten.
    (root / config.WORKSPACE_FILE_NAME).write_text(map_text(("api", "https://x.test/api.git")))
    (root / "repos" / "api").mkdir(parents=True)
    with contextlib.chdir(root / "repos" / "api"):
        assert main(["init"]) == 0
        out = capsys.readouterr().out
        assert f"kept    {root / '.gitignore'}" in out
        assert "  - api\n" in out
        assert "x.test" not in out  # clone URLs are for `canopy workspace sync` alone
        assert not (root / "repos" / "api" / "canopy.toml").exists()


def test_sync_clones_missing_repositories_and_reports_a_different_origin(
    ws: Ws,
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    extra = bare_origin(tmp_path / "origins" / "docs.git", tmp_path)
    (ws.root / config.WORKSPACE_FILE_NAME).write_text(
        map_text(("api", str(ws.origins["api"])), ("docs", str(extra)), ("web", "https://x.test/web.git")),
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


def test_sync_turns_off_gits_automatic_maintenance_in_every_clone_but_not_in_a_dry_run(ws: Ws, tmp_path: Path) -> None:
    extra = bare_origin(tmp_path / "origins" / "docs.git", tmp_path)
    (ws.root / config.WORKSPACE_FILE_NAME).write_text(map_text(("api", str(ws.origins["api"])), ("docs", str(extra))))
    off = {"maintenance.auto=false", "gc.auto=0"}
    unset_auto_maintenance(ws.clone("api"))

    def local_config(name: str) -> set[str]:
        return set(git("config", "--local", "--list", cwd=ws.clone(name)).splitlines())

    assert main(["workspace", "sync", "--dry-run"]) == 0
    assert not off & local_config("api")
    assert main(["workspace", "sync"]) == 0
    assert off <= local_config("api")  # a clone from before
    assert off <= local_config("docs")  # and one sync made


def test_a_tick_says_where_a_clone_leaves_gits_automatic_maintenance_on_until_sync_turns_it_off(
    ws_scenario: Scenario,
    ws: Ws,
) -> None:
    unset_auto_maintenance(ws.clone("api"))
    git("config", "--local", "--unset", "gc.auto", cwd=ws.clone("web"))
    ticked = ws_scenario.tick(dry_run=True)

    found = [d for d in decisions(ws_scenario.conn, ticked.tick.id) if d[0] == f"attention:{attention.MAINTENANCE_ON}"]
    fix = f"and can prune what running slots use; run `canopy workspace sync` in {ws.root}"
    assert found == [
        (
            f"attention:{attention.MAINTENANCE_ON}",
            f"git's automatic maintenance is on in {ws.clone('api')} (maintenance.auto, gc.auto not set), {fix}",
        ),
        (
            f"attention:{attention.MAINTENANCE_ON}",
            f"git's automatic maintenance is on in {ws.clone('web')} (gc.auto not set), {fix}",
        ),
    ]
    assert [i.subject for i in attention.current(ws_scenario.conn) if i.reason == attention.MAINTENANCE_ON] == [
        "api",
        "web",
    ]

    assert main(["workspace", "sync"]) == 0
    ws_scenario.tick(dry_run=True)
    assert not [i for i in attention.current(ws_scenario.conn) if i.reason == attention.MAINTENANCE_ON]


def unset_auto_maintenance(clone: Path) -> None:
    """Take out of `clone`'s config what sync sets there, as in a clone from before sync set it."""
    for key in ("maintenance.auto", "gc.auto"):
        git("config", "--local", "--unset", key, cwd=clone)


def test_sync_refuses_a_path_that_is_not_a_clone_and_never_prints_a_credential(
    ws: Ws,
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    (ws.root / config.WORKSPACE_FILE_NAME).write_text(
        map_text(("docs", "https://someone:s3cret@x.invalid/docs.git"), ("notes", str(ws.origins["api"]))),
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


def test_sync_outside_a_workspace_refuses(
    canopy_env: CanopyEnv,
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    elsewhere = tmp_path / "elsewhere"
    elsewhere.mkdir()
    with contextlib.chdir(elsewhere):
        assert main(["workspace", "sync"]) == 1
        assert "run `canopy init` first" in capsys.readouterr().err
