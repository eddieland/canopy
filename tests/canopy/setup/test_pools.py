"""Declared repositories and slots (DESIGN §18, ROADMAP M17): `capacity` sizes the pools, sync converges."""

import contextlib
import json
import os
import threading
from collections.abc import Mapping
from pathlib import Path
from typing import Any
from unittest import mock

import pytest

from canopy.cli.main import main
from canopy.core import config, workspace
from canopy.infra import lock
from canopy.setup import workspace as setup_workspace
from tests.canopy.conftest import Ws, bare_origin, map_text, seed_pools
from tests.canopy.helpers import LABEL, InlineRunner, in_tick
from tests.conftest import CanopyEnv, git, user_toml

GIT_AUTHORS = ("GIT_AUTHOR_NAME", "GIT_COMMITTER_NAME", "GIT_AUTHOR_EMAIL", "GIT_COMMITTER_EMAIL")


def declare(canopy_env: CanopyEnv, capacity: str) -> None:
    """Add `capacity` lines to the operator's user file."""
    canopy_env.write_user(user_toml() + f"\n[capacity]\n{capacity}\n")


def fake_state(treehouse_state: Path) -> dict[str, Any]:
    state: dict[str, Any] = json.loads(treehouse_state.read_text())
    return state


def pool_of(state: Mapping[str, Any], ws: Ws, name: str) -> dict[str, Any]:
    pool: dict[str, Any] = state["pools"][str(ws.clone(name))]
    return pool


def slots_of(treehouse_state: Path, ws: Ws, name: str) -> list[dict[str, str]]:
    slots: list[dict[str, str]] = pool_of(fake_state(treehouse_state), ws, name)["slots"]
    return slots


def set_slots(treehouse_state: Path, ws: Ws, name: str, *statuses: str, **extra: object) -> list[str]:
    """Give repository `name`'s pool one slot per status, named 1, 2, ..., each a directory. Returns their paths."""
    state: dict[str, Any] = fake_state(treehouse_state) if treehouse_state.exists() else {}
    paths: list[str] = []
    slots: list[dict[str, str]] = []
    for i, status in enumerate(statuses, 1):
        path = ws.root / ".treehouse" / f"{name}-fake" / str(i) / name
        path.mkdir(parents=True, exist_ok=True)
        slot = {"name": str(i), "path": str(path), "status": status}
        if status == "leased":
            slot |= {"lease_id": f"id-{i}", "lease_holder": "canopy:PROJ-9", "leased_at": "2026-10-07T00:00:00Z"}
        slots.append(slot)
        paths.append(str(path))
    state.setdefault("pools", {})[str(ws.clone(name))] = {"slots": slots}
    state.update(extra)
    treehouse_state.write_text(json.dumps(state))
    return paths


def calls(treehouse_state: Path) -> list[list[str]]:
    found: list[list[str]] = fake_state(treehouse_state).get("calls", [])
    return found


def dispatch(*repos: str) -> list[str]:
    return ["dispatch", "PROJ-1", "--label", LABEL, "--kind", "implement", *(a for r in repos for a in ("--repo", r))]


# The declaration


def test_slots_are_declared_in_the_user_file_only(ws: Ws, canopy_env: CanopyEnv) -> None:
    declare(canopy_env, "slots_per_repo = 3\n[capacity.repo_slots]\nweb = 1\nelsewhere = 5")
    capacity = config.load(ws.root, canopy_env.user_file).capacity
    # A name outside this map is allowed: one user file serves every workspace.
    assert (capacity.slots_for("api"), capacity.slots_for("web"), capacity.slots_for("elsewhere")) == (3, 1, 5)

    declare(canopy_env, "[capacity.repo_slots]\nAPI = 1")
    with pytest.raises(config.ConfigError, match="repository name 'API'"):
        config.load(ws.root, canopy_env.user_file)
    declare(canopy_env, "slots_per_repo = -1")
    with pytest.raises(config.ConfigError, match=r"capacity\.slots_per_repo"):
        config.load(ws.root, canopy_env.user_file)

    canopy_env.write_user(user_toml())
    assert config.load(ws.root, canopy_env.user_file).capacity.slots_for("api") is None  # unmanaged by default
    (ws.root / config.WORKSPACE_FILE_NAME).write_text(map_text(extra="\n[capacity.repo_slots]\napi = 9\n"))
    with pytest.raises(config.ConfigError, match=r"capacity\.repo_slots is private"):
        config.load(ws.root, canopy_env.user_file)


