"""Reviews (DESIGN §21, ROADMAP M11): a fresh reviewer per PR commit, guarded, in a slot it never works in."""

import json
import os
import time
from pathlib import Path
from unittest import mock

import pytest
from syrupy.assertion import SnapshotAssertion

from canopy.cli.main import main
from canopy.core import conversation, db, definitions, review_diff
from canopy.core import review_result as result
from canopy.core.config import load
from canopy.core.vocab import ResumeReason, RunKind
from canopy.infra import procs
from canopy.loop import attention
from canopy.reviews import grants
from tests.canopy.helpers import (
    InlineRunner,
    agent_runs,
    canopy,
    decisions,
    granted_meanwhile,
    in_run,
    in_tick,
    lifelock_left,
    messages,
    pool_statuses,
    present,
    tools_of,
    waits,
    with_events,
)
from tests.canopy.review_helpers import CLEAN, FINDINGS, PR, head, review_decisions, reviewer_reports
from tests.canopy.scenario_helpers import Scenario, dispatches, pushes, reviews
from tests.conftest import CanopyEnv, GitPool, git


@pytest.fixture
def reviewing(canopy_env: CanopyEnv) -> CanopyEnv:
    """Reviews on, for the loop's own PRs, with the reviewer command running the fake agent as `canopy-reviewer`.

    PROJ-1's unit in `repo` has opened `PR`, as its worker's result records it, so a review may name PROJ-1 for it.
    """
    template = "env OPENCODE_CONFIG_DIR={definitions_dir} agent run --agent canopy-reviewer {prompt}"
    user = canopy_env.user_file.read_text().replace("[runtime]\n", f"[runtime]\nreview_cmd = '{template}'\n", 1)
    canopy_env.write_user(user + "\n[review]\nagent_prs = true\n")
    db.set_unit(canopy_env.journal(), "PROJ-1", str(canopy_env.root), "repo", pr_url=PR)
    return canopy_env


def test_with_reviews_off_nothing_about_them_reaches_the_overseer(scenario: Scenario) -> None:
    scenario.tick(dry_run=True)
    assert "reviews" not in scenario.state()
    [(action, _)] = scenario.refuses(reviews("a" * 40))
    assert action == "refused:reviews_off"


def test_max_reviews_zero_turns_reviews_off(reviewing: CanopyEnv, scenario: Scenario) -> None:
    scenario.configures(capacity={"max_reviews": 0})
    scenario.tick(*waits("PROJ-1"), dry_run=True)
    assert "reviews" not in scenario.state()


def test_a_review_runs_outside_the_checkout_at_the_commit(
    reviewing: CanopyEnv, git_pool: GitPool, treehouse_state: Path, agent_log: Path
) -> None:
    """M11 against the fakes: the reviewer reads the checkout at the commit through a link, and the slot goes back."""
    conn = reviewing.journal()
    sha = head(git_pool)
    with (
        in_tick(conn) as tick_id,
        reviewer_reports(FINDINGS, ["git", "-C", "checkout", "rev-parse", "HEAD"], ["pwd"]),
    ):
        assert main(reviews(sha, ticket="PROJ-1", context="Start with src/retry.py")[1:]) == 0
        deadline = time.monotonic() + 30
        row = db.get_review_run(conn, 1)
        while row is not None and row.status == "running" and time.monotonic() < deadline:
            time.sleep(0.05)
            row = db.get_review_run(conn, 1)
        assert row is not None
        assert row.status == "done", Path(row.log_path).read_text()
        assert result.stored(row.result_json) == result.ReviewResult.model_validate(FINDINGS)
        assert (row.pr_url, row.sha, row.ticket_key) == (PR, sha, "PROJ-1")

        [reviewer] = agent_runs(agent_log)
        run_dir = reviewing.state_dir / "reviews" / "1"
        assert reviewer["cwd"] == str(run_dir)
        assert reviewer["argv"][:3] == ["run", "--agent", "canopy-reviewer"]
        assert "CANOPY_TICK_ID" not in reviewer["env"]
        checked, _ = reviewer["commands"]
        assert checked["stdout"].strip() == sha
        assert not run_dir.exists()  # removed, and its link with it, once the run ended
        assert not lifelock_left(row)
        assert pool_statuses(treehouse_state) == ["available", "available"]
        [(ticket, pr, action, rationale)] = review_decisions(conn, tick_id)
        assert (ticket, pr, action) == ("PROJ-1", PR, "dispatch:review")
        assert rationale.startswith(f"review run 1: {sha} in ")
        assert rationale.endswith("; context=Start with src/retry.py")

        prompt = reviewer["argv"][3]
        assert prompt.startswith("# canopy reviewer\n")
        assert f"- Checkout: `{run_dir / 'checkout'}` is the repository at that commit." in prompt
        assert "Post nothing anywhere" in prompt
        assert "canopy-review" not in prompt
        assert "None: never report `low`." in prompt
        assert prompt.rstrip().endswith(result.CONTRACT)


def test_a_review_hears_the_notice_in_force(reviewing: CanopyEnv, scenario: Scenario, git_pool: GitPool) -> None:
    # A review reads CI too, so the operator's notice about an outage reaches it (DESIGN §8, §21).
    scenario.operator("notice", "CI is down.")
    reviewed = scenario.review(reviews(head(git_pool)), reviewer=reviewer_reports(CLEAN))
    assert "## Notice from the operator\n\nCI is down.\n" in reviewed.prompt


