"""Reviews (DESIGN §21, ROADMAP M11): a fresh reviewer per PR commit, guarded, in a slot it never works in."""

import json
import os
import re
import sys
import time
from pathlib import Path
from unittest import mock

import pytest
from syrupy.assertion import SnapshotAssertion

from canopy.cli.main import main
from canopy.core import (
    conversation,
    db,
    definitions,
    personas,
    prompts,
    records,
    review_answers,
    review_diff,
    review_runs,
    run_models,
    sql,
)
from canopy.core import review_result as result
from canopy.core.config import load
from canopy.core.context import Context
from canopy.core.vocab import DismissalReason, FindingAnswer, ResumeReason, RunKind, SeenKind
from canopy.infra import procs
from canopy.loop import attention
from canopy.reviews import grants, waiting
from canopy.serve import pr_list
from tests.canopy.helpers import (
    Called,
    InlineRunner,
    agent_runs,
    calls,
    decisions,
    granted_meanwhile,
    has_deadline,
    in_run,
    in_tick,
    lifelock_left,
    logged,
    messages,
    overseer_calls,
    personas_dir,
    pool_statuses,
    present,
    raises,
    tick_starts,
    ticket_sets,
    told,
    tools_of,
    waits,
    with_events,
)
from tests.canopy.review_helpers import (
    CLEAN,
    FINDINGS,
    PR,
    feature_commit,
    head,
    review_decisions,
    reviewer_reports,
)
from tests.canopy.scenario_helpers import Scenario, dispatches, pushes, review_waits, reviews
from tests.canopy.web_helpers import signed_in_client
from tests.conftest import CanopyEnv, GitPool, git


def test_with_reviews_off_nothing_about_them_reaches_the_overseer(scenario: Scenario) -> None:
    scenario.tick(*waits("PROJ-1"), dry_run=True)
    assert "reviews" not in scenario.state()
    [(action, _)] = scenario.refuses(reviews("a" * 40))
    assert action == "refused:reviews_off"


def test_max_reviews_zero_turns_reviews_off(reviewing: CanopyEnv, scenario: Scenario) -> None:
    scenario.configures(capacity={"max_reviews": 0})
    scenario.tick(*waits("PROJ-1"), dry_run=True)
    assert "reviews" not in scenario.state()


def test_a_review_runs_outside_the_checkout_at_the_commit(
    reviewing: CanopyEnv,
    git_pool: GitPool,
    treehouse_state: Path,
    agent_log: Path,
) -> None:
    """M11 against the fakes: the reviewer reads the checkout at the commit through a link, and the slot goes back."""
    conn = reviewing.journal()
    sha = head(git_pool)
    with (
        in_tick(conn) as tick_id,
        reviewer_reports(FINDINGS, ["git", "-C", "checkout", "rev-parse", "HEAD"], ["pwd"]),
    ):
        before = time.time()
        said = overseer_calls(reviews(sha, ticket="PROJ-1", context="Start with src/retry.py"))
        assert not said.error, said.text
        tick_starts()
        deadline = time.monotonic() + 30
        row = review_runs.get_review_run(conn, 1)
        while row is not None and row.status == "running" and time.monotonic() < deadline:
            time.sleep(0.05)
            row = review_runs.get_review_run(conn, 1)
        after = time.time()
        assert row is not None
        assert row.status == "done", Path(row.log_path).read_text()
        assert result.stored(row.result_json) == result.ReviewResult.model_validate(FINDINGS)
        assert (row.pr_url, row.sha, row.ticket_key) == (PR, sha, "PROJ-1")

        [reviewer] = agent_runs(agent_log)
        run_dir = reviewing.state_dir / "reviews" / "1"
        assert reviewer["cwd"] == str(run_dir)
        assert reviewer["argv"][:3] == ["run", "--agent", "canopy-reviewer"]
        assert "CANOPY_TICK_ID" not in reviewer["env"]
        assert has_deadline(reviewer, 20, before=before, after=after)  # the review's timeout (DESIGN §33)
        checked, _ = reviewer["commands"]
        assert checked["stdout"].strip() == sha
        assert not run_dir.exists()  # removed, and its link with it, once the run ended
        assert not lifelock_left(row)
        assert pool_statuses(treehouse_state) == ["available", "available"]
        [(ticket, pr, action, rationale)] = review_decisions(conn, tick_id)
        assert (ticket, pr, action) == ("PROJ-1", PR, "dispatch:review")
        assert rationale.startswith(f"review run 1: {sha} in ")
        assert rationale.endswith("; context=Start with src/retry.py")

        # Its fixed instructions are its agent's body, which ends with the contract; it is sent the run's own.
        prompt = told(reviewer)
        assert prompt.startswith("# canopy reviewer\n")
        assert reviewer["argv"][3].startswith("## Run\n\nThis is review 1 of at most ")
        assert f"- Checkout: `{run_dir / 'checkout'}`" in reviewer["argv"][3]
        assert "Post nothing anywhere" in prompt
        assert "canopy-review" not in prompt
        assert "None: never report `low`." in prompt
        assert prompt.index(result.CONTRACT) < prompt.index("\n## Run\n")


def test_a_review_hears_the_notice_in_force(reviewing: CanopyEnv, scenario: Scenario, git_pool: GitPool) -> None:
    # A review reads CI too, so the operator's notice about an outage reaches it (DESIGN §8, §21).
    scenario.operator("notice", "CI is down.")
    reviewed = scenario.review(reviews(head(git_pool)), reviewer=reviewer_reports(CLEAN))
    assert "## Notice from the operator\n\nCI is down.\n" in reviewed.prompt


def reviewer_instructions(scenario: Scenario, text: str | None) -> Path:
    """Point `paths.reviewer_instructions` at a file holding `text`, or at one that is not there for None."""
    path = scenario.env.user_file.parent / "reviewer-instructions.md"
    if text is not None:
        path.write_text(text)
    scenario.configures(paths={"reviewer_instructions": str(path)})
    return path


def test_the_operators_standing_instructions_reach_every_reviewer(
    reviewing: CanopyEnv,
    scenario: Scenario,
    git_pool: GitPool,
) -> None:
    rule = "A migration without a test that applies it is a finding."
    reviewer_instructions(scenario, f"\n{rule}\n\n")
    reviewed = scenario.review(reviews(head(git_pool)), reviewer=reviewer_reports(CLEAN))
    assert f"## Standing instructions from the operator\n\n{rule}\n\nThe operator set these" in reviewed.prompt


def test_reviewer_instructions_that_cannot_be_used_cost_the_pr_nothing(
    reviewing: CanopyEnv,
    scenario: Scenario,
    git_pool: GitPool,
    treehouse_state: Path,
) -> None:
    # The operator set them for every review; a review without them would judge as if they were never written.
    path = reviewer_instructions(scenario, None)
    [(action, reason)] = scenario.refuses(reviews(head(git_pool)))
    assert action == "refused:bad_prompt"
    assert reason.startswith(f"cannot read reviewer instructions {path}: ")
    assert scenario.conn.execute("SELECT count(*) FROM review_runs").fetchone()[0] == 0
    assert pool_statuses(treehouse_state) == ["available", "available"]


def test_a_review_runs_in_the_reviewers_persona_and_records_it(
    reviewing: CanopyEnv,
    scenario: Scenario,
    git_pool: GitPool,
    ctx: Context,
) -> None:
    # DESIGN §31: the reviewer's persona is the operator's choice in [personas], recorded on the run it reached.
    scenario.configures(personas={"reviewer": "skeptic"})
    skeptic = personas.load(load(reviewing.root, reviewing.user_file), "skeptic")
    reviewed = scenario.review(reviews(head(git_pool)), reviewer=reviewer_reports(CLEAN))
    assert f"## Persona\n\n{skeptic.text}\n" in reviewed.prompt
    assert (reviewed.row.persona, reviewed.row.persona_digest) == ("skeptic", skeptic.digest)
    assert db.persona_text(scenario.conn, skeptic.digest) == skeptic.text
    c, _ = signed_in_client(ctx)
    got = c.get(f"/api/reviews/{reviewed.id}").json()
    assert (got["persona"], got["persona_digest"]) == ("skeptic", skeptic.digest)