# Leases stay within the declared size


def test_a_full_pool_refuses_a_dispatch_without_asking_treehouse_for_another_slot(
    ws: Ws,
    canopy_env: CanopyEnv,
    treehouse_state: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    declare(canopy_env, "slots_per_repo = 1")
    set_slots(treehouse_state, ws, "api", "leased")
    conn = ws.journal()
    with in_tick(conn):
        runner = InlineRunner()

        assert main(dispatch("api"), runner=runner) == 1
        assert (
            "dispatch refused (no_slot): api: 1 of its slots are busy, and capacity declares 1"
            in capsys.readouterr().err
        )
        assert [c[0] for c in calls(treehouse_state)] == ["status"]
        assert len(slots_of(treehouse_state, ws, "api")) == 1
        assert runner.spawned == []


def test_a_slot_treehouse_makes_past_the_declared_size_is_destroyed(
    ws: Ws,
    canopy_env: CanopyEnv,
    treehouse_state: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    declare(canopy_env, "slots_per_repo = 1")
    stale = str(ws.root / ".treehouse" / "api-fake" / "1" / "api")
    set_slots(treehouse_state, ws, "api", "available", skip_reuse=[stale])
    conn = ws.journal()
    with in_tick(conn):
        assert main(dispatch("api"), runner=InlineRunner()) == 1
        err = capsys.readouterr().err
        assert "no slot of the 1 could be reused, and capacity declares 1" in err
        assert "the new slot " in err
        assert " was removed" in err
        assert [c[0] for c in calls(treehouse_state)] == ["status", "get", "return", "destroy"]
        assert [s["path"] for s in slots_of(treehouse_state, ws, "api")] == [stale]


def test_a_pool_declared_smaller_than_it_is_counts_its_busy_slots(
    ws: Ws,
    canopy_env: CanopyEnv,
    treehouse_state: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    declare(canopy_env, "[capacity.repo_slots]\napi = 0\nweb = 1")
    set_slots(treehouse_state, ws, "api", "available")
    set_slots(treehouse_state, ws, "web", "leased", "available")
    conn = ws.journal()
    with in_tick(conn):
        assert main(dispatch("api"), runner=InlineRunner()) == 1
        assert "api: 0 of its slots are busy, and capacity declares 0" in capsys.readouterr().err
        assert main(dispatch("web"), runner=InlineRunner()) == 1
        assert "web: 1 of its slots are busy, and capacity declares 1" in capsys.readouterr().err
        assert [c[0] for c in calls(treehouse_state)] == ["status", "status"]


def test_a_pool_below_its_size_grows_and_one_at_it_reuses_a_slot(
    ws: Ws,
    canopy_env: CanopyEnv,
    treehouse_state: Path,
) -> None:
    declare(canopy_env, "[capacity.repo_slots]\napi = 2\nweb = 1")
    set_slots(treehouse_state, ws, "api", "leased")
    seed = set_slots(treehouse_state, ws, "web", "available")
    conn = ws.journal()
    with in_tick(conn):
        assert main(dispatch("api", "web"), runner=InlineRunner()) == 0
        assert [s["status"] for s in slots_of(treehouse_state, ws, "api")] == ["leased", "leased"]
        assert [s["path"] for s in slots_of(treehouse_state, ws, "web")] == seed


# Sync converges the pools


def test_sync_fills_each_pool_to_its_size_and_returns_every_lease_it_took(
    ws: Ws,
    canopy_env: CanopyEnv,
    treehouse_state: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    declare(canopy_env, "slots_per_repo = 3\n[capacity.repo_slots]\nweb = 1")
    seed_pools(ws, treehouse_state)

    assert main(["workspace", "sync"]) == 0
    out = capsys.readouterr().out
    assert "api: present\napi: slots: 3 of 3, made 2\n" in out
    assert "web: present\nweb: slots: 1 of 1\n" in out
    api = slots_of(treehouse_state, ws, "api")
    assert [(s["name"], s["status"]) for s in api] == [("1", "available"), ("2", "available"), ("3", "available")]
    gets = [c for c in calls(treehouse_state) if c[0] == "get"]
    assert len(gets) == 3  # slot 1 is leased too, so the next two are new
    assert all("--no-fetch" in c and "canopy-sync" in c for c in gets)

    assert main(["workspace", "sync"]) == 0  # converged: nothing more to do
    assert "api: slots: 3 of 3\n" in capsys.readouterr().out


def test_a_dry_run_previews_the_pool_of_a_repository_not_cloned_yet(
    ws: Ws,
    canopy_env: CanopyEnv,
    treehouse_state: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    declare(canopy_env, "[capacity.repo_slots]\ndocs = 2")
    (ws.root / config.WORKSPACE_FILE_NAME).write_text(map_text(("docs", "https://x.test/docs.git")))
    assert main(["workspace", "sync", "--dry-run"]) == 0
    out = capsys.readouterr().out
    assert (
        f"docs: to clone: https://x.test/docs.git into {ws.clone('docs')}\ndocs: slots: 0 of 2, would make 2\n" in out
    )
    assert not ws.clone("docs").exists()


def test_sync_returns_what_a_dead_sync_left_leased_before_counting(
    ws: Ws,
    canopy_env: CanopyEnv,
    treehouse_state: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    declare(canopy_env, "slots_per_repo = 1")
    set_slots(treehouse_state, ws, "api", "available")
    state = fake_state(treehouse_state)
    pool_of(state, ws, "api")["slots"][0] |= {"status": "leased", "lease_id": "left", "lease_holder": "canopy-sync"}
    treehouse_state.write_text(json.dumps(state))

    assert main(["workspace", "sync"]) == 0
    assert "api: slots: 1 of 1\n" in capsys.readouterr().out
    assert [s["status"] for s in slots_of(treehouse_state, ws, "api")] == ["available"]


def test_sync_reports_a_pool_treehouse_will_not_grow(
    ws: Ws,
    canopy_env: CanopyEnv,
    treehouse_state: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    declare(canopy_env, "[capacity.repo_slots]\napi = 3")
    set_slots(treehouse_state, ws, "api", "available")
    state = fake_state(treehouse_state)
    pool_of(state, ws, "api")["max_trees"] = 2
    treehouse_state.write_text(json.dumps(state))

    assert main(["workspace", "sync"]) == 1
    out = capsys.readouterr().out
    assert "api: failed: 2 of 3, made 1: treehouse get exited 1: " in out
    assert "max_trees" in out
    assert [s["status"] for s in slots_of(treehouse_state, ws, "api")] == ["available", "available"]


def test_sync_removes_idle_slots_over_the_size_highest_first_and_never_a_busy_one(
    ws: Ws,
    canopy_env: CanopyEnv,
    treehouse_state: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    declare(canopy_env, "[capacity.repo_slots]\napi = 1\nweb = 2")
    api = set_slots(treehouse_state, ws, "api", "available", "leased", "available", "available")
    web = set_slots(treehouse_state, ws, "web", "available", "available", "available")

    assert main(["workspace", "sync", "--dry-run"]) == 0
    out = capsys.readouterr().out
    assert "api: slots: 4 of 1, would remove 4, 3, 1\n" in out
    assert len(slots_of(treehouse_state, ws, "api")) == 4

    assert main(["workspace", "sync"]) == 0
    out = capsys.readouterr().out
    assert "api: slots: 1 of 1, removed 4, 3, 1\n" in out
    assert "web: slots: 2 of 2, removed 3\n" in out
    assert [s["path"] for s in slots_of(treehouse_state, ws, "api")] == [api[1]]
    assert not Path(api[3]).exists()
    assert [s["path"] for s in slots_of(treehouse_state, ws, "web")] == web[:2]

    # Only busy slots over the size: they stay until a later sync finds them idle.
    set_slots(treehouse_state, ws, "api", "leased", "in-use")
    assert main(["workspace", "sync"]) == 0
    assert "api: slots: 2 of 1, removed none; 1 over, busy; a later sync removes them once idle\n" in (
        capsys.readouterr().out
    )


def test_sync_passes_over_a_slot_treehouse_keeps_and_says_so_when_it_cannot_converge(
    ws: Ws,
    canopy_env: CanopyEnv,
    treehouse_state: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    declare(canopy_env, "[capacity.repo_slots]\napi = 1")
    unmerged = str(ws.root / ".treehouse" / "api-fake" / "2" / "api")
    paths = set_slots(treehouse_state, ws, "api", "available", "available", unmerged=[unmerged])
    assert main(["workspace", "sync"]) == 0
    assert "api: slots: 1 of 1, removed 1\n" in capsys.readouterr().out
    assert [s["path"] for s in slots_of(treehouse_state, ws, "api")] == [unmerged]
    assert not Path(paths[0]).exists()

    set_slots(treehouse_state, ws, "api", "leased", "available", unmerged=[unmerged])
    assert main(["workspace", "sync"]) == 1
    out = capsys.readouterr().out
    assert "api: kept: 2 of 1, removed none; slot 2 kept: skipped " in out
    assert "unmerged" in out
    assert Path(unmerged).exists()


def test_sync_leaves_unmanaged_pools_alone(ws: Ws, treehouse_state: Path, capsys: pytest.CaptureFixture[str]) -> None:
    set_slots(treehouse_state, ws, "api", "available", "available")
    assert main(["workspace", "sync"]) == 0
    assert "slots" not in capsys.readouterr().out
    assert calls(treehouse_state) == []


def test_sync_waits_for_a_running_tick(
    ws: Ws,
    canopy_env: CanopyEnv,
    treehouse_state: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    declare(canopy_env, "slots_per_repo = 1")
    set_slots(treehouse_state, ws, "api", "available")
    ws.journal()
    held = threading.Event()

    def tick() -> None:
        with lock.hold(ws.state_dir / lock.LOCK_FILE_NAME):
            held.set()
            threading.Event().wait(0.5)

    thread = threading.Thread(target=tick)
    thread.start()
    held.wait()
    try:
        assert main(["workspace", "sync"]) == 0
    finally:
        thread.join()
    assert "A tick is running; sync starts when it ends.\n" in capsys.readouterr().out


# Sync removes clones the map no longer lists


def drop_from_map(ws: Ws, *keep: str) -> None:
    (ws.root / config.WORKSPACE_FILE_NAME).write_text(map_text(*((n, str(ws.origins[n])) for n in keep)))


def test_sync_removes_a_clean_clone_the_map_dropped_with_its_slots(
    ws: Ws,
    treehouse_state: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    seed_pools(ws, treehouse_state)
    [web_slot] = [s["path"] for s in slots_of(treehouse_state, ws, "web")]
    drop_from_map(ws, "api")
    (ws.root / "repos" / ".keep").write_text("dot entries are not clones")

    assert main(["workspace", "sync", "--dry-run"]) == 0
    assert f"web: to remove: {ws.clone('web')} and its 1 slots\n" in capsys.readouterr().out
    assert ws.clone("web").exists()

    assert main(["workspace", "sync"]) == 0
    out = capsys.readouterr().out
    assert f"web: removed: {ws.clone('web')} and its 1 slots\n" in out
    assert ".keep" not in out
    assert not ws.clone("web").exists()
    assert not Path(web_slot).exists()
    assert slots_of(treehouse_state, ws, "web") == []
    assert ws.clone("api").exists()


@pytest.mark.parametrize(
    ("change", "reason"),
    [
        ("untracked", "it has uncommitted, untracked, or ignored files"),
        ("ignored", "it has uncommitted, untracked, or ignored files"),
        ("stash", "it has stashed changes"),
        ("unpushed", "it has commits no remote has"),
        ("detached", "it has commits no remote has"),
        ("leased", "slot 1 is leased"),
    ],
)
def test_sync_keeps_a_dropped_clone_with_anything_to_lose(
    ws: Ws,
    treehouse_state: Path,
    capsys: pytest.CaptureFixture[str],
    change: str,
    reason: str,
) -> None:
    clone = ws.clone("web")
    set_slots(treehouse_state, ws, "web", "leased" if change == "leased" else "available")
    if change in ("untracked", "stash"):
        (clone / "notes.txt").write_text("mine")
    if change == "stash":
        git("add", "notes.txt", cwd=clone)
        git("stash", "--quiet", cwd=clone)
    if change == "ignored":
        (clone / ".git" / "info" / "exclude").write_text(".env\n")
        (clone / ".env").write_text("TOKEN=local")
    if change in ("unpushed", "detached"):
        if change == "detached":
            git("checkout", "--quiet", "--detach", cwd=clone)
        git("commit", "--quiet", "--allow-empty", "-m", "local only", cwd=clone)
    drop_from_map(ws, "api")

    assert main(["workspace", "sync"]) == 1
    assert f"web: kept: {reason}" in capsys.readouterr().out
    assert clone.is_dir()
    assert len(slots_of(treehouse_state, ws, "web")) == 1


def test_sync_keeps_what_under_repos_is_not_a_clone(
    ws: Ws,
    treehouse_state: Path,
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    (ws.root / "repos" / "notes").write_text("a file of the operator's")
    (ws.root / "repos" / "linked").symlink_to(tmp_path)

    assert main(["workspace", "sync"]) == 1
    out = capsys.readouterr().out
    assert f"linked: kept: {ws.root / 'repos' / 'linked'} is not a clone" in out
    assert f"notes: kept: {ws.root / 'repos' / 'notes'} is not a clone" in out
    assert (ws.root / "repos" / "notes").is_file()
    assert (ws.root / "repos" / "linked").is_symlink()
    assert treehouse_state.exists() is False


# Repositories by clone URL


@pytest.mark.parametrize(
    ("arg", "expected"),
    [
        ("https://github.com/acme/api.git", ("api", "https://github.com/acme/api.git")),
        ("https://github.com/acme/Web_App/", ("web-app", "https://github.com/acme/Web_App/")),
        ("git@github.com:acme/api.git", ("api", "git@github.com:acme/api.git")),
        ("/srv/git/docs.git", ("docs", "/srv/git/docs.git")),
        ("site=https://github.com/acme/www.git", ("site", "https://github.com/acme/www.git")),
        ("https://x.test/r?ref=main", ("r-ref-main", "https://x.test/r?ref=main")),
    ],
)
def test_a_repository_is_named_after_its_url_unless_named(arg: str, expected: tuple[str, str]) -> None:
    assert setup_workspace.repo_arg(arg) == expected


@pytest.mark.parametrize(
    ("arg", "error"),
    [
        ("--upload-pack", "must be a clone URL"),
        ("--upload-pack=x", "repository name '--upload-pack'"),
        ("API=https://x.test/api.git", "repository name 'API'"),
        ("https://x.test/9/", "NAME=URL"),
    ],
)
def test_a_repository_argument_that_cannot_be_used_is_refused(arg: str, error: str) -> None:
    with pytest.raises(ValueError, match=error):
        setup_workspace.repo_arg(arg)


def test_add_lists_new_urls_in_the_map_and_syncs_them(
    ws: Ws,
    canopy_env: CanopyEnv,
    treehouse_state: Path,
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    declare(canopy_env, "[capacity.repo_slots]\ndocs = 2")
    docs = bare_origin(tmp_path / "origins" / "docs.git", tmp_path)
    map_file = ws.root / config.WORKSPACE_FILE_NAME

    assert main(["workspace", "add", str(docs), str(ws.origins["api"]) + "/"]) == 0
    out = capsys.readouterr().out
    assert "docs: added\napi: present: the map already lists it\n" in out
    assert f"docs: cloning {docs} into {ws.clone('docs')}\ndocs: cloned\ndocs: slots: 2 of 2, made 2\n" in out
    assert [r.name for r in workspace.load(ws.root).repos] == ["api", "docs", "web"]
    assert git("log", "--format=%s", cwd=ws.clone("docs")) == "initial docs"

    # The map is written whole and renamed into place, leaving no partial file.
    assert not map_file.with_name(map_file.name + ".tmp").exists()

    # A name the map gives another URL refuses the whole add: nothing is written.
    before = map_file.read_text()
    assert main(["workspace", "add", "https://x.test/new.git", "docs=https://x.test/other.git"]) == 1
    assert "docs: the map already has a repository by that name" in capsys.readouterr().err
    assert map_file.read_text() == before


def test_init_with_clone_urls_sets_up_a_workspace_ready_to_run(
    canopy_env: CanopyEnv,
    treehouse_state: Path,
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    authors = dict.fromkeys(GIT_AUTHORS, "canopy-test")
    with mock.patch.dict(os.environ, {**authors, "GIT_CONFIG_GLOBAL": os.devnull, "GIT_CONFIG_NOSYSTEM": "1"}):
        origins = [bare_origin(tmp_path / "origins" / f"{n}.git", tmp_path) for n in ("api", "web")]
        declare(canopy_env, "slots_per_repo = 2")
        root = tmp_path / "acme"
        root.mkdir()
        with contextlib.chdir(root):
            assert main(["init", "--workspace", "--provider", "github", *map(str, origins)]) == 0
            out = capsys.readouterr().out
            assert "api: added\nweb: added\n" in out
            assert "api: cloned\napi: slots: 2 of 2, made 2\n" in out
            assert "web: cloned\nweb: slots: 2 of 2, made 2\n" in out
            assert "  - api\n  - web\n" in out  # branch protection names both
            ws = workspace.load(root)
            assert [(r.name, r.url, r.cloned) for r in ws.repos] == [
                ("api", str(origins[0]), True),
                ("web", str(origins[1]), True),
            ]
            assert config.load(root, canopy_env.user_file).tracker.provider == "github"
            assert len(fake_state(treehouse_state)["pools"]) == 2


def test_sync_warns_about_an_origin_rewritten_to_push_over_ssh(
    canopy_env: CanopyEnv,
    treehouse_state: Path,
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """What git pushes to after the operator's rewrites, not the map's URL, which is a local path here."""
    authors = dict.fromkeys(GIT_AUTHORS, "canopy-test")
    with mock.patch.dict(os.environ, {**authors, "GIT_CONFIG_NOSYSTEM": "1"}):
        origins = tmp_path / "origins"
        origin = bare_origin(origins / "api.git", tmp_path)
        global_config = tmp_path / "gitconfig"
        pushes_over_ssh = ("url.git@example.test:acme/.pushInsteadOf", f"{origins}/")
        git("config", "--file", str(global_config), *pushes_over_ssh, cwd=tmp_path)
        root = tmp_path / "acme"
        root.mkdir()
        with mock.patch.dict(os.environ, {"GIT_CONFIG_GLOBAL": str(global_config)}), contextlib.chdir(root):
            assert main(["init", "--provider", "github", str(origin)]) == 0
            assert "api: warning: origin pushes over SSH (git@example.test:acme/api.git)" in capsys.readouterr().out


def test_clone_urls_in_a_code_checkout_are_refused(
    canopy_env: CanopyEnv,
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    checkout = tmp_path / "code"
    (checkout / ".git").mkdir(parents=True)
    with contextlib.chdir(checkout):
        assert main(["init", "--provider", "jira", "https://x.test/api.git"]) == 2
        assert "Pass --workspace" in capsys.readouterr().err
        assert not (checkout / config.WORKSPACE_FILE_NAME).exists()
