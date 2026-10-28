"""Settling (DESIGN §21): a PR's head commit is reviewed once canopy has seen it for `review.settle_minutes`."""

from typing import Final

import pytest

from canopy.core.config import MAX_SETTLE_MINUTES, ConfigError, load
from tests.canopy.helpers import waits
from tests.canopy.review_helpers import CLEAN, PR, head, review_decisions, reviewer_reports
from tests.canopy.scenario_helpers import Scenario, reviews
from tests.conftest import CanopyEnv, GitPool

# A PR the operator names, with no ticket.
OTHER_PR: Final = f"{PR}0"


def test_a_head_is_reviewed_once_it_has_settled_and_a_new_push_starts_over(
    reviewing: CanopyEnv,
    scenario: Scenario,
    git_pool: GitPool,
) -> None:
    scenario.configures(review={"settle_minutes": 30})
    first, second = "a" * 40, head(git_pool)
    [(action, why)] = scenario.refuses(reviews(first))
    assert action == "refused:settling"
    assert why.startswith(f"{first[:12]} was first seen now and settles at ")
    assert why.endswith("(review.settle_minutes = 30); a newer push starts over")
    scenario.time_passes(minutes=20)
    [(action, why)] = scenario.refuses(reviews(first))
    assert (action, why.startswith(f"{first[:12]} was first seen at ")) == ("refused:settling", True)
    # A push: the new head waits the whole settle time again.
    assert [a for a, _ in scenario.refuses(reviews(second))] == ["refused:settling"]
    scenario.time_passes(minutes=31)
    assert scenario.review(reviews(second), reviewer=reviewer_reports(CLEAN)).status == "done"


def test_a_force_push_back_to_an_earlier_head_starts_its_wait_over(reviewing: CanopyEnv, scenario: Scenario) -> None:
    scenario.configures(review={"settle_minutes": 30})
    first, second = "a" * 40, "b" * 40
    scenario.refuses(reviews(first))
    scenario.time_passes(minutes=60)
    scenario.refuses(reviews(second))
    # Back to the first commit: it is the head from now, not from an hour ago.
    [(_, why)] = scenario.refuses(reviews(first))
    assert why.startswith(f"{first[:12]} was first seen now ")
    rows = scenario.conn.execute("SELECT pr_url, sha FROM review_heads").fetchall()
    assert [tuple(r) for r in rows] == [(PR, first)]


def test_a_dry_run_reads_a_heads_settle_time_and_never_starts_it(reviewing: CanopyEnv, scenario: Scenario) -> None:
    scenario.configures(review={"settle_minutes": 30})
    sha = "a" * 40
    assert [a for a, _ in scenario.refuses(reviews(sha), dry_run=True)] == ["refused:settling"]
    assert scenario.conn.execute("SELECT count(*) FROM review_heads").fetchone()[0] == 0
    # Seen by a live tick long enough ago, it would be reviewed.
    scenario.refuses(reviews(sha))
    scenario.time_passes(minutes=31)
    with scenario.ticking(dry_run=True) as tick_id:
        scenario.overseer(*reviews(sha)[1:])
    assert [d[2] for d in review_decisions(scenario.conn, tick_id)] == ["dispatch:review"]


def test_with_settling_off_no_head_is_recorded(reviewing: CanopyEnv, scenario: Scenario, git_pool: GitPool) -> None:
    assert scenario.review(reviews(head(git_pool)), reviewer=reviewer_reports(CLEAN)).status == "done"
    assert scenario.conn.execute("SELECT count(*) FROM review_heads").fetchone()[0] == 0


def test_a_review_the_operator_asked_for_does_not_wait(
    canopy_env: CanopyEnv,
    scenario: Scenario,
    git_pool: GitPool,
) -> None:
    template = "env OPENCODE_CONFIG_DIR={definitions_dir} agent run --agent canopy-reviewer {prompt}"
    scenario.configures(runtime={"review_cmd": template}, review={"settle_minutes": 30})
    scenario.operator("start", OTHER_PR, "--review")
    assert scenario.review(reviews(head(git_pool), OTHER_PR), reviewer=reviewer_reports(CLEAN)).status == "done"


def test_the_state_block_shows_the_heads_still_settling(
    reviewing: CanopyEnv,
    scenario: Scenario,
    git_pool: GitPool,
) -> None:
    scenario.configures(review={"settle_minutes": 30})
    sha = head(git_pool)
    scenario.refuses(reviews("c" * 40, OTHER_PR))
    scenario.time_passes(minutes=20)
    scenario.refuses(reviews("a" * 40))
    scenario.refuses(reviews(sha))
    scenario.tick(*waits("PROJ-1"), dry_run=True)
    section = scenario.state()["reviews"]
    assert section["limits"]["settle_minutes"] == 30
    # Newest first; PR's first head was pushed over, so only its newer one is its head.
    assert [(h["pr"], h["sha"]) for h in section["settling"]] == [(PR, sha), (OTHER_PR, "c" * 40)]
    # Settled, a head is no longer listed, reviewed or not.
    scenario.time_passes(minutes=15)
    scenario.tick(*waits("PROJ-1"), dry_run=True)
    assert [h["pr"] for h in scenario.state()["reviews"]["settling"]] == [PR]


def test_settle_minutes_is_at_most_a_week(canopy_env: CanopyEnv) -> None:
    canopy_env.append_user(f"\n[review]\nsettle_minutes = {MAX_SETTLE_MINUTES}\n")
    assert load(canopy_env.root, canopy_env.user_file).review.settle_minutes == MAX_SETTLE_MINUTES
    canopy_env.write_user(
        canopy_env.user_file.read_text().replace(str(MAX_SETTLE_MINUTES), str(MAX_SETTLE_MINUTES + 1)),
    )
    with pytest.raises(ConfigError, match="settle_minutes"):
        load(canopy_env.root, canopy_env.user_file)