@pytest.mark.parametrize("full", [False, True], ids=["defaults", "every-value-set"])
def test_the_reviewer_prompt(
    reviewing: CanopyEnv, scenario: Scenario, git_pool: GitPool, markdown_snapshot: SnapshotAssertion, *, full: bool
) -> None:
    """The reviewer's prompt, whole, so a change to its wording or to what fills it in is a diff in review.

    One with every value at its default, and one with each set: a ticket, the overseer's context, the operator's rule
    for `low`, and a notice. `git_pool` gives the review a pool to lease from; the run starts and never runs.
    """
    command = reviews("b" * 40)
    if full:
        scenario.configures(review={"low_impact": "A change to docs or tests only."})
        scenario.operator("notice", "CI is down.")
        command = reviews("b" * 40, ticket="PROJ-1", context="Start with src/retry.py")
    with in_tick(scenario.conn):
        assert main(command[1:], runner=InlineRunner()) == 0
    prompt = (reviewing.state_dir / "reviews" / "1.prompt").read_text()
    assert prompt.replace(str(reviewing.state_dir), "/state") == markdown_snapshot


@pytest.mark.parametrize(
    ("pr", "sha", "reason"),
    [
        ("http://x.test/pull/1", "a" * 40, "--pr must be the PR's plain https:// URL"),
        (PR, "abc", "--sha must be the full head commit"),
        (PR, "A" * 40, "--sha must be the full head commit"),
    ],
)
def test_bad_pr(reviewing: CanopyEnv, scenario: Scenario, pr: str, sha: str, reason: str) -> None:
    [(action, rationale)] = scenario.refuses(reviews(sha, pr))
    assert action == "refused:bad_pr"
    assert rationale.startswith(reason)


def test_review_guards(reviewing: CanopyEnv, scenario: Scenario, git_pool: GitPool, treehouse_state: Path) -> None:
    # The operator's rule for `low`, so the clean review's impact is recorded as it reported it.
    scenario.configures(policy={"max_reviews_per_pr": 2}, review={"low_impact": "A change to docs or tests only."})
    conn = scenario.conn
    sha = head(git_pool)
    held = scenario.starts_review(reviews(sha), reviewer=reviewer_reports(CLEAN))
    assert [d[2] for d in review_decisions(conn, held.row.tick_id)] == ["dispatch:review"]
    assert [a for a, _ in scenario.refuses(reviews(sha))] == ["refused:running"]
    # max_reviews is 1.
    assert [a for a, _ in scenario.refuses(reviews(sha, f"{PR}0"))] == ["refused:review_capacity"]
    assert held.finishes().status == "done"
    assert scenario.refuses(reviews(sha)) == [
        ("refused:reviewed", f"review run 1 already reviewed {sha[:12]} (clean, impact low); one review per commit")
    ]
    # A commit origin does not have fails its review, which still counts.
    failed = scenario.review(reviews("b" * 40))
    assert failed.status == "failed"
    assert [d[2] for d in review_decisions(conn, failed.row.tick_id)] == ["dispatch:review"]
    limit = "this PR has had 2 review runs and the limit is 2"
    assert scenario.refuses(reviews("c" * 40)) == [
        ("refused:review_limit", limit),
        ("attention:review_limit", f"{limit}; allow it another review with `canopy grant {PR} review`"),
    ]
    assert pool_statuses(treehouse_state) == ["available", "available"]


def test_a_grant_lets_a_pr_at_its_review_limit_be_reviewed_again_and_every_run_still_counts(
    reviewing: CanopyEnv, scenario: Scenario, git_pool: GitPool
) -> None:
    scenario.configures(policy={"max_reviews_per_pr": 1})
    scenario.review(reviews(head(git_pool)), reviewer=reviewer_reports(CLEAN))
    scenario.review(reviews(head(git_pool), f"{PR}0"), reviewer=reviewer_reports(CLEAN))
    [(action, _), (raised, _)] = scenario.refuses(reviews("b" * 40))
    assert (action, raised) == ("refused:review_limit", "attention:review_limit")

    granted = scenario.operator("grant", PR, "review")
    assert f"{PR} has had 1 review runs, and may now have 2." in granted.out
    reviewed = scenario.review(reviews("b" * 40), reviewer=reviewer_reports(CLEAN))
    assert "This is review 2 of at most 2 of this PR." in " ".join(reviewed.prompt.split())

    # The granted run counted like any other, and the grant is that PR's only.
    refused = scenario.refuses(reviews("c" * 40)).decisions[0]
    assert (refused.pr, refused.action, refused.rationale) == (
        PR,
        "refused:review_limit",
        "this PR has had 2 review runs and the limit is 2",
    )
    refused = scenario.refuses(reviews("c" * 40, f"{PR}0")).decisions[0]
    assert (refused.pr, refused.action, refused.rationale) == (
        f"{PR}0",
        "refused:review_limit",
        "this PR has had 1 review runs and the limit is 1",
    )
    granted = scenario.operator("grant", PR, "review", "--runs", "2")
    assert "has had 2 review runs, and may now have 4." in granted.out

    # The state block shows a granted PR's grants beside its review runs; a PR with none has no key.
    scenario.tick(*waits("PROJ-1"), dry_run=True)
    prs = {p["url"]: p for p in scenario.state()["reviews"]["prs"]}
    assert (prs[PR]["review_runs"], prs[PR]["granted"]) == (2, 3)
    assert "granted" not in prs[f"{PR}0"]


