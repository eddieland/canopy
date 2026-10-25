"""`canopy gc --caches` (DESIGN §26, Git in the primary clones): it empties each sandbox role's cache.

It skips a cache while a run of its role is live, or when canopy cannot tell, and follows no link out of one.
"""

import os
import sqlite3
from collections.abc import Iterator
from pathlib import Path
from unittest import mock

import canopy_sandbox
import pytest

from canopy.cli.main import main
from canopy.core import db
from canopy.infra import lock
from canopy.loop import cache_gc
from tests.canopy.scenario_helpers import Scenario
from tests.conftest import CanopyEnv, GitPool


@pytest.fixture
def caches(canopy_env: CanopyEnv) -> Iterator[Path]:
    """The sandbox's cache root, under an XDG_CACHE_HOME of the test's own, with the worker's and the review's caches.

    Yields:
        The root.
    """
    with mock.patch.dict(os.environ, {"XDG_CACHE_HOME": str(canopy_env.home / "xdg-cache")}):
        root = canopy_sandbox.cache_root()
        fill(root / "worker" / "npm" / "_cacache", 300)
        fill(root / "review" / "pip", 40)
        yield root


def fill(directory: Path, size: int) -> None:
    """Make `directory` with a file of `size` bytes in it."""
    directory.mkdir(parents=True)
    (directory / "blob").write_bytes(b"x" * size)


def test_gc_caches_empties_each_roles_cache_following_no_link(
    canopy_env: CanopyEnv,
    caches: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    # The operator's own cache, beside the sandbox's, and reached by a link from inside the worker's.
    own = canopy_env.home / "xdg-cache" / "opencode"
    fill(own, 7)
    (caches / "worker" / "opencode").symlink_to(own)
    (caches / "worker" / "kept").symlink_to(own / "blob")
    # Go's module cache makes its directories read-only.
    fill(caches / "worker" / "go-mod" / "example.com@v1", 5)
    (caches / "worker" / "go-mod" / "example.com@v1").chmod(0o555)
    # A directory no role caches in, and a link where a role's cache would be.
    fill(caches / "unknown", 1)
    (caches / "chore").symlink_to(own)

    assert main(["gc", "--caches"]) == 0

    assert capsys.readouterr().out.splitlines() == [
        "chore: skipped: it is a link, which canopy does not follow",
        "review: emptied: 40 B freed",
        "unknown: skipped: no role canopy knows caches here, so it cannot tell whether a run uses it",
        "worker: emptied: 305 B freed",
    ]
    assert list((caches / "worker").iterdir()) == []
    assert list((caches / "review").iterdir()) == []
    assert (caches / "unknown" / "blob").exists()
    assert (own / "blob").read_bytes() == b"x" * 7


def test_gc_caches_skips_the_worker_cache_while_a_worker_run_is_live_or_its_agent_is(
    scenario: Scenario,
    git_pool: GitPool,
    caches: Path,
) -> None:
    working = scenario.starts()

    printed = scenario.operator("gc", "--caches")
    assert f"worker: skipped: run {working.id} is live and may be using it; run it again once none is" in printed.out
    assert "review: emptied: 40 B freed" in printed.out
    assert (caches / "worker" / "npm" / "_cacache" / "blob").exists()

    # Its own process gone, its worker is still at work until the next tick's reconcile.
    working.dies()
    printed = scenario.operator("gc", "--caches")
    assert f"worker: skipped: run {working.id} is live" in printed.out
    assert (caches / "worker" / "npm" / "_cacache" / "blob").exists()


def test_gc_caches_empties_the_worker_cache_once_its_run_has_ended(
    scenario: Scenario,
    git_pool: GitPool,
    caches: Path,
) -> None:
    scenario.starts().finishes()

    printed = scenario.operator("gc", "--caches")

    assert "worker: emptied: 300 B freed" in printed.out
    assert list((caches / "worker").iterdir()) == []


def test_gc_caches_skips_every_cache_when_it_cannot_read_the_runs(
    canopy_env: CanopyEnv,
    caches: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    broken = sqlite3.OperationalError("database is locked")
    with mock.patch.object(cache_gc.db, "running_runs", autospec=True, side_effect=broken):
        assert main(["gc", "--caches"]) == 0

    out = capsys.readouterr().out
    assert "worker: skipped: canopy could not tell whether a run using it is live: database is locked" in out
    assert "review: skipped: canopy could not tell whether a run using it is live: database is locked" in out
    assert (caches / "worker" / "npm" / "_cacache" / "blob").exists()


def test_gc_caches_empties_the_overseers_cache_only_between_ticks(
    canopy_env: CanopyEnv,
    caches: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """The overseer's runs are ticks: its cache goes under the tick lock, never while a tick holds it."""
    fill(caches / "overseer" / "opencode", 20)

    with lock.hold(canopy_env.state_dir / lock.LOCK_FILE_NAME):
        assert main(["gc", "--caches"]) == 0
    printed = capsys.readouterr().out
    assert "overseer: skipped: a tick is running, whose overseer may be using it; run it again later" in printed
    assert "worker: emptied: 300 B freed" in printed
    assert (caches / "overseer" / "opencode" / "blob").exists()

    assert main(["gc", "--caches"]) == 0
    assert "overseer: emptied: 20 B freed" in capsys.readouterr().out
    assert list((caches / "overseer").iterdir()) == []


def test_gc_caches_says_when_there_is_no_cache(canopy_env: CanopyEnv, capsys: pytest.CaptureFixture[str]) -> None:
    with mock.patch.dict(os.environ, {"XDG_CACHE_HOME": str(canopy_env.home / "none")}):
        assert main(["gc", "--caches"]) == 0
    assert capsys.readouterr().out == f"No sandbox cache is in {canopy_env.home / 'none' / 'canopy' / 'sandbox'}.\n"


def test_every_role_of_the_wrappers_has_the_runs_that_start_as_it() -> None:
    assert set(cache_gc.ROLE_TABLES) == set(canopy_sandbox.ROLES) == set(canopy_sandbox.CACHES)
    assert {name: cache_gc.tables_of(name) for name in sorted(set(canopy_sandbox.CACHES.values()))} == {
        "chore": ("chore_runs",),
        "overseer": (),
        "review": ("review_runs",),
        "worker": ("runs", "task_runs"),
    }
    assert all(set(tables) <= set(db.RUN_TABLES) for tables in cache_gc.ROLE_TABLES.values())