def test_reviews_share_their_reviewers_body_and_snapshot_and_are_sent_only_their_own(
    reviewing: CanopyEnv,
    scenario: Scenario,
    git_pool: GitPool,
    tmp_path: Path,
) -> None:
    # DESIGN §13: the fixed instructions are the reviewer's body, the same for every review, whatever its commit,
    # checkout, or round.
    first = scenario.review(reviews(head(git_pool)), reviewer=reviewer_reports(CLEAN))
    second = scenario.review(
        reviews(feature_commit(git_pool, tmp_path), ticket="PROJ-1"),
        reviewer=reviewer_reports(CLEAN),
    )
    runs = agent_runs(scenario.agent_log)
    assert len(runs) == 2
    assert runs[0]["env"]["OPENCODE_CONFIG_DIR"] == runs[1]["env"]["OPENCODE_CONFIG_DIR"]
    bodies = {prompts.split(r.prompt).body for r in (first, second)}
    assert len(bodies) == 1
    [body] = bodies
    assert body is not None
    for reviewed, run in zip((first, second), runs, strict=True):
        assert reviewed.row.sha not in body
        assert run["argv"][3] == prompts.split(reviewed.prompt).message
        assert f"- Commit: `{reviewed.row.sha}`" in run["argv"][3]


def test_a_tickets_reviewer_override_reaches_its_reviews_alone(
    reviewing: CanopyEnv,
    scenario: Scenario,
    git_pool: GitPool,
) -> None:
    # DESIGN §31: the operator's override for one ticket's reviewer, which a review of a PR with no ticket never takes.
    scenario.operator("persona", "PROJ-1", "skeptic", "--agent", "reviewer")
    no_ticket = scenario.review(reviews(head(git_pool)), reviewer=reviewer_reports(CLEAN))
    assert no_ticket.row.persona == "canopy"
    of_ticket = scenario.review(reviews("b" * 40, ticket="PROJ-1"), reviewer=reviewer_reports(CLEAN))
    assert of_ticket.row.persona == "skeptic"
    scenario.operator("persona", "PROJ-1", "--agent", "reviewer", "--clear")
    again = scenario.review(reviews("c" * 40, ticket="PROJ-1"), reviewer=reviewer_reports(CLEAN))
    assert again.row.persona == "canopy"


def test_a_review_whose_persona_has_no_file_costs_the_pr_nothing_and_asks_the_operator(
    reviewing: CanopyEnv,
    scenario: Scenario,
    git_pool: GitPool,
    treehouse_state: Path,
) -> None:
    yours = personas_dir(reviewing)
    scenario.configures(personas={"reviewer": "lenient"})
    reason = (
        f"[personas] reviewer: persona lenient has no file in {yours} or among canopy's own: add it, or name one "
        "`canopy personas` lists"
    )
    refused = scenario.refuses(reviews(head(git_pool), ticket="PROJ-1"))
    assert refused == [("refused:persona_missing", reason), ("attention:persona_missing", reason)]
    assert scenario.attention() == [("PROJ-1", "persona_missing")]
    assert scenario.conn.execute("SELECT count(*) FROM review_runs").fetchone()[0] == 0
    assert pool_statuses(treehouse_state) == ["available", "available"]


@pytest.mark.parametrize("instructed", [False, True])
def test_a_reviewer_override_without_the_placeholder_fails_closed_once_instructions_are_set(
    reviewing: CanopyEnv,
    scenario: Scenario,
    git_pool: GitPool,
    instructed: bool,  # noqa: FBT001  (a parametrized fixture)
) -> None:
    # An override written before the placeholder existed keeps serving an operator who sets no instructions.
    if instructed:
        reviewer_instructions(scenario, "Be brief.")
    overrides = reviewing.user_file.parent / "prompts"
    overrides.mkdir()
    (overrides / "reviewer.md").write_text("Review {{PR_URL}} at {{SHA}} in {{CHECKOUT}}.\n")
    if not instructed:
        assert scenario.review(reviews(head(git_pool)), reviewer=reviewer_reports(CLEAN)).status == "done"
        return
    [(action, reason)] = scenario.refuses(reviews(head(git_pool)))
    assert action == "refused:bad_prompt"
    assert reason.endswith("missing required placeholder {{STANDING_SECTION}} or {{STANDING_INSTRUCTIONS}}")


@pytest.mark.parametrize("full", [False, True], ids=["defaults", "every-value-set"])
def test_the_reviewer_prompt(
    reviewing: CanopyEnv,
    scenario: Scenario,
    git_pool: GitPool,
    markdown_snapshot: SnapshotAssertion,
    *,
    full: bool,
) -> None:
    """The reviewer's prompt, whole, so a change to its wording or to what fills it in is a diff in review.

    One with every value at its default, and one with each set: a ticket, the overseer's context, the operator's rule
    for `low`, a notice, standing instructions, and a limit of one review, which makes it the PR's last round.
    `git_pool` gives the review a pool to lease from; the run starts and never runs.
    """
    command = reviews("b" * 40)
    if full:
        scenario.configures(review={"low_impact": "A change to docs or tests only."}, policy={"max_reviews_per_pr": 1})
        scenario.operator("notice", "CI is down.")
        reviewer_instructions(scenario, "A migration without a test that applies it is a finding.\n")
        command = reviews("b" * 40, ticket="PROJ-1", context="Start with src/retry.py")
    with in_tick(scenario.conn):
        said = overseer_calls(command, runner=InlineRunner())
        assert not said.error, said.text
        tick_starts(InlineRunner())
    prompt = (reviewing.state_dir / "reviews" / "1.prompt").read_text()
    assert prompt.replace(str(reviewing.state_dir), "/state") == markdown_snapshot