def test_a_review_grant_reports_the_limit_of_its_own_transaction_whatever_grant_commits_beside_it(
    reviewing: CanopyEnv, scenario: Scenario, git_pool: GitPool
) -> None:
    conn = scenario.conn
    scenario.review(reviews(head(git_pool)), reviewer=reviewer_reports(CLEAN))
    cfg = load(reviewing.root, reviewing.user_file)
    other = "INSERT INTO review_grants (pr_url, runs, granted_at) VALUES (?, 1, ?)"
    # No other grant commits between this one and the read of its limit, so two at once never report the same (#341).
    with granted_meanwhile(conn, grants, "limit", other, PR, db.now()) as tried:
        granted = grants.grant(conn, cfg, conversation.parse_ref(PR), runs=1)
    assert tried == ["locked"]
    assert (granted.runs, granted.limit) == (1, cfg.policy.max_reviews_per_pr + 1)


@pytest.mark.parametrize("env", ["CANOPY_TICK_ID", "CANOPY_RUN_ID"])
def test_only_the_operator_grants_reviews(
    reviewing: CanopyEnv, scenario: Scenario, git_pool: GitPool, capsys: pytest.CaptureFixture[str], env: str
) -> None:
    conn = scenario.conn
    scenario.review(reviews(head(git_pool)), reviewer=reviewer_reports(CLEAN))
    capsys.readouterr()
    # Inside a tick, as the overseer; or inside a run, as its agent, with no tick named.
    with in_tick(conn, ends_ok=True) if env == "CANOPY_TICK_ID" else in_run(1):
        assert main(["grant", PR, "review"]) == 1
        assert "grant refused (inside_run)" in capsys.readouterr().err
    assert conn.execute("SELECT count(*) FROM review_grants").fetchone()[0] == 0


def test_review_grant_refusals(reviewing: CanopyEnv, scenario: Scenario, git_pool: GitPool) -> None:
    conn = scenario.conn
    refused = scenario.operator("grant", PR, "review", code=1)
    assert f"grant refused (unknown): canopy has not reviewed {PR}" in refused.err
    scenario.review(reviews(head(git_pool)), reviewer=reviewer_reports(CLEAN))
    refusals = [
        (["repo#7", "review"], "grant refused (bad_ref): name the PR by its URL"),
        (["PROJ-1", "review"], "grant refused (bad_kind): PROJ-1 is a ticket; `review` takes the PR's URL"),
        ([PR, "implement"], f"grant refused (bad_kind): {PR} is a PR, which takes only `review`"),
        ([PR, "review", "--repo", "repo"], "grant refused (bad_repo): a PR's review limit is the PR's own"),
    ]
    for args, refusal in refusals:
        assert refusal in scenario.operator("grant", *args, code=1).err
    scenario.operator("grant", PR, "review", "--runs", "0", code=2)
    assert conn.execute("SELECT count(*) FROM review_grants").fetchone()[0] == 0


def test_a_review_waits_for_its_tickets_worker_and_counts_against_max_workers(
    reviewing: CanopyEnv, scenario: Scenario, git_pool: GitPool
) -> None:
    scenario.configures(capacity={"max_workers": 1, "max_reviews": 2})
    scenario.starts()
    assert scenario.refuses(reviews(head(git_pool), ticket="PROJ-1")) == [
        ("refused:running", "a worker run for PROJ-1 is running; review its PR once it ends")
    ]
    assert scenario.refuses(reviews(head(git_pool), f"{PR}0")) == [
        ("refused:capacity", "1 of 1 workers and reviews are running")
    ]


def test_a_running_review_takes_worker_capacity(reviewing: CanopyEnv, scenario: Scenario, git_pool: GitPool) -> None:
    scenario.configures(capacity={"max_workers": 1})
    held = scenario.starts_review(reviews(head(git_pool)), reviewer=reviewer_reports(CLEAN))
    assert scenario.refuses(dispatches()) == [("refused:capacity", "1 of 1 workers are running")]
    assert held.finishes().status == "done"


def test_a_dry_run_counts_its_reviews(reviewing: CanopyEnv) -> None:
    conn = reviewing.journal()
    with in_tick(conn, dry_run=True) as tick_id:
        runner = InlineRunner()
        assert main(reviews("a" * 40)[1:], runner=runner) == 0
        assert main(reviews("a" * 40)[1:], runner=runner) == 1
        assert main(reviews("a" * 40, f"{PR}0")[1:], runner=runner) == 1
        assert [d[2:] for d in review_decisions(conn, tick_id)] == [
            ("dispatch:review", f"dry run: not dispatched; would review {'a' * 40}"),
            ("refused:running", "this dry run already reviewed this PR"),
            ("refused:review_capacity", "1 of 1 review runs are running"),
        ]
        assert runner.spawned == []
        assert conn.execute("SELECT count(*) FROM review_runs").fetchone()[0] == 0


@pytest.mark.parametrize(
    ("report", "status", "note"),
    [
        # A reviewer from before reviews stayed in canopy may still name a comment: it is ignored (D114).
        ({**FINDINGS, "comment": f"{PR}#issuecomment-1"}, "done", ""),
        (CLEAN, "done", "reported low impact, but review.low_impact is not set; recorded as normal"),
        ({**CLEAN, "findings": FINDINGS["findings"]}, "unknown", "the reviewer's last line was not a valid result"),
        ({"status": "failed", "summary": "cannot read the PR"}, "failed", ""),
    ],
)
def test_the_harness_checks_what_it_can_of_a_result(
    reviewing: CanopyEnv, scenario: Scenario, git_pool: GitPool, report: dict[str, object], status: str, note: str
) -> None:
    row = scenario.review(reviews(head(git_pool)), reviewer=reviewer_reports(report)).row
    assert row.status == status
    assert row.result_json is not None
    stored = json.loads(row.result_json)
    assert stored.get("harness", "").startswith(note)
    if status == "done":
        assert stored["impact"] == "normal"


@pytest.mark.parametrize("events", [False, True])
def test_a_plugin_notice_after_the_result_does_not_hide_it(
    reviewing: CanopyEnv, scenario: Scenario, git_pool: GitPool, *, events: bool
) -> None:
    # A plugin the operator must load prints after the agent's last word; it lands in the text (DESIGN §13).
    if events:
        with_events(reviewing, "canopy-reviewer")
    reviewer = reviewer_reports(f"{json.dumps(FINDINGS)}\n[policy-plugin] session audited, 0 violations")
    row = scenario.review(reviews(head(git_pool)), reviewer=reviewer).row
    assert row.status == "done"
    assert json.loads(row.result_json or "{}")["verdict"] == "findings"


def test_a_review_records_the_prs_own_title(reviewing: CanopyEnv, scenario: Scenario, git_pool: GitPool) -> None:
    """A PR canopy only reviews has no ticket's title to show, so the reviewer reports the PR's own (DESIGN §21)."""
    scenario.review(reviews(head(git_pool)), reviewer=reviewer_reports({**FINDINGS, "pr_title": "Retry the\n  queue"}))
    # A result without one, as an older override prints, records none.
    scenario.review(reviews(head(git_pool), f"{PR}0"), reviewer=reviewer_reports(CLEAN))
    titles = {str(r["url"]): r["pr_title"] for r in db.pull_requests(scenario.conn, 10)}
    assert titles == {PR: "Retry the queue", f"{PR}0": None}  # on one line


def test_links_out_of_the_checkout_are_removed_before_the_reviewer_reads_it(
    reviewing: CanopyEnv, scenario: Scenario, git_pool: GitPool, tmp_path: Path
) -> None:
    secret = tmp_path / "secret.txt"
    secret.write_text("operator only\n")
    work = git_pool.slots[1]
    git("checkout", "--quiet", "-b", "pr-7", "origin/main", cwd=work)
    (work / "inside").symlink_to("README.md" if (work / "README.md").exists() else ".")
    (work / "outside").symlink_to(secret)
    (work / "up").symlink_to("../..")
    git("add", "inside", "outside", "up", cwd=work)
    git("commit", "--quiet", "-m", "links", cwd=work)
    git("push", "--quiet", "origin", "pr-7", cwd=work)
    sha = git("rev-parse", "HEAD", cwd=work)
    git("checkout", "--quiet", "--detach", cwd=work)
    reviewed = scenario.review(reviews(sha), reviewer=reviewer_reports(FINDINGS, ["ls", "checkout/"]))
    assert reviewed.status == "done", reviewed.printed.out
    [reviewer] = agent_runs(scenario.agent_log)
    [listing] = reviewer["commands"]
    names = listing["stdout"].split()
    assert "inside" in names
    assert "outside" not in names
    assert "up" not in names


@pytest.mark.parametrize("phase", ["review_pending", "review_findings"])
def test_the_review_phases_are_a_units(reviewing: CanopyEnv, scenario: Scenario, phase: str) -> None:
    scenario.overseer("ticket", "set", "PROJ-1", "--repo", "repo", "--phase", phase)
    [unit] = db.units(scenario.conn, "PROJ-1")
    assert unit["phase"] == phase


def test_a_commit_origin_does_not_have_fails_the_review(
    reviewing: CanopyEnv, scenario: Scenario, git_pool: GitPool, treehouse_state: Path
) -> None:
    """A PR of another repository fails here: its commit cannot be fetched from this one's origin."""
    row = scenario.review(reviews("d" * 40)).row
    assert row.status == "failed"
    assert json.loads(row.result_json or "{}")["harness"].startswith("git fetch failed: ")
    assert not scenario.agent_log.exists()  # the reviewer never ran
    assert pool_statuses(treehouse_state) == ["available", "available"]


def test_a_killed_review_is_crashed_on_the_next_tick(
    reviewing: CanopyEnv, scenario: Scenario, git_pool: GitPool, treehouse_state: Path
) -> None:
    held = scenario.starts_review(reviews(head(git_pool)), reviewer=reviewer_reports(CLEAN))
    agent_pid = present(held.row.agent_pid)
    run_dir = reviewing.state_dir / "reviews" / str(held.id)
    assert (run_dir / "checkout").is_symlink()
    held.dies()
    assert pool_statuses(treehouse_state) == ["leased", "available"]

    scenario.tick(*waits("PROJ-1"))
    crashed = held.row
    assert crashed.status == "crashed"
    assert not procs.lifelock(Path(crashed.log_path)).exists()
    deadline = time.monotonic() + 30
    while procs.alive(agent_pid) and time.monotonic() < deadline:
        time.sleep(0.05)
    assert not procs.alive(agent_pid)
    assert pool_statuses(treehouse_state) == ["available", "available"]
    assert not run_dir.exists()
    assert git_pool.slots[0].is_dir()  # removing the run's directory never follows its link