@pytest.mark.parametrize(
    ("pr", "sha", "reason"),
    [
        ("http://x.test/pull/1", "a" * 40, "pr must be the PR's plain https:// URL"),
        (PR, "abc", "sha must be the full head commit"),
        (PR, "A" * 40, "sha must be the full head commit"),
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
        ("refused:reviewed", f"review run 1 already reviewed {sha[:12]} (clean, impact low); one review per commit"),
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
    reviewing: CanopyEnv,
    scenario: Scenario,
    git_pool: GitPool,
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

    # The state block shows a granted PR's grants beside its review runs. The other PR, of no ticket listed and found by
    # no review query, is left out: no decision rests on its review (#1528).
    scenario.tick(*waits("PROJ-1"), dry_run=True)
    prs = {p["url"]: p for p in scenario.state()["reviews"]["prs"]}
    assert (prs[PR]["review_runs"], prs[PR]["granted"]) == (2, 3)
    assert f"{PR}0" not in prs


def test_a_review_grant_reports_the_limit_of_its_own_transaction_whatever_grant_commits_beside_it(
    reviewing: CanopyEnv,
    scenario: Scenario,
    git_pool: GitPool,
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
    reviewing: CanopyEnv,
    scenario: Scenario,
    git_pool: GitPool,
    capsys: pytest.CaptureFixture[str],
    env: str,
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
    reviewing: CanopyEnv,
    scenario: Scenario,
    git_pool: GitPool,
) -> None:
    scenario.configures(capacity={"max_workers": 1, "max_reviews": 2})
    scenario.starts()
    assert scenario.refuses(reviews(head(git_pool), ticket="PROJ-1")) == [
        ("refused:running", "a worker run for PROJ-1 is running; review its PR once it ends"),
    ]
    assert scenario.refuses(reviews(head(git_pool), f"{PR}0")) == [
        ("refused:capacity", "1 of 1 workers, reviews, and tasks are running"),
    ]


def test_a_running_review_takes_worker_capacity(reviewing: CanopyEnv, scenario: Scenario, git_pool: GitPool) -> None:
    scenario.configures(capacity={"max_workers": 1})
    held = scenario.starts_review(reviews(head(git_pool)), reviewer=reviewer_reports(CLEAN))
    assert scenario.refuses(dispatches()) == [("refused:capacity", "1 of 1 workers are running")]
    assert held.finishes().status == "done"


def test_a_dry_run_counts_its_reviews(reviewing: CanopyEnv, scenario: Scenario) -> None:
    conn = scenario.conn
    with (
        mock.patch.object(procs.SubprocessRunner, "spawn", autospec=True) as spawn,
        scenario.ticking(dry_run=True) as tick_id,
    ):
        scenario.overseer(reviews("a" * 40))
        scenario.overseer(reviews("a" * 40), error=True)
        scenario.overseer(reviews("a" * 40, f"{PR}0"), error=True)
        assert [d[2:] for d in review_decisions(conn, tick_id)] == [
            ("dispatch:review", f"dry run: not dispatched; would review {'a' * 40}"),
            ("refused:running", "this dry run already reviewed this PR"),
            ("refused:review_capacity", "1 of 1 review runs are running"),
        ]
    assert not spawn.called
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
    reviewing: CanopyEnv,
    scenario: Scenario,
    git_pool: GitPool,
    report: dict[str, object],
    status: str,
    note: str,
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
    reviewing: CanopyEnv,
    scenario: Scenario,
    git_pool: GitPool,
    *,
    events: bool,
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
    titles = {r.url: r.pr_title for r in pr_list.pull_requests(scenario.conn, 10)}
    assert titles == {PR: "Retry the queue", f"{PR}0": None}  # on one line


def test_links_out_of_the_checkout_are_removed_before_the_reviewer_reads_it(
    reviewing: CanopyEnv,
    scenario: Scenario,
    git_pool: GitPool,
    tmp_path: Path,
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
    scenario.overseer(ticket_sets("PROJ-1", repo="repo", phase=phase))
    [unit] = db.units(scenario.conn, "PROJ-1")
    assert unit.phase == phase


def test_a_commit_origin_does_not_have_fails_the_review(
    reviewing: CanopyEnv,
    scenario: Scenario,
    git_pool: GitPool,
    treehouse_state: Path,
) -> None:
    """A PR of another repository fails here: its commit cannot be fetched from this one's origin."""
    row = scenario.review(reviews("d" * 40)).row
    assert row.status == "failed"
    assert json.loads(row.result_json or "{}")["harness"].startswith("git fetch failed: ")
    assert not scenario.agent_log.exists()  # the reviewer never ran
    assert pool_statuses(treehouse_state) == ["available", "available"]


def test_a_killed_review_is_crashed_on_the_next_tick(
    reviewing: CanopyEnv,
    scenario: Scenario,
    git_pool: GitPool,
    treehouse_state: Path,
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
    reviewing: CanopyEnv,
    scenario: Scenario,
    git_pool: GitPool,
    treehouse_state: Path,
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
    # What is null or empty, such as the query, the running reviews, and the settling heads, is left out.
    assert section["agent_prs"] is True
    assert "query" not in section
    assert section["limits"] == {
        "max_reviews": 1,
        "max_reviews_per_day": 20,
        "max_reviews_per_pr": 3,
        "settle_minutes": 0,
        "started_last_24h": 1,
    }
    assert "running" not in section
    # With settling off, no head is recorded.
    assert "settling" not in section
    [reviewed] = section["prs"]
    # The PR is PROJ-1's unit's, so it is named by its ticket and repository, its URL being the unit's `pr_url`.
    assert "url" not in reviewed
    assert (reviewed["ticket"], reviewed["repo"], reviewed["review_runs"]) == ("PROJ-1", "repo", 1)
    latest = reviewed["latest"]
    assert (latest["status"], latest["verdict"], latest["impact"]) == ("done", "findings", "normal")
    assert latest["findings"] == ["retry never stops"]
    # The run took its journal number when it ended: the overseer passes it as the unit's review cursor.
    assert latest["number"] is not None
    scenario.overseer(ticket_sets("PROJ-1", repo="repo", cursors={"review": str(latest["number"])}))
    assert "comment" not in latest


def test_attention_about_a_pr_without_a_ticket(reviewing: CanopyEnv, scenario: Scenario) -> None:
    scenario.tick(
        raises(None, "flaky_rerun", "build failed again on rerun", pr=PR),
        *waits("PROJ-1"),
    )
    conn = scenario.conn
    assert [(i.subject, i.reason, i.detail) for i in attention.current(conn)] == [
        (f"pr:{PR}", "flaky_rerun", "build failed again on rerun"),
    ]
    assert f"pr:{PR}  attention:flaky_rerun" in scenario.operator("decisions").out
    with scenario.ticking() as tick_id:
        unnamed = scenario.overseer(raises(None, "flaky_rerun", "x"), error=True)
        assert "key or pr is required" in unnamed.text
        plain = scenario.overseer(raises(None, "flaky_rerun", "x", pr="http://plain"), error=True)
        assert "pr: must be a plain https:// URL" in plain.text
    assert review_decisions(conn, tick_id) == []


def test_review_wait_records_a_plain_pr_url_and_refuses_anything_else(reviewing: CanopyEnv, scenario: Scenario) -> None:
    conn = scenario.conn
    with scenario.ticking() as tick_id:
        for bad in ("http://x.test/pull/1", "javascript:alert(1)", f"{PR}/{'x' * 300}"):
            refused = scenario.overseer(review_waits(bad, "draft"), error=True)
            assert "pr: must be a plain https:// URL" in refused.text
        assert review_decisions(conn, tick_id) == []
        scenario.overseer(review_waits(PR, "draft"))
        assert review_decisions(conn, tick_id) == [(None, PR, "wait", "draft")]


def test_a_sink_that_takes_reviews_hears_when_one_ends(
    reviewing: CanopyEnv,
    scenario: Scenario,
    git_pool: GitPool,
    sink_script: Path,
    tmp_path: Path,
) -> None:
    out = tmp_path / "sink.txt"
    scenario.configures(
        notify={"sinks": {"s": {"cmd": f"{sink_script} {out}", "format": "text", "events": ["reviews"]}}},
    )
    scenario.tick(*waits("PROJ-1"))
    scenario.review(reviews(head(git_pool), ticket="PROJ-1"), reviewer=reviewer_reports(FINDINGS))
    scenario.tick(*waits("PROJ-1"))
    [message] = messages(out)
    assert f"< review run 1 of {PR} (PROJ-1) ended done: findings normal (1 findings)\n" in message


def test_a_reviewer_prompt_that_does_not_render_costs_the_pr_nothing(
    reviewing: CanopyEnv,
    scenario: Scenario,
    git_pool: GitPool,
    treehouse_state: Path,
) -> None:
    overrides = reviewing.user_file.parent / "prompts"
    overrides.mkdir()
    (overrides / "reviewer.md").write_text("Review {{PR_URL}}\n")
    [(action, reason)] = scenario.refuses(reviews(head(git_pool)))
    assert action == "refused:bad_prompt"
    assert reason.endswith("missing required placeholder {{SHA}}, {{CHECKOUT}}")
    assert scenario.conn.execute("SELECT count(*) FROM review_runs").fetchone()[0] == 0
    assert pool_statuses(treehouse_state) == ["available", "available"]


def test_a_review_run_records_what_it_cost(
    reviewing: CanopyEnv,
    scenario: Scenario,
    git_pool: GitPool,
    opencode_state: Path,
) -> None:
    """With OpenCode's JSON events, as the default `review_cmd` asks for, a review run records its session and cost."""
    opencode_state.write_text(json.dumps({"sessions": {"ses_review": [["anthropic", "claude-x", 0.25]]}}))
    with_events(reviewing, "canopy-reviewer")
    reviewer = reviewer_reports(FINDINGS, ["echo", "read it"], session="ses_review")
    reviewed = scenario.review(reviews(head(git_pool)), reviewer=reviewer)
    conn, row, run_id = scenario.conn, reviewed.row, reviewed.id
    assert row.status == "done", reviewed.printed.out  # the result line is read from the text events
    assert row.session_id == "ses_review"
    usage = present(db.usage_of(row))
    assert usage.cost_usd == 0.25  # two model calls at 0.125
    assert (usage.first_call, usage.first_cache_write, usage.first_cache_read) == (5500, 500, 4000)
    assert (reviewing.state_dir / definitions.RUNTIME_DIR / row.definitions_digest).is_dir()
    assert db.spent_since(conn, "2000-01-01T00:00:00Z") == 0.25
    assert tools_of(conn, "review_runs", run_id) == [("bash", 1, 0, len("read it\n"))]
    # Which models served it, read from its session as it ended (DESIGN §13).
    assert [(m.model, m.replies) for m in run_models.of_run(conn, "review_runs", run_id)] == [("anthropic/claude-x", 1)]


def test_a_running_review_shows_its_session_and_spend_so_far(
    reviewing: CanopyEnv,
    scenario: Scenario,
    git_pool: GitPool,
) -> None:
    """What the reviewer reports is on its row as it prints it, so its page shows it mid-review."""
    with_events(reviewing, "canopy-reviewer")
    journal = reviewing.state_dir / db.DB_FILE_NAME
    # canopy records each event as it reads it, a moment after the reviewer printed it: wait for the cost to land.
    read_row = (
        "import sqlite3, sys, time\n"
        "deadline = time.monotonic() + 10\n"
        "while True:\n"
        "    rows = sqlite3.connect(sys.argv[1]).execute(sys.argv[2]).fetchall()\n"
        "    if (rows and rows[0][1] is not None) or time.monotonic() > deadline:\n"
        "        break\n"
        "    time.sleep(0.05)\n"
        "print(rows)"
    )
    row_now = [sys.executable, "-c", read_row, str(journal), "SELECT session_id, cost_usd FROM review_runs"]
    reviewer = reviewer_reports(FINDINGS, row_now, session="ses_review")
    reviewed = scenario.review(reviews(head(git_pool)), reviewer=reviewer)
    assert reviewed.status == "done", reviewed.printed.out

    [run] = agent_runs(scenario.agent_log)
    commands = run["commands"]
    assert isinstance(commands, list)
    [shown] = commands
    # The first of its two model calls has ended, before it ran its command.
    assert shown["stdout"] == "[('ses_review', 0.125)]\n"
    # Once it ends, its row has its whole report, and its log what it printed in the same shape as ever.
    assert (reviewed.row.session_id, reviewed.row.cost_usd) == ("ses_review", 0.25)
    out = reviewed.printed.out
    assert re.search(r"--- reviewer stdout ---\n(\{.*\}\n)+\n--- reviewer stderr ---\n\n--- reviewer exit 0 ---\n", out)


def test_a_timed_out_review_records_what_it_reported_before_the_kill(
    reviewing: CanopyEnv,
    scenario: Scenario,
    git_pool: GitPool,
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
) -> Called:
    """The overseer dispatches a `resume` of PROJ-1 for review feedback, and for `reasons` besides (DESIGN §8)."""
    return dispatches(
        kind=RunKind.RESUME,
        reasons=[ResumeReason.REVIEW, *reasons],
        review_run=review_run,
        cursors=cursors,
        context=context,
    )


def test_a_resume_for_a_review_carries_its_findings_from_the_journal(
    reviewing: CanopyEnv,
    scenario: Scenario,
    git_pool: GitPool,
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


def test_a_resume_without_a_review_has_no_section_for_one(
    reviewing: CanopyEnv,
    scenario: Scenario,
    git_pool: GitPool,
) -> None:
    scenario.run(worker=pushes())
    assert "## canopy's review" not in scenario.run(resume(), worker=pushes()).prompt


def test_a_review_run_goes_only_to_a_resume_of_its_own_ticket(
    reviewing: CanopyEnv,
    scenario: Scenario,
    git_pool: GitPool,
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
            "review_run names findings for a resume to address; it is for resume only",
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
    # New to the operator until they read it in full (DESIGN §22).
    assert line.endswith(f"  done  findings, 1 findings, impact normal  {PR} @ {sha[:7]}  in canopy  new")
    shown = scenario.operator("review", "show", str(run_id)).out
    assert shown.startswith(f"review run {run_id} of {PR} (PROJ-1) at {sha}, in canopy\ndone, started ")
    assert "\x1b" not in shown
    assert "verdict findings, impact normal\n\nOne blocking defect. [2J\n\n1. **blocking** `src/retry.py:42`" in shown
    scenario.operator("review", "show", "99", code=1)
    assert scenario.operator("review", "show").out.endswith(f"{PR} @ {sha[:7]}  in canopy\n")


def test_a_review_keeps_its_commits_diff_for_the_web_ui(
    reviewing: CanopyEnv,
    scenario: Scenario,
    git_pool: GitPool,
    tmp_path: Path,
) -> None:
    """The diff against where the commit leaves the pool's base branch, for a PR not yet read (DESIGN §21)."""
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
    reviewing: CanopyEnv,
    scenario: Scenario,
    git_pool: GitPool,
    tmp_path: Path,
) -> None:
    """The diff is for the page only: a base origin no longer has leaves the review as it was, without one."""
    sha = feature_commit(git_pool, tmp_path)
    git("update-ref", "-d", "refs/heads/main", cwd=git_pool.origin)
    reviewed = scenario.review(reviews(sha), reviewer=reviewer_reports(FINDINGS))
    assert reviewed.status == "done", reviewed.printed.out
    assert not review_diff.path_for(reviewed.row.log_path).exists()


def test_a_review_of_a_stacked_pr_runs_from_the_branch_it_merges_into(
    reviewing: CanopyEnv,
    scenario: Scenario,
    git_pool: GitPool,
    tmp_path: Path,
) -> None:
    """The base is the PR's own, as the reader last read it, not the pool's: a stacked PR's diff is its own commits."""
    parent = feature_commit(git_pool, tmp_path)
    seed = tmp_path / "seed"
    git("checkout", "--quiet", "-b", "stacked", cwd=seed)
    (seed / "backoff.py").write_text("sleep(1)\n")
    git("add", "backoff.py", cwd=seed)
    git("commit", "--quiet", "-m", "backoff", cwd=seed)
    git("push", "--quiet", str(git_pool.origin), "stacked", cwd=seed)
    sha = present(git_pool.remote_head("stacked"))
    records.insert(
        records.ObservedPr,
        url=PR,
        repository="acme/api",
        number=7,
        head_sha=sha,
        base_ref="feature",
        draft=False,
        observed_at=db.now(),
        labels="[]",
    ).run(scenario.conn)
    reads = [calls("canopy_git_merge-base", base="origin/feature", head="HEAD")]
    reviewed = scenario.review(reviews(sha), reviewer=reviewer_reports(CLEAN, tools=reads))
    assert (reviewed.status, reviewed.row.base_branch) == ("done", "feature"), reviewed.printed.out
    [changed] = present(review_diff.read(review_diff.path_for(reviewed.row.log_path))).files
    assert changed.path == "backoff.py"
    assert "- Base: `feature`" in reviewed.prompt
    [reviewer] = agent_runs(scenario.agent_log)
    [fork] = reviewer["tools"]
    assert (fork["error"], fork["text"]) == (False, parent)


def test_a_reviewer_reads_its_checkouts_history_through_canopys_git_tools(
    reviewing: CanopyEnv,
    scenario: Scenario,
    git_pool: GitPool,
    tmp_path: Path,
) -> None:
    """#1130: the reviewer has no shell; canopy's read-only git tools, over its own checkout alone, read its history."""
    sha = feature_commit(git_pool, tmp_path)
    reads = [
        calls("canopy_git_merge-base", base="origin/main", head="HEAD"),
        calls("canopy_git_diff", base="origin/main", head=sha, paths=["retry.py"]),
        calls("canopy_git_log", range=f"origin/main..{sha}", limit=5),
        calls("canopy_git_show", rev="origin/main", path="."),
        calls("canopy_git_show", rev=sha, path="../../../../etc/passwd"),
        calls("canopy_git_diff", base="--output=/tmp/x", head=sha),
    ]
    reviewed = scenario.review(reviews(sha), reviewer=reviewer_reports(CLEAN, tools=reads))
    assert reviewed.status == "done", reviewed.printed.out

    [reviewer] = agent_runs(scenario.agent_log)
    slot = Path(present(reviewed.row.slot_path))
    entry = json.loads(reviewer["env"]["OPENCODE_CONFIG_CONTENT"])["mcp"]["canopy_git"]
    assert entry["command"][-3:] == ["_mcp", "--git", f"checkout={slot}"]
    assert reviewer["env"]["OPENCODE_EXPERIMENTAL_CODE_MODE"] == "false"
    fork, diff, log, root, escape, option = reviewer["tools"]
    assert [call["error"] for call in (fork, diff, log, root)] == [False] * 4, [fork, diff, log, root]
    assert fork["text"] == head(git_pool)
    assert "+while True:\n+    call()" in diff["text"]
    [commit] = logged(log["text"]).commits
    assert (commit.commit, [(f.status, f.path) for f in commit.files]) == (sha, [("A", "retry.py")])
    assert root["text"] == "Nothing at . in origin/main."
    assert (escape["error"], option["error"]) == (True, True)
    assert "no `..`" in escape["text"]
    assert "base: not a revision" in option["text"]
    assert "Your git tools, `canopy_git_merge-base`" in reviewed.prompt


TWO_FINDINGS = {
    **FINDINGS,
    "findings": [
        *FINDINGS["findings"],
        {"severity": "minor", "title": "log line is noisy", "location": "src/retry.py:7", "detail": "It logs twice."},
    ],
}


def test_a_dismissed_finding_reaches_no_worker_and_no_tick(
    reviewing: CanopyEnv,
    scenario: Scenario,
    git_pool: GitPool,
    capsys: pytest.CaptureFixture[str],
) -> None:
    conn = scenario.conn
    review_id = scenario.review(reviews(head(git_pool), ticket="PROJ-1"), reviewer=reviewer_reports(TWO_FINDINGS)).id
    ref = f"review:{review_id}"

    # Only the operator dismisses, and only a finding the review has.
    with mock.patch.dict(os.environ, {"CANOPY_TICK_ID": "1"}):
        assert main(["dismiss", ref, "2", "--reason", "wrong"]) == 1
        assert "dismiss refused (inside_run)" in capsys.readouterr().err
    wrong = ("--reason", "wrong")
    for args, guard in [
        ([ref, "3", *wrong], "unknown"),
        ([ref, "0", *wrong], "bad_finding"),
        ([ref, "two", *wrong], "bad_finding"),
        (["review:99", "1", *wrong], "unknown"),
        (["review:x", "1", *wrong], "bad_ref"),
        ([ref, "2", "--undo"], "unknown"),
        ([ref, "2", "3", *wrong], "unknown"),
        ([ref, "2", "two", *wrong], "bad_finding"),
        # A review's dismissal says why, and taking one back says nothing.
        ([ref, "2"], "bad_reason"),
        ([ref, "2", "--undo", *wrong], "bad_reason"),
    ]:
        assert f"dismiss refused ({guard})" in scenario.operator("dismiss", *args, code=1).err
    # Several are dismissed together or not at all.
    assert review_runs.review_dismissals(conn, review_id) == {}

    dismissed = scenario.operator("dismiss", ref, "2", "--reason", "not_worth_it")
    assert f"{ref} finding 2 is dismissed as not_worth_it: no worker or tick acts on it." in dismissed.out
    shown = scenario.operator("review", "show", str(review_id)).out
    assert "2. **minor** `src/retry.py:7`: log line is noisy (dismissed: not_worth_it)" in shown
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
    both = scenario.operator("dismiss", ref, "2", "1", "--reason", "intentional")
    assert f"{ref} findings 2, 1 are dismissed as intentional: no worker or tick acts on them." in both.out
    assert scenario.refuses(resume(review_id)) == [
        (
            "refused:bad_review",
            f"the operator dismissed every finding of review run {review_id}: none is left to address",
        ),
    ]

    # Undo hands it back.
    undone = scenario.operator("dismiss", ref, "1", "--undo")
    assert "is no longer dismissed: a resume hands it to the worker again." in undone.out
    # Dismissing one again records the reason anew.
    assert review_runs.review_dismissals(conn, review_id) == {2: DismissalReason.INTENTIONAL}
    # One that holds and is worth fixing, but in another PR.
    later = scenario.operator("dismiss", ref, "1", "--reason", "out_of_scope")
    assert f"{ref} finding 1 is dismissed as out_of_scope: no worker or tick acts on it." in later.out
    assert review_runs.review_dismissals(conn, review_id) == {
        1: DismissalReason.OUT_OF_SCOPE,
        2: DismissalReason.INTENTIONAL,
    }


def test_review_noise_counts_findings_by_severity_persona_and_model_and_why_each_was_dismissed(
    reviewing: CanopyEnv,
    scenario: Scenario,
    git_pool: GitPool,
    opencode_state: Path,
) -> None:
    """`canopy review noise` reads the reviewer's noise from the operator's dismissals: `wrong` ones (DESIGN §21).

    An `out_of_scope` one held, so it counts in its own column and not in the `wrong` rate.
    """
    nothing = scenario.operator("review", "noise").out
    assert nothing.startswith("0 done reviews since ")
    assert nothing.endswith(": no findings.\n")
    opencode_state.write_text(json.dumps({"sessions": {"ses_review": [["anthropic", "claude-x", 0.25]]}}))
    with_events(reviewing, "canopy-reviewer")
    elsewhere = {**TWO_FINDINGS["findings"][1], "title": "rename the module"}
    four = {
        **TWO_FINDINGS,
        "findings": [*TWO_FINDINGS["findings"], {**FINDINGS["findings"][0], "title": "again"}, elsewhere],
    }
    reviewed = scenario.review(reviews(head(git_pool)), reviewer=reviewer_reports(four, session="ses_review"))
    ref = f"review:{reviewed.id}"
    scenario.operator("dismiss", ref, "1", "--reason", "wrong")
    scenario.operator("dismiss", ref, "2", "--reason", "not_worth_it")
    scenario.operator("dismiss", ref, "3", "--reason", "intentional")
    scenario.operator("dismiss", ref, "4", "--reason", "out_of_scope")
    # As a dismissal from before canopy asked why.
    records.update(records.ReviewDismissal).set(reason=None).where("finding = ?", 3).run(scenario.conn)

    found = json.loads(scenario.operator("review", "noise", "--json").out)
    assert found["reviews"] == 1
    assert found["severity"] == [
        {
            "key": "blocking",
            "findings": 2,
            "dismissed": {"wrong": 1, "unrecorded": 1},
            "answered": {},
            "rebuttals": 0,
            "rates": {
                "wrong": 0.5,
                "intentional": 0.0,
                "not_worth_it": 0.0,
                "out_of_scope": 0.0,
                "fixed": 0.0,
                "declined": 0.0,
            },
        },
        {
            "key": "minor",
            "findings": 2,
            "dismissed": {"not_worth_it": 1, "out_of_scope": 1},
            "answered": {},
            "rebuttals": 0,
            "rates": {
                "wrong": 0.0,
                "intentional": 0.0,
                "not_worth_it": 0.5,
                "out_of_scope": 0.5,
                "fixed": 0.0,
                "declined": 0.0,
            },
        },
    ]
    assert [(g["key"], g["findings"], g["dismissed"]) for g in found["persona"]] == [
        (reviewed.row.persona, 4, {"wrong": 1, "not_worth_it": 1, "out_of_scope": 1, "unrecorded": 1}),
    ]
    assert [g["key"] for g in found["model"]] == ["anthropic/claude-x"]
    text = scenario.operator("review", "noise").out.splitlines()
    assert text[2:5] == [
        (
            "severity  findings  wrong  intentional  not_worth_it  out_of_scope  unrecorded  fixed  declined  rebuttals"
            "  wrong rate"
        ),
        (
            "blocking         2      1            0             0             0           1      0         0          0"
            "         50%"
        ),
        (
            "minor            2      0            0             1             1           0      0         0          0"
            "          0%"
        ),
    ]


def previous_review(prompt: str) -> str:
    """The `## The previous review` section of a reviewer's prompt, its framing left out."""
    return prompt.split("## The previous review\n\n", 1)[1].split("\n\nThis is canopy's own last review", 1)[0]


def test_a_later_review_reads_the_prs_last_done_review_less_what_the_operator_dismissed(
    reviewing: CanopyEnv,
    scenario: Scenario,
    git_pool: GitPool,
) -> None:
    sha = head(git_pool)
    first = scenario.review(reviews(sha, ticket="PROJ-1"), reviewer=reviewer_reports(TWO_FINDINGS))
    # A PR's first review has none, so its prompt has no section for one.
    assert "## The previous review" not in first.prompt
    scenario.operator("dismiss", f"review:{first.id}", "2", "--reason", "wrong")
    # Another PR's review reaches none of this PR's.
    other = scenario.review(reviews(sha, f"{PR}0"), reviewer=reviewer_reports(CLEAN))
    assert "## The previous review" not in other.prompt

    # A commit origin does not have: the run fails, so the next review still reads the first.
    second = scenario.review(reviews("b" * 40, ticket="PROJ-1"), reviewer=reviewer_reports(CLEAN))
    third = scenario.review(reviews("c" * 40, ticket="PROJ-1"), reviewer=reviewer_reports(CLEAN))
    assert second.status == third.status == "failed"
    expected = (
        f"canopy's review run {first.id} of this PR, at commit `{sha}`, ended with verdict findings, impact normal.\n"
        "\n"
        "Its summary:\n"
        f"> {FINDINGS['summary']}\n"
        "\n"
        "Its findings:\n"
        "1. **blocking** `src/retry.py:42`: retry never stops\n"
        "   > The loop resets attempts on every error.\n"
        "   > A failing call retries forever."
    )
    assert previous_review(second.prompt) == previous_review(third.prompt) == expected

    scenario.operator("dismiss", f"review:{first.id}", "1", "--reason", "wrong")
    scenario.operator("grant", PR, "review")
    fourth = scenario.review(reviews("d" * 40, ticket="PROJ-1"), reviewer=reviewer_reports(CLEAN))
    assert previous_review(fourth.prompt) == (
        f"canopy's review run {first.id} of this PR, at commit `{sha}`, ended with verdict findings, impact normal.\n"
        "\n"
        "Its summary:\n"
        f"> {FINDINGS['summary']}\n"
        "\n"
        "Its findings: none the operator kept."
    )


def test_a_reviewer_override_without_the_previous_review_serves_only_a_prs_first_review(
    reviewing: CanopyEnv,
    scenario: Scenario,
    git_pool: GitPool,
) -> None:
    overrides = reviewing.user_file.parent / "prompts"
    overrides.mkdir()
    (overrides / "reviewer.md").write_text("Review {{PR_URL}} at {{SHA}} in {{CHECKOUT}}.\n")
    assert scenario.review(reviews(head(git_pool)), reviewer=reviewer_reports(CLEAN)).status == "done"
    [(action, reason)] = scenario.refuses(reviews("b" * 40))
    assert action == "refused:bad_prompt"
    assert reason.endswith("missing required placeholder {{PREVIOUS_REVIEW}}")


def test_findings_sent_to_a_worker_reach_its_ticket_as_the_operators_go_ahead(
    reviewing: CanopyEnv,
    scenario: Scenario,
    git_pool: GitPool,
    capsys: pytest.CaptureFixture[str],
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
    scenario.operator("dismiss", ref, "2", "--reason", "wrong")
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
    assert (message.body, message.channel) == (body, "cli")
    # The reviewer's words stay data: the operator's message names the finding and never quotes it.
    assert "retry never stops" not in message.body
    # The same command again records nothing new.
    assert "already went to PROJ-1" in scenario.operator("send", ref, "1").out

    # The next tick reads it as the operator's go-ahead, and a resume for the review hears both.
    scenario.tick(*waits("PROJ-1"), dry_run=True)
    assert [m["body"] for m in scenario.ticket_state()["operator"]["new_operator_messages"]] == [body]
    command = resume(review_id, ResumeReason.REPLY, cursors={"message": str(message.id)})
    prompt = scenario.run(command, worker=pushes()).prompt
    assert body in prompt
    assert "1. **blocking** `src/retry.py:42`: retry never stops" in prompt


#: What a resumed worker answers of TWO_FINDINGS, with entries `_run` refuses after the two it keeps.
DECLINED = "It logs once per attempt, which the runbook asks for."


def answers_to(review_id: int) -> list[dict[str, object]]:
    """A worker's `review_answers` for review run `review_id`: 1 fixed, 2 declined, and three it may not give."""
    return [
        {"review": review_id, "finding": 1, "answer": "fixed"},
        {"review": review_id, "finding": 2, "answer": "declined", "reason": DECLINED},
        {"review": review_id, "finding": 3, "answer": "fixed"},
        {"review": 99, "finding": 1, "answer": "fixed"},
        {"review": review_id, "finding": 1, "answer": "declined"},
        {"review": review_id, "finding": 1, "answer": ["fixed"]},
    ]


def test_a_declined_finding_reaches_the_next_review_and_its_rebuttal_waits_on_the_operator(
    reviewing: CanopyEnv,
    scenario: Scenario,
    git_pool: GitPool,
) -> None:
    """A worker answers each finding; a rebuttal of a decline is held for the operator, never resumed (DESIGN §21)."""
    # canopy's reviewer is trusted, so its findings go to a worker on its own word, but a rebuttal's never does.
    scenario.configures("private", trust={"trusted_reviewers": ["canopy:review"]})
    conn = scenario.conn
    first = scenario.review(reviews(head(git_pool), ticket="PROJ-1"), reviewer=reviewer_reports(TWO_FINDINGS)).id
    scenario.run(worker=pushes())

    # The resume is asked for an answer to each finding, and the answers `_run` can check are kept.
    ran = scenario.run(resume(first), worker=pushes(review_answers=answers_to(first)))
    assert '"review_answers":[{"review":<review run id>' in ran.prompt
    answered = review_answers.latest(conn, first)
    assert [(n, a.answer, a.reason) for n, a in answered.items()] == [
        (1, FindingAnswer.FIXED, None),
        (2, FindingAnswer.DECLINED, DECLINED),
    ]
    note = json.loads(ran.row["result_json"])["harness"]
    assert note == (
        f"review answers not recorded: entry 3: review run {first} has no finding 3; entry 4: review run 99 is not a "
        "done review of PROJ-1; entry 5: a decline gives no reason; entry 6: `answer` is not fixed or declined"
    )

    # The next review reads them: it rebuts the decline, and repeats the fix's finding, which it may not rebut.
    rebuttal = {
        **FINDINGS,
        "findings": [
            {**TWO_FINDINGS["findings"][1], "detail": "The runbook asks for one line, not two.", "rebuts": 2},
            {**TWO_FINDINGS["findings"][0], "rebuts": 1},
        ],
    }
    sha = present(git_pool.remote_head("agent/PROJ-1-work"))
    # The PR the reviews read is the one PROJ-1's unit opened.
    db.set_unit(conn, "PROJ-1", str(reviewing.root), "repo", pr_url=PR)
    second = scenario.review(reviews(sha, ticket="PROJ-1"), reviewer=reviewer_reports(rebuttal))
    assert previous_review(second.prompt).endswith(
        "1. **blocking** `src/retry.py:42`: retry never stops\n"
        "   > The loop resets attempts on every error.\n"
        "   > A failing call retries forever.\n"
        "   The author's answer: fixed.\n"
        "2. **minor** `src/retry.py:7`: log line is noisy\n"
        "   > It logs twice.\n"
        "   The author's answer: declined:\n"
        f"   > {DECLINED}",
    )
    assert set(review_runs.held(conn, second.id)) == {1}
    held = f"(held for the operator: it rebuts the author's decline of finding 2 of review run {first})"
    assert (
        f"1. **minor** `src/retry.py:7`: log line is noisy {held}"
        in scenario.operator(
            "review",
            "show",
            str(second.id),
        ).out
    )

    # Neither the overseer nor a worker acts on the held one; the operator hears of it.
    [item] = waiting.items(conn)
    assert (item.ticket, item.reason) == ("PROJ-1", waiting.REBUTTAL_REASON)
    assert item.detail.startswith(
        f"review:{second.id} finding 1 rebuts the worker's decline of review:{first} finding 2",
    )
    scenario.tick(*waits("PROJ-1"), dry_run=True)
    latest = scenario.state()["reviews"]["prs"][0]["latest"]
    assert (latest["findings"], latest["held_findings"]) == (["retry never stops"], 1)
    prompt = scenario.run(resume(second.id), worker=pushes()).prompt
    assert "2. **blocking** `src/retry.py:42`: retry never stops" in prompt
    assert "log line is noisy" not in prompt

    # Sent, it is the operator's go-ahead, and a resume hands it on; the item is gone. The worker reported its own PR
    # again, so the unit is put back on the reviewed one.
    db.set_unit(conn, "PROJ-1", str(reviewing.root), "repo", pr_url=PR)
    scenario.operator("send", f"review:{second.id}", "1")
    assert review_runs.held(conn, second.id) == {}
    assert waiting.items(conn) == []
    assert "1. **minor** `src/retry.py:7`: log line is noisy" in scenario.run(resume(second.id), worker=pushes()).prompt


@pytest.mark.usefixtures("reviewing")
def test_a_later_resume_answering_one_finding_keeps_an_earlier_resumes_answer_to_another(
    scenario: Scenario,
    git_pool: GitPool,
) -> None:
    """Each finding keeps its own latest answer, so a later resume of one finding hides no earlier decline (§21)."""
    conn = scenario.conn
    first = scenario.review(reviews(head(git_pool), ticket="PROJ-1"), reviewer=reviewer_reports(TWO_FINDINGS)).id
    scenario.run(worker=pushes())
    scenario.run(resume(first), worker=pushes(review_answers=answers_to(first)))
    # A second resume of the same review answers finding 1 alone, as when the operator sent it after the first.
    later = [{"review": first, "finding": 1, "answer": "declined", "reason": "The loop is bounded upstream."}]
    scenario.run(resume(first), worker=pushes(review_answers=later))

    answered = review_answers.latest(conn, first)
    assert [(n, a.answer, a.reason) for n, a in sorted(answered.items())] == [
        (1, FindingAnswer.DECLINED, "The loop is bounded upstream."),
        (2, FindingAnswer.DECLINED, DECLINED),
    ]


def test_review_noise_counts_what_workers_answered_of_the_findings_not_dismissed_and_the_rebuttals(
    reviewing: CanopyEnv,
    scenario: Scenario,
    git_pool: GitPool,
) -> None:
    """`canopy review noise` counts a worker's latest answer to each finding, the operator's dismissal first (§21)."""
    conn = scenario.conn
    three = {**TWO_FINDINGS, "findings": [*TWO_FINDINGS["findings"], {**FINDINGS["findings"][0], "title": "again"}]}
    first = scenario.review(reviews(head(git_pool), ticket="PROJ-1"), reviewer=reviewer_reports(three)).id
    scenario.run(worker=pushes())
    answers = [
        {"review": first, "finding": 1, "answer": "fixed"},
        {"review": first, "finding": 2, "answer": "declined", "reason": DECLINED},
        {"review": first, "finding": 3, "answer": "fixed"},
    ]
    scenario.run(resume(first), worker=pushes(review_answers=answers))
    # The operator's word on finding 3 wins over the worker's.
    scenario.operator("dismiss", f"review:{first}", "3", "--reason", "wrong")
    # The next review rebuts the decline, and the harness holds it; released, it still counts as a rebuttal.
    rebuttal = {**FINDINGS, "findings": [{**TWO_FINDINGS["findings"][1], "rebuts": 2}]}
    db.set_unit(conn, "PROJ-1", str(reviewing.root), "repo", pr_url=PR)
    sha = present(git_pool.remote_head("agent/PROJ-1-work"))
    second = scenario.review(reviews(sha, ticket="PROJ-1"), reviewer=reviewer_reports(rebuttal)).id
    assert set(review_runs.held(conn, second)) == {1}
    scenario.operator("send", f"review:{second}", "1")
    assert review_runs.held(conn, second) == {}

    found = json.loads(scenario.operator("review", "noise", "--json").out)
    assert found["reviews"] == 2
    assert [(g["key"], g["findings"], g["dismissed"], g["answered"], g["rebuttals"]) for g in found["severity"]] == [
        ("blocking", 2, {"wrong": 1}, {"fixed": 1}, 0),
        # The rebuttal itself is neither dismissed nor answered: it counts in the total and as a rebuttal.
        ("minor", 2, {}, {"declined": 1}, 1),
    ]
    assert found["severity"][0]["rates"]["fixed"] == 0.5
    text = scenario.operator("review", "noise").out.splitlines()
    assert text[3:5] == [
        (
            "blocking         2      1            0             0             0           0      1         0          0"
            "         50%"
        ),
        (
            "minor            2      0            0             0             0           0      0         1          1"
            "          0%"
        ),
    ]


def test_a_rebuttal_the_operator_dismisses_waits_on_nobody(
    reviewing: CanopyEnv,
    scenario: Scenario,
    git_pool: GitPool,
    ctx: Context,
) -> None:
    """Dismissing a held rebuttal agrees with the worker: the review then moves on as a clean one (DESIGN §21)."""
    conn = scenario.conn
    first = scenario.review(reviews(head(git_pool), ticket="PROJ-1"), reviewer=reviewer_reports(TWO_FINDINGS)).id
    scenario.run(worker=pushes())
    scenario.run(resume(first), worker=pushes(review_answers=answers_to(first)))
    rebuttal = {**FINDINGS, "findings": [{**TWO_FINDINGS["findings"][1], "rebuts": 2}]}
    sha = present(git_pool.remote_head("agent/PROJ-1-work"))
    db.set_unit(conn, "PROJ-1", str(reviewing.root), "repo", pr_url=PR)
    scenario.tick(*waits("PROJ-1"), dry_run=True)
    second = scenario.review(reviews(sha, ticket="PROJ-1"), reviewer=reviewer_reports(rebuttal)).id
    assert scenario.refuses(resume(second))[0][1].startswith(f"every finding of review run {second}")
    # The tick records the item about the ticket; the list checks it against the holds as they stand.
    scenario.tick(*waits("PROJ-1"), dry_run=True)
    assert [(i.subject, i.reason) for i in attention.listed(ctx) if i.reason == waiting.REBUTTAL_REASON] == [
        ("PROJ-1", waiting.REBUTTAL_REASON),
    ]
    scenario.operator("dismiss", f"review:{second}", "1", "--reason", "wrong")
    assert waiting.items(conn) == []
    assert all(i.reason != waiting.REBUTTAL_REASON for i in attention.listed(ctx))


def test_a_review_names_a_ticket_only_for_the_pr_its_unit_opened(
    reviewing: CanopyEnv,
    scenario: Scenario,
    git_pool: GitPool,
) -> None:
    """A review's purpose is settled as it starts: `own` only for its ticket's unit's PR, else `query` (DESIGN §21)."""
    other = "https://github.com/acme/api/pull/8"
    sha = head(git_pool)
    assert scenario.refuses(reviews(sha, other, ticket="PROJ-1")) == [
        (
            "refused:not_ours",
            f"PROJ-1's unit in repo did not open {other}; ticket is only for the loop's own PR",
        ),
    ]
    assert scenario.refuses(reviews(sha, ticket="PROJ-2")) == [
        (
            "refused:not_ours",
            f"PROJ-2's unit in repo did not open {PR}; ticket is only for the loop's own PR",
        ),
    ]
    own = scenario.review(reviews(sha, ticket="PROJ-1"), reviewer=reviewer_reports(FINDINGS)).id
    query = scenario.review(reviews(sha, other), reviewer=reviewer_reports(FINDINGS)).id
    purposes = {r["id"]: r["purpose"] for r in scenario.conn.execute("SELECT id, purpose FROM review_runs")}
    assert purposes == {own: "own", query: "query"}


def test_a_review_is_new_to_the_operator_until_they_see_it(
    reviewing: CanopyEnv,
    scenario: Scenario,
    git_pool: GitPool,
) -> None:
    """`canopy review show ID` marks a review's result seen, as its page does; only for the operator (DESIGN §22).

    A review is new once it found something, or ended at all when the operator asked for it: a clean review the loop
    started on its own is never new.
    """
    sha = head(git_pool)
    asked = "https://github.com/acme/api/pull/11"
    first = scenario.review(reviews(sha, ticket="PROJ-1"), reviewer=reviewer_reports(FINDINGS)).id
    scenario.review(reviews(sha, "https://github.com/acme/api/pull/9"), reviewer=reviewer_reports(CLEAN))
    scenario.operator("start", asked, "--review")
    second = scenario.review(reviews(sha, asked), reviewer=reviewer_reports(CLEAN)).id
    running = scenario.starts_review(reviews(sha, "https://github.com/acme/api/pull/10"))

    def new() -> list[int]:
        return [
            int(line.split()[0])
            for line in scenario.operator("review", "show").out.splitlines()
            if line.endswith("  new")
        ]

    assert new() == [second, first]
    # An agent cannot hide a review from the operator by reading it in full: the show stands, and it stays new.
    with mock.patch.dict(os.environ, {"CANOPY_RUN_ID": "1"}):
        assert main(["review", "show", str(first)]) == 0
    assert new() == [second, first]
    # A review still running has no result to see yet: its show marks nothing.
    scenario.operator("review", "show", str(running.id))

    scenario.operator("review", "show", str(first))
    assert new() == [second]
    [mark] = records.fetch_all(
        scenario.conn,
        records.Seen,
        sql.select("*").from_("seen").where("subject = ?", str(first)),
    )
    assert (mark.kind, mark.channel) == (SeenKind.REVIEW, "cli")

    # The guards every channel's mark goes through: all of them are marked, or none.
    def refused(*refs: str) -> str:
        with pytest.raises(conversation.Refused) as refusal:
            conversation.see(scenario.conn, [conversation.parse_ref(r) for r in refs], channel="web")
        return refusal.value.guard

    assert refused(f"review:{second}", f"review:{running.id}") == "running"
    assert refused(f"review:{second}", "review:99") == "unknown"
    assert refused(f"review:{second}", "PROJ-1") == "unsupported"
    assert new() == [second]
    ref = conversation.Ref(conversation.REVIEW, str(second))
    assert conversation.see(scenario.conn, [ref, ref], channel="web") == [ref]
    assert conversation.see(scenario.conn, [ref], channel="web") == []
    assert new() == []
    running.finishes()


def test_the_loops_own_pr_is_reviewed_once_in_each_of_its_reviewers(
    reviewing: CanopyEnv,
    scenario: Scenario,
    git_pool: GitPool,
) -> None:
    # DESIGN §31: `[personas] reviewers` reviews each commit of the loop's own PRs once in each, side by side.
    scenario.configures(personas={"reviewers": ["skeptic", "explainer"]}, capacity={"max_reviews": 2})
    sha = head(git_pool)
    both = scenario.reviews_each(reviews(sha, ticket="PROJ-1"), reviewer=reviewer_reports(CLEAN))
    assert [(r.row.persona, r.status) for r in both] == [("skeptic", "done"), ("explainer", "done")]
    [(action, reason)] = scenario.refuses(reviews(sha, ticket="PROJ-1"))
    assert action == "refused:reviewed"
    assert reason.startswith(f"each persona chosen for this PR (skeptic, explainer) has reviewed {sha[:12]};")
    # The ticket's override chooses one persona, whose one review the next commit gets.
    scenario.operator("persona", "PROJ-1", "minimalist", "--agent", "reviewer")
    assert scenario.operator("persona", "PROJ-1", "--agent", "reviewer").out.splitlines()[1] == (
        "  reviewer  minimalist  (this ticket's override)"
    )
    [one] = scenario.reviews_each(reviews("b" * 40, ticket="PROJ-1"), reviewer=reviewer_reports(CLEAN))
    assert one.row.persona == "minimalist"
    # A PR the loop does not own takes `[personas] reviewer`'s one.
    other = "https://github.com/acme/api/pull/8"
    assert scenario.review(reviews(sha, other), reviewer=reviewer_reports(CLEAN)).row.persona == "canopy"


def test_a_commit_waits_on_each_reviewer_and_counts_each_review_against_the_limit(
    reviewing: CanopyEnv,
    scenario: Scenario,
    git_pool: GitPool,
) -> None:
    scenario.configures(personas={"reviewers": ["skeptic", "explainer"]})
    sha = head(git_pool)
    first = scenario.review(reviews(sha, ticket="PROJ-1"), reviewer=reviewer_reports(FINDINGS))
    assert first.row.persona == "skeptic"
    # One review slot: explainer's waits, and the overseer sees the commit still owed it. Its overseer, played
    # whole, decides nothing, so the tick leaves PROJ-1's duty undone.
    actions = [d.action for d in db.decisions_for_tick(scenario.conn, first.row.tick_id)]
    # The refusal is at the ask; the review's decision as the tick starts it, after the overseer (DESIGN §40).
    assert actions == ["refused:review_capacity", "dispatch:review"]
    scenario.tick(dry_run=True, code=1)
    [pr] = scenario.state()["reviews"]["prs"]
    assert (pr["latest"]["run_id"], pr["owed"]) == (first.id, ["explainer"])
    second = scenario.review(reviews(sha, ticket="PROJ-1"), reviewer=reviewer_reports(FINDINGS))
    assert second.row.persona == "explainer"
    # Reviewed in each: the commit's reviews read as one, their findings together, at the number the last took.
    scenario.tick(dry_run=True, code=1)
    [pr] = scenario.state()["reviews"]["prs"]
    assert "owed" not in pr
    assert (pr["latest"]["run_id"], pr["latest"]["verdict"]) == (second.id, "findings")
    assert pr["latest"]["findings"] == ["retry never stops", "retry never stops"]
    assert pr["latest"]["number"] == max(first.row.number or 0, second.row.number or 0)
    # Each review counted: at a limit of two, the next commit gets none.
    scenario.configures("workspace", policy={"max_reviews_per_pr": 2})
    assert [a for a, _ in scenario.refuses(reviews("b" * 40, ticket="PROJ-1"))] == [
        "refused:review_limit",
        "attention:review_limit",
    ]


def test_a_resume_addresses_the_findings_of_each_reviewer_of_its_commit(
    reviewing: CanopyEnv,
    scenario: Scenario,
    git_pool: GitPool,
) -> None:
    scenario.configures(personas={"reviewers": ["skeptic", "explainer"]}, capacity={"max_reviews": 2})
    sha = head(git_pool)
    skeptic, explainer = scenario.reviews_each(reviews(sha, ticket="PROJ-1"), reviewer=reviewer_reports(FINDINGS))
    scenario.run(worker=pushes())
    resumed = scenario.run(resume(explainer.id), worker=pushes())
    section = resumed.prompt.split("## canopy's review\n\n", 1)[1]
    assert f"canopy's review run {explainer.id} of {PR} at commit `{sha}`, in explainer, found these" in section
    assert f"canopy's review run {skeptic.id} of {PR} at commit `{sha}`, in skeptic, found these" in section
    # A persona's review whose findings the operator dismissed adds nothing.
    scenario.operator("dismiss", f"review:{skeptic.id}", "1", "--reason", "wrong")
    again = scenario.run(resume(explainer.id), worker=pushes())
    assert f"review run {skeptic.id} " not in again.prompt.split("## canopy's review\n\n", 1)[1]


def test_personas_reviewers_names_each_persona_once_and_canopy_personas_lists_them(
    reviewing: CanopyEnv,
    scenario: Scenario,
) -> None:
    scenario.configures(personas={"reviewers": ["skeptic", "skeptic"]})
    assert "personas.reviewers: Value error, names skeptic more than once" in scenario.operator("personas", code=2).err
    scenario.configures(personas={"reviewers": ["skeptic", "lenient"]})
    printed = scenario.operator("personas", code=1).out
    assert "  skeptic  canopy's; the default for reviewer\n" in printed
    assert "[personas] reviewers names lenient, which has no file: its reviews refuse (persona_missing).\n" in printed
    assert "  reviewer  skeptic, lenient  ([personas] reviewers: one review each)\n" in (
        scenario.operator("persona", "PROJ-1").out
    )