def test_reconcile_leaves_a_running_reviews_slot_alone(
    reviewing: CanopyEnv, scenario: Scenario, git_pool: GitPool, treehouse_state: Path
) -> None:
    held = scenario.starts_review(reviews(head(git_pool)), reviewer=reviewer_reports(CLEAN))
    scenario.tick(*waits("PROJ-1"))
    assert pool_statuses(treehouse_state) == ["leased", "available"]
    assert held.row.status == "running"
    assert held.finishes().status == "done"
    assert pool_statuses(treehouse_state) == ["available", "available"]


def test_the_state_block_shows_reviewed_prs(reviewing: CanopyEnv, scenario: Scenario, git_pool: GitPool) -> None:
    scenario.review(reviews(head(git_pool), ticket="PROJ-1"), reviewer=reviewer_reports(FINDINGS))
    scenario.tick(*waits("PROJ-1"), dry_run=True)
    section = scenario.state()["reviews"]
    assert section["agent_prs"] is True
    assert section["query"] is None
    assert section["limits"] == {
        "max_reviews": 1,
        "max_reviews_per_day": 20,
        "max_reviews_per_pr": 3,
        "started_last_24h": 1,
    }
    assert section["running"] == []
    [reviewed] = section["prs"]
    assert (reviewed["url"], reviewed["ticket"], reviewed["review_runs"]) == (PR, "PROJ-1", 1)
    latest = reviewed["latest"]
    assert (latest["status"], latest["verdict"], latest["impact"]) == ("done", "findings", "normal")
    assert latest["findings"] == ["retry never stops"]
    assert latest["reviewed_at"] == f"{latest['ended_at'][:19]}Z"
    # The overseer passes it as the unit's review cursor, which takes whole seconds only.
    scenario.overseer("ticket", "set", "PROJ-1", "--repo", "repo", "--cursor", f"review={latest['reviewed_at']}")
    assert "comment" not in latest


def test_attention_about_a_pr_without_a_ticket(reviewing: CanopyEnv, scenario: Scenario) -> None:
    scenario.tick(
        canopy("attention", "--pr", PR, "review_failed", "--detail", "review run 3 ended crashed"),
        canopy("attention", "PROJ-1", "review_limit", "--pr", f"{PR}0", "--detail", "3 of 3 reviews"),
    )
    conn = scenario.conn
    assert [(i.subject, i.reason, i.detail) for i in attention.current(conn)] == [
        ("PROJ-1", "review_limit", f"3 of 3 reviews; allow it another review with `canopy grant {PR}0 review`"),
        (f"pr:{PR}", "review_failed", "review run 3 ended crashed"),
    ]
    assert f"pr:{PR}  attention:review_failed" in scenario.operator("decisions").out
    with scenario.ticking() as tick_id:
        scenario.overseer("attention", "review_failed", "--detail", "x", code=2)
        scenario.overseer("attention", "--pr", "http://plain", "review_failed", "--detail", "x", code=2)
    assert review_decisions(conn, tick_id) == []


def test_review_wait_records_a_plain_pr_url_and_refuses_anything_else(reviewing: CanopyEnv, scenario: Scenario) -> None:
    conn = scenario.conn
    with scenario.ticking() as tick_id:
        for bad in ("http://x.test/pull/1", "javascript:alert(1)", f"{PR}/{'x' * 300}"):
            refused = scenario.overseer("review", "wait", "--pr", bad, "--rationale", "draft", code=2)
            assert "must be a plain https:// URL" in refused.err
        assert review_decisions(conn, tick_id) == []
        scenario.overseer("review", "wait", "--pr", PR, "--rationale", "draft")
        assert review_decisions(conn, tick_id) == [(None, PR, "wait", "draft")]


def test_a_sink_that_takes_reviews_hears_when_one_ends(
    reviewing: CanopyEnv, scenario: Scenario, git_pool: GitPool, sink_script: Path, tmp_path: Path
) -> None:
    out = tmp_path / "sink.txt"
    scenario.configures(
        notify={"sinks": {"s": {"cmd": f"{sink_script} {out}", "format": "text", "events": ["reviews"]}}}
    )
    scenario.tick(*waits("PROJ-1"))
    scenario.review(reviews(head(git_pool), ticket="PROJ-1"), reviewer=reviewer_reports(FINDINGS))
    scenario.tick(*waits("PROJ-1"))
    [message] = messages(out)
    assert f"< review run 1 of {PR} (PROJ-1) ended done: findings normal (1 findings)\n" in message


def test_a_reviewer_prompt_that_does_not_render_costs_the_pr_nothing(
    reviewing: CanopyEnv, scenario: Scenario, git_pool: GitPool, treehouse_state: Path
) -> None:
    overrides = reviewing.user_file.parent / "prompts"
    overrides.mkdir()
    (overrides / "reviewer.md").write_text("Review {{PR_URL}}\n")
    [(action, reason)] = scenario.refuses(reviews(head(git_pool)))
    assert action == "refused:bad_prompt"
    assert reason.endswith("missing required placeholder {{SHA}}, {{CHECKOUT}}")
    assert scenario.conn.execute("SELECT count(*) FROM review_runs").fetchone()[0] == 0
    assert pool_statuses(treehouse_state) == ["available", "available"]


def test_a_review_run_records_what_it_cost(reviewing: CanopyEnv, scenario: Scenario, git_pool: GitPool) -> None:
    """With OpenCode's JSON events, as the default `review_cmd` asks for, a review run records its session and cost."""
    with_events(reviewing, "canopy-reviewer")
    reviewer = reviewer_reports(FINDINGS, ["echo", "read it"], session="ses_review")
    reviewed = scenario.review(reviews(head(git_pool)), reviewer=reviewer)
    conn, row, run_id = scenario.conn, reviewed.row, reviewed.id
    assert row.status == "done", reviewed.printed.out  # the result line is read from the text events
    assert row.session_id == "ses_review"
    usage = present(db.usage_of(row))
    assert usage.cost_usd == 0.25  # two model calls at 0.125
    assert (usage.first_call, usage.first_cache_write) == (5500, 500)
    assert (reviewing.state_dir / definitions.RUNTIME_DIR / row.definitions_digest).is_dir()
    assert db.spent_since(conn, "2000-01-01T00:00:00Z") == 0.25
    assert tools_of(conn, "review_runs", run_id) == [("bash", 1, 0, len("read it\n"))]


def test_a_timed_out_review_records_what_it_reported_before_the_kill(
    reviewing: CanopyEnv, scenario: Scenario, git_pool: GitPool
) -> None:
    tokens = {"input": 1, "output": 2, "reasoning": 0, "cache": {"read": 3, "write": 4}}
    events = [
        {"type": "step_finish", "sessionID": "ses_slow", "part": {"cost": 0.5, "tokens": tokens}},
        {"type": "text", "sessionID": "ses_slow", "part": {"type": "text", "text": "still reading"}},
    ]
    stdout = "".join(json.dumps(e) + "\n" for e in events)
    runner = InlineRunner(timeout_agent=True, timeout_stdout=stdout)
    row = scenario.review(reviews(head(git_pool)), runner=runner).row
    assert row.status == "timeout"
    assert (row.session_id, row.cost_usd, row.tokens_cache_write) == ("ses_slow", 0.5, 4)


def test_the_default_review_cmd_asks_for_events(canopy_env: CanopyEnv) -> None:
    assert "--format json" in load(canopy_env.root, canopy_env.user_file).runtime.review_cmd


def resume(
    review_run: int | None = None,
    *reasons: ResumeReason,
    cursors: dict[str, str] | None = None,
    context: str | None = None,
) -> list[str]:
    """The overseer dispatches a `resume` of PROJ-1 for review feedback, and for `reasons` besides (DESIGN §8)."""
    return dispatches(
        kind=RunKind.RESUME,
        reasons=[ResumeReason.REVIEW, *reasons],
        review_run=review_run,
        cursors=cursors,
        context=context,
    )


def test_a_resume_for_a_review_carries_its_findings_from_the_journal(
    reviewing: CanopyEnv, scenario: Scenario, git_pool: GitPool
) -> None:
    """Nothing of a review is on the PR (D114): the worker reads its findings in its prompt."""
    sha = head(git_pool)
    review_id = scenario.review(reviews(sha, ticket="PROJ-1"), reviewer=reviewer_reports(FINDINGS)).id
    scenario.run(worker=pushes())
    resumed = scenario.run(resume(review_id, context="Address review run 1"), worker=pushes())
    [(action, rationale)] = decisions(scenario.conn, int(resumed.row["tick_id"]))
    assert action == "dispatch:resume"
    assert rationale.endswith(f"; review run {review_id}; for review")
    section = resumed.prompt.split("## canopy's review\n\n", 1)[1].split("\n\nThese findings", 1)[0]
    assert section == (
        f"canopy's review run {review_id} of {PR} at commit `{sha}` found these (verdict findings, impact normal). "
        "They are in canopy's journal only, not on the PR:\n"
        "1. **blocking** `src/retry.py:42`: retry never stops\n"
        "   > The loop resets attempts on every error.\n"
        "   > A failing call retries forever."
    )


def test_a_resume_without_a_review_says_so(reviewing: CanopyEnv, scenario: Scenario, git_pool: GitPool) -> None:
    scenario.run(worker=pushes())
    assert "## canopy's review\n\nNone.\n" in scenario.run(resume(), worker=pushes()).prompt


def test_a_review_run_goes_only_to_a_resume_of_its_own_ticket(
    reviewing: CanopyEnv, scenario: Scenario, git_pool: GitPool
) -> None:
    sha = head(git_pool)
    of_ticket = scenario.review(reviews(sha, ticket="PROJ-1"), reviewer=reviewer_reports(FINDINGS)).id
    of_query = scenario.review(reviews(sha, f"{PR}0"), reviewer=reviewer_reports(FINDINGS)).id
    # A commit origin does not have: the run fails, with nothing for a worker.
    failed = scenario.review(reviews("b" * 40, ticket="PROJ-1"), reviewer=reviewer_reports(FINDINGS)).id
    scenario.run(worker=pushes())
    for command, why in [
        (resume(99), "there is no review run 99"),
        (resume(of_query), f"review run {of_query} reviewed {PR}0, not a PR of PROJ-1"),
        (resume(failed), f"review run {failed} ended failed with no findings to address"),
        (
            dispatches(review_run=of_ticket),
            "--review-run names findings for a resume to address; it is for resume only",
        ),
    ]:
        assert scenario.refuses(command) == [("refused:bad_review", why)]


def test_the_operator_reads_reviews_in_canopy(reviewing: CanopyEnv, scenario: Scenario, git_pool: GitPool) -> None:
    assert scenario.operator("review", "show").out == "no reviews in the last 14 days\n"
    sha = head(git_pool)
    reviewer = reviewer_reports({**FINDINGS, "summary": "One blocking defect.\x1b[2J"})
    run_id = scenario.review(reviews(sha, ticket="PROJ-1"), reviewer=reviewer).id
    [line] = scenario.operator("review", "show").out.splitlines()
    assert line.startswith(f"{run_id}  ")
    assert line.endswith(f"  done  findings, 1 findings, impact normal  {PR} @ {sha[:7]}")
    shown = scenario.operator("review", "show", str(run_id)).out
    assert shown.startswith(f"review run {run_id} of {PR} (PROJ-1) at {sha}\ndone, started ")
    assert "\x1b" not in shown
    assert "verdict findings, impact normal\n\nOne blocking defect. [2J\n\n1. **blocking** `src/retry.py:42`" in shown
    scenario.operator("review", "show", "99", code=1)


def feature_commit(git_pool: GitPool, tmp_path: Path) -> str:
    """Push a commit adding `retry.py` on a branch `feature` off origin's `main`, and return it."""
    seed = tmp_path / "seed"
    git("checkout", "--quiet", "-b", "feature", cwd=seed)
    (seed / "retry.py").write_text("while True:\n    call()\n")
    git("add", "retry.py", cwd=seed)
    git("commit", "--quiet", "-m", "retry", cwd=seed)
    git("push", "--quiet", str(git_pool.origin), "feature", cwd=seed)
    return present(git_pool.remote_head("feature"))


def test_a_review_keeps_its_commits_diff_for_the_web_ui(
    reviewing: CanopyEnv, scenario: Scenario, git_pool: GitPool, tmp_path: Path
) -> None:
    """The diff against where the commit leaves the pool's base branch, beside the run's log (DESIGN §21)."""
    sha = feature_commit(git_pool, tmp_path)
    row = scenario.review(reviews(sha), reviewer=reviewer_reports(FINDINGS)).row
    assert (row.status, row.base_branch) == ("done", "main")
    path = review_diff.path_for(row.log_path)
    assert path.stat().st_mode & 0o777 == 0o600
    diff = present(review_diff.read(path))
    [changed] = diff.files
    assert changed.path == "retry.py"
    assert [(ln.kind, ln.new, ln.text) for ln in changed.hunks[0].lines] == [
        ("add", 1, "while True:"),
        ("add", 2, "    call()"),
    ]


def test_a_review_without_its_base_branch_still_runs(
    reviewing: CanopyEnv, scenario: Scenario, git_pool: GitPool, tmp_path: Path
) -> None:
    """The diff is for the page only: a base origin no longer has leaves the review as it was, without one."""
    sha = feature_commit(git_pool, tmp_path)
    git("update-ref", "-d", "refs/heads/main", cwd=git_pool.origin)
    reviewed = scenario.review(reviews(sha), reviewer=reviewer_reports(FINDINGS))
    assert reviewed.status == "done", reviewed.printed.out
    assert not review_diff.path_for(reviewed.row.log_path).exists()


TWO_FINDINGS = {
    **FINDINGS,
    "findings": [
        *FINDINGS["findings"],
        {"severity": "minor", "title": "log line is noisy", "location": "src/retry.py:7", "detail": "It logs twice."},
    ],
}


def test_a_dismissed_finding_reaches_no_worker_and_no_tick(
    reviewing: CanopyEnv, scenario: Scenario, git_pool: GitPool, capsys: pytest.CaptureFixture[str]
) -> None:
    conn = scenario.conn
    review_id = scenario.review(reviews(head(git_pool), ticket="PROJ-1"), reviewer=reviewer_reports(TWO_FINDINGS)).id
    ref = f"review:{review_id}"

    # Only the operator dismisses, and only a finding the review has.
    with mock.patch.dict(os.environ, {"CANOPY_TICK_ID": "1"}):
        assert main(["dismiss", ref, "2"]) == 1
        assert "dismiss refused (inside_run)" in capsys.readouterr().err
    for args, guard in [
        ([ref, "3"], "unknown"),
        ([ref, "0"], "bad_finding"),
        ([ref, "two"], "bad_finding"),
        (["review:99", "1"], "unknown"),
        (["review:x", "1"], "bad_ref"),
        ([ref, "2", "--undo"], "unknown"),
    ]:
        assert f"dismiss refused ({guard})" in scenario.operator("dismiss", *args, code=1).err

    dismissed = scenario.operator("dismiss", ref, "2")
    assert f"{ref} finding 2 is dismissed: no worker or tick acts on it." in dismissed.out
    shown = scenario.operator("review", "show", str(review_id)).out
    assert "2. **minor** `src/retry.py:7`: log line is noisy (dismissed)" in shown
    assert "findings, 2 findings (1 dismissed), impact normal" in scenario.operator("review", "show").out

    # The overseer reads only the findings the operator kept.
    scenario.tick(*waits("PROJ-1"), dry_run=True)
    latest = scenario.state()["reviews"]["prs"][0]["latest"]
    assert (latest["findings"], latest["dismissed_findings"]) == (["retry never stops"], 1)

    # A resume hands the worker the kept one, under its own number.
    scenario.run(worker=pushes())
    prompt = scenario.run(resume(review_id), worker=pushes()).prompt
    assert "1. **blocking** `src/retry.py:42`: retry never stops" in prompt
    assert "log line is noisy" not in prompt

    # With every finding dismissed, there is nothing for a worker to address.
    scenario.operator("dismiss", ref, "1")
    assert scenario.refuses(resume(review_id)) == [
        (
            "refused:bad_review",
            f"the operator dismissed every finding of review run {review_id}: none is left to address",
        )
    ]

    # Undo hands it back.
    undone = scenario.operator("dismiss", ref, "1", "--undo")
    assert "is no longer dismissed: a resume hands it to the worker again." in undone.out
    assert db.review_dismissals(conn, review_id) == frozenset({2})


def test_findings_sent_to_a_worker_reach_its_ticket_as_the_operators_go_ahead(
    reviewing: CanopyEnv, scenario: Scenario, git_pool: GitPool, capsys: pytest.CaptureFixture[str]
) -> None:
    """`canopy send review:ID N` replies on the review's ticket, naming findings by number only (DESIGN §21).

    Only for a review of one of the loop's own PRs: its ticket's unit opened the PR.
    """
    conn = scenario.conn
    sha = head(git_pool)
    review_id = scenario.review(reviews(sha, ticket="PROJ-1"), reviewer=reviewer_reports(TWO_FINDINGS)).id
    query = reviews(sha, "https://github.com/acme/api/pull/9")
    query_id = scenario.review(query, reviewer=reviewer_reports(TWO_FINDINGS)).id
    ref = f"review:{review_id}"
    scenario.run(worker=pushes())

    # Inside a run, as its agent: not the operator's shell.
    with in_run(1):
        assert main(["send", ref, "1"]) == 1
        assert "send refused (inside_run)" in capsys.readouterr().err
    scenario.operator("dismiss", ref, "2")
    for args, guard in [
        ([ref, "3"], "unknown"),
        ([ref, "0"], "bad_finding"),
        ([ref, "2"], "dismissed"),
        (["review:99", "1"], "unknown"),
        # A PR review.query matched; and PROJ-1's own review, now that its unit has the PR its implement's worker
        # reported instead, as after a `canopy forget` and a new PR: no worker pushes to the reviewed one any more.
        ([f"review:{query_id}", "1"], "not_ours"),
        ([ref, "1"], "not_ours"),
        (["PROJ-1", "1"], "unsupported"),
    ]:
        assert f"send refused ({guard})" in scenario.operator("send", *args, code=1).err
    # Back on the PR the review read, its findings go to PROJ-1's worker.
    db.set_unit(conn, "PROJ-1", str(reviewing.root), "repo", pr_url=PR)
    scenario.operator("dismiss", ref, "2", "--undo")

    assert f"{ref} findings 1 went to PROJ-1 as message" in scenario.operator("send", ref, "1").out
    [message] = conversation.operator_messages_after(conn, "PROJ-1", 0)
    body = f"Address finding 1 of canopy's review run {review_id}, of commit {sha[:12]}. Leave its finding 2 alone."
    assert (message["body"], message["channel"]) == (body, "cli")
    # The reviewer's words stay data: the operator's message names the finding and never quotes it.
    assert "retry never stops" not in message["body"]
    # The same command again records nothing new.
    assert "already went to PROJ-1" in scenario.operator("send", ref, "1").out

    # The next tick reads it as the operator's go-ahead, and a resume for the review hears both.
    scenario.tick(*waits("PROJ-1"), dry_run=True)
    assert [m["body"] for m in scenario.ticket_state()["operator"]["new_operator_messages"]] == [body]
    command = resume(review_id, ResumeReason.REPLY, cursors={"message": str(message["id"])})
    prompt = scenario.run(command, worker=pushes()).prompt
    assert body in prompt
    assert "1. **blocking** `src/retry.py:42`: retry never stops" in prompt


def test_a_review_names_a_ticket_only_for_the_pr_its_unit_opened(
    reviewing: CanopyEnv, scenario: Scenario, git_pool: GitPool
) -> None:
    """A review's purpose is settled as it starts: `own` only for its ticket's unit's PR, else `query` (DESIGN §21)."""
    other = "https://github.com/acme/api/pull/8"
    sha = head(git_pool)
    assert scenario.refuses(reviews(sha, other, ticket="PROJ-1")) == [
        ("refused:not_ours", f"PROJ-1's unit in repo did not open {other}; --ticket is only for the loop's own PR")
    ]
    assert scenario.refuses(reviews(sha, ticket="PROJ-2")) == [
        ("refused:not_ours", f"PROJ-2's unit in repo did not open {PR}; --ticket is only for the loop's own PR")
    ]
    own = scenario.review(reviews(sha, ticket="PROJ-1"), reviewer=reviewer_reports(FINDINGS)).id
    query = scenario.review(reviews(sha, other), reviewer=reviewer_reports(FINDINGS)).id
    purposes = {r["id"]: r["purpose"] for r in scenario.conn.execute("SELECT id, purpose FROM review_runs")}
    assert purposes == {own: "own", query: "query"}
