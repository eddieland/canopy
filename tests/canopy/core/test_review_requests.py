"""Review requests (DESIGN §21, ROADMAP M42): the operator asks canopy to review a PR the loop does not own."""

import os
import sqlite3
from unittest import mock

import httpx2
import pytest

from canopy.cli.main import main
from canopy.core import conversation, db, personas, review_requests
from canopy.core.config import load
from canopy.core.context import Context
from canopy.infra import resources
from tests.canopy.helpers import context, operator, personas_dir
from tests.canopy.review_helpers import CLEAN, FINDINGS, head, review_decisions, reviewer_reports
from tests.canopy.scenario_helpers import Scenario, reviews
from tests.canopy.web_helpers import refused, signed_in_client
from tests.conftest import CanopyEnv, GitPool

PR = "https://github.com/acme/other/pull/12"
LOOP_PR = "https://github.com/acme/api/pull/7"


@pytest.fixture
def requests_env(canopy_env: CanopyEnv) -> CanopyEnv:
    """A reviewer command and no `[review]` table: reviews are on only while a request is open."""
    template = "env OPENCODE_CONFIG_DIR={definitions_dir} agent run --agent canopy-reviewer {prompt}"
    user = canopy_env.user_file.read_text().replace("[runtime]\n", f"[runtime]\nreview_cmd = '{template}'\n", 1)
    canopy_env.write_user(user)
    return canopy_env


@pytest.fixture
def ctx(requests_env: CanopyEnv) -> Context:
    found = context(requests_env)
    db.migrate(found.conn, resources.migrations_dir())
    return found


def requests_of(conn: sqlite3.Connection) -> list[tuple[str, str, str | None]]:
    rows = conn.execute("SELECT pr_url, channel, end_reason FROM review_requests ORDER BY id")
    return [(r["pr_url"], r["channel"], r["end_reason"]) for r in rows]


def test_a_request_is_reviewed_at_its_head_and_ends_reviewed(
    requests_env: CanopyEnv,
    scenario: Scenario,
    git_pool: GitPool,
) -> None:
    conn = scenario.conn
    # Without a request, no `[review]` table means reviews are off.
    assert [action for action, _ in scenario.refuses(reviews(head(git_pool), PR))] == ["refused:reviews_off"]

    requested = scenario.operator("start", PR, "--review")
    assert f"{PR} is requested for review. The next tick reviews its head, once." in requested.out
    assert "was already requested" in scenario.operator("start", PR, "--review").out
    assert requests_of(conn) == [(PR, "cli", None)]

    run = scenario.review(reviews(head(git_pool), PR), reviewer=reviewer_reports(FINDINGS)).row
    assert (run.status, run.purpose, run.ticket_key) == ("done", "request", None)
    assert requests_of(conn) == [(PR, "cli", "reviewed")]
    # With the request ended, reviews are off again.
    assert not review_requests.reviews_on(conn, load(requests_env.root))

    out = scenario.operator("show", PR).out
    assert "review request: made " in out
    assert "(reviewed)" in out
    assert f"review:{run.id}" in out


def test_the_reviewer_is_handed_the_requests_notes(
    requests_env: CanopyEnv,
    scenario: Scenario,
    git_pool: GitPool,
) -> None:
    conn = scenario.conn
    scenario.operator("start", PR, "--review", "--notes", "  The author asked about the cache.  ")
    assert review_requests.open_requests(conn)[0].notes == "The author asked about the cache."
    # Asked again without notes, the request keeps its own; with notes, they replace them.
    assert "Its notes are replaced" not in scenario.operator("start", PR, "--review", "--notes", " ").out
    assert review_requests.open_requests(conn)[0].notes == "The author asked about the cache."
    again = scenario.operator("start", PR, "--review", "--notes", "Look hard at the eviction.\nAnd its lock.")
    assert f"{PR} was already requested for review. Its notes are replaced." in again.out
    assert "  notes:\n    Look hard at the eviction.\n    And its lock.\n" in scenario.operator("show", PR).out

    reviewed = scenario.review(reviews(head(git_pool), PR), reviewer=reviewer_reports(CLEAN))
    assert "## Notes from the operator\n\nLook hard at the eviction.\nAnd its lock.\n" in reviewed.prompt
    assert requests_of(conn) == [(PR, "cli", "reviewed")]


def test_a_review_without_a_requests_notes_has_no_section_for_them(
    requests_env: CanopyEnv,
    scenario: Scenario,
    git_pool: GitPool,
) -> None:
    scenario.operator("start", PR, "--review")
    assert review_requests.open_requests(scenario.conn)[0].notes is None
    reviewed = scenario.review(reviews(head(git_pool), PR), reviewer=reviewer_reports(CLEAN))
    assert "## Notes from the operator" not in reviewed.prompt


def test_a_request_is_reviewed_in_the_persona_the_operator_chose_for_it(
    requests_env: CanopyEnv,
    scenario: Scenario,
    git_pool: GitPool,
) -> None:
    # DESIGN §31: the request's persona takes the place of `[personas] reviewer`, for this PR's review alone.
    scenario.configures(personas={"reviewer": "explainer"})
    requested = scenario.operator("start", PR, "--review", "--persona", "skeptic").out
    assert requested.endswith("Nothing is posted on the PR.\nIts review is written in skeptic.\n")
    assert "  persona: skeptic\n" in scenario.operator("show", PR).out
    assert (
        scenario.operator("persona", PR).out == f"{PR}'s review is written in skeptic, from its next: this request's.\n"
    )
    skeptic = personas.load(load(requests_env.root, requests_env.user_file), "skeptic")
    reviewed = scenario.review(reviews(head(git_pool), PR), reviewer=reviewer_reports(CLEAN))
    assert f"## Persona\n\n{skeptic.text}\n" in reviewed.prompt
    assert (reviewed.row.persona, reviewed.row.persona_digest) == ("skeptic", skeptic.digest)
    # Another PR's review takes `[personas]`'s.
    other = "https://github.com/acme/other/pull/13"
    scenario.operator("start", other, "--review")
    assert scenario.review(reviews("b" * 40, other), reviewer=reviewer_reports(CLEAN)).row.persona == "explainer"


def test_canopy_persona_chooses_or_clears_an_open_requests_persona(
    requests_env: CanopyEnv,
    scenario: Scenario,
    git_pool: GitPool,
) -> None:
    scenario.operator("start", PR, "--review")
    assert (
        scenario.operator("persona", PR).out == f"{PR}'s review is written in eddie, from its next: canopy's default.\n"
    )
    said = scenario.operator("persona", PR, "minimalist", "--agent", "reviewer").out
    assert said == f"{PR}'s review is written in minimalist, from its next: this request's.\n"
    # Asked again with a persona, the request's is replaced, as its notes are.
    again = scenario.operator("start", PR, "--review", "--persona", "skeptic").out
    assert again == f"{PR} was already requested for review. Its review is written in skeptic.\n"
    assert "Its review is written in" not in scenario.operator("start", PR, "--review").out
    assert review_requests.personas_of(scenario.conn, review_requests.open_requests(scenario.conn)[0].id) == ["skeptic"]
    scenario.configures(personas={"reviewer": "explainer"})
    cleared = scenario.operator("persona", PR, "--clear").out
    assert cleared == f"{PR}'s review is written in explainer, from its next: [personas].\n"
    assert scenario.review(reviews(head(git_pool), PR), reviewer=reviewer_reports(CLEAN)).row.persona == "explainer"


def test_a_requests_persona_is_refused_when_unknown_without_a_request_or_inside_a_run(
    requests_env: CanopyEnv,
    scenario: Scenario,
) -> None:
    err = scenario.operator("start", PR, "--review", "--persona", "lenient", code=1).err
    assert "start refused (unknown_persona): persona lenient has no file among canopy's own" in err
    assert requests_of(scenario.conn) == []
    # Without --review, a PR is M14's, whatever persona it names.
    assert "start refused (unsupported)" in scenario.operator("start", PR, "--persona", "skeptic", code=1).err
    err = scenario.operator("persona", PR, "skeptic", code=1).err
    assert f"persona refused (not_requested): {PR} has no open review request" in err
    assert f"canopy start {PR} --review --persona skeptic" in err
    assert "has no open review request" in scenario.operator("persona", PR, code=1).err
    scenario.operator("start", PR, "--review")
    assert "only its review's persona" in scenario.operator("persona", PR, "skeptic", "--agent", "worker", code=2).err
    assert "persona refused (unknown_persona)" in scenario.operator("persona", PR, "lenient", code=1).err
    # No agent chooses a persona, a PR's reviewer's least of all (TRUST_MODEL T1).
    assert "persona refused (inside_run)" in scenario.overseer("persona", PR, "skeptic", code=1).err
    assert "persona refused (bad_pr)" in scenario.operator("persona", "repo#12", "skeptic", code=1).err
    assert scenario.conn.execute("SELECT count(*) FROM review_request_personas").fetchone()[0] == 0


def test_a_review_whose_requests_persona_has_no_file_is_refused_and_asks_the_operator(
    requests_env: CanopyEnv,
    scenario: Scenario,
    git_pool: GitPool,
) -> None:
    yours = personas_dir(requests_env)
    (yours / "terse.md").write_text("Be terse.\n")
    scenario.operator("start", PR, "--review", "--persona", "terse")
    (yours / "terse.md").unlink()
    reason = (
        f"{PR}'s review request: persona terse has no file in {yours} or among canopy's own: add it, or name one "
        f"`canopy personas` lists; or clear it: canopy persona {PR} --clear"
    )
    # Never `[personas]`'s instead: the operator chose this one for this PR.
    refused = scenario.refuses(reviews(head(git_pool), PR))
    assert refused == [("refused:persona_missing", reason), ("attention:persona_missing", reason)]
    assert scenario.conn.execute("SELECT count(*) FROM review_runs").fetchone()[0] == 0
    assert requests_of(scenario.conn) == [(PR, "cli", None)]


def test_a_request_in_several_personas_is_reviewed_once_in_each_side_by_side(
    requests_env: CanopyEnv,
    scenario: Scenario,
    git_pool: GitPool,
) -> None:
    scenario.configures(capacity={"max_reviews": 2})
    out = scenario.operator("start", PR, "--review", "--persona", "skeptic", "--persona", "explainer").out
    assert out.endswith("It is reviewed once in each of skeptic, explainer, side by side.\n")
    assert "  personas: skeptic, explainer\n" in scenario.operator("show", PR).out
    said = scenario.operator("persona", PR).out
    assert said == f"{PR} is reviewed once in each of skeptic, explainer, side by side: this request's.\n"
    # One `review run`: both start in its tick, the second while the first is still at work.
    both = scenario.reviews_each(reviews(head(git_pool), PR), reviewer=reviewer_reports(FINDINGS))
    assert [(r.row.persona, r.status, r.row.tick_id) for r in both] == [
        ("skeptic", "done", both[0].row.tick_id),
        ("explainer", "done", both[0].row.tick_id),
    ]
    # The request ends once each persona has had its review.
    assert requests_of(scenario.conn) == [(PR, "cli", "reviewed")]
    # Each review keeps a draft of its own, and is named by its persona.
    hashes = {scenario.operator("review", "draft", str(r.id)).out.splitlines()[0] for r in both}
    assert len(hashes) == 2
    listed = scenario.operator("review", "show").out
    assert all(f"{r.id}  " in listed and f"  in {r.row.persona}" in listed for r in both)
    assert f"review run {both[0].id} of {PR} at {head(git_pool)}, in skeptic" in (
        scenario.operator("review", "show", str(both[0].id)).out
    )
    assert "  in explainer\n" in scenario.operator("show", PR).out


def test_a_persona_is_reviewed_once_per_commit_and_waits_on_room_for_its_review(
    requests_env: CanopyEnv,
    scenario: Scenario,
    git_pool: GitPool,
) -> None:
    scenario.configures(capacity={"max_reviews": 1})
    scenario.operator("start", PR, "--review", "--persona", "skeptic", "--persona", "explainer")
    sha = head(git_pool)
    first = scenario.review(reviews(sha, PR), reviewer=reviewer_reports(CLEAN))
    assert first.row.persona == "skeptic"
    # One slot: explainer's review waits, and the request with it.
    actions = [d.action for d in db.decisions_for_tick(scenario.conn, first.row.tick_id)]
    assert actions == ["dispatch:review", "refused:review_capacity"]
    assert requests_of(scenario.conn) == [(PR, "cli", None)]
    # At the same commit, skeptic's review is done: the next starts explainer's alone, and that ends the request.
    second = scenario.review(reviews(sha, PR), reviewer=reviewer_reports(CLEAN))
    assert second.row.persona == "explainer"
    assert requests_of(scenario.conn) == [(PR, "cli", "reviewed")]
    # Asked again at a head each persona reviewed: the refusal answers it.
    scenario.operator("start", PR, "--review", "--persona", "explainer", "--persona", "skeptic")
    [(action, reason)] = scenario.refuses(reviews(sha, PR))
    assert action == "refused:reviewed"
    assert reason.startswith(f"each persona chosen for this PR (explainer, skeptic) has reviewed {sha[:12]}")
    assert requests_of(scenario.conn)[-1] == (PR, "cli", "reviewed")
    # A persona that has not reviewed this commit is owed one, though another persona has.
    scenario.operator("start", PR, "--review", "--persona", "minimalist")
    assert scenario.review(reviews(sha, PR), reviewer=reviewer_reports(CLEAN)).row.persona == "minimalist"


def test_each_personas_review_counts_against_the_prs_limit(
    requests_env: CanopyEnv,
    scenario: Scenario,
    git_pool: GitPool,
) -> None:
    scenario.configures(capacity={"max_reviews": 2})
    scenario.configures("workspace", policy={"max_reviews_per_pr": 1})
    scenario.operator("start", PR, "--review", "--persona", "skeptic", "--persona", "explainer")
    [one] = scenario.reviews_each(reviews(head(git_pool), PR), reviewer=reviewer_reports(CLEAN))
    assert one.row.persona == "skeptic"
    actions = [d.action for d in db.decisions_for_tick(scenario.conn, one.row.tick_id)]
    assert actions == ["dispatch:review", "refused:review_limit"]
    assert (
        "several are for a PR's reviews"
        in scenario.operator("start", "PROJ-1", "--persona", "skeptic", "--persona", "explainer", code=2).err
    )


def test_notes_are_refused_without_review_or_past_their_bound(requests_env: CanopyEnv, scenario: Scenario) -> None:
    assert "--notes is for a PR's review" in scenario.operator("start", "PROJ-1", "--notes", "hi", code=2).err
    too_long = "x" * (review_requests.MAX_NOTES + 1)
    refused = scenario.operator("start", PR, "--review", "--notes", too_long, code=1)
    assert f"start refused (bad_notes): the notes are {len(too_long)} characters; the most is 4000" in refused.err
    assert requests_of(scenario.conn) == []


def test_a_request_made_after_its_head_was_reviewed_ends_on_the_reviewed_refusal(
    requests_env: CanopyEnv,
    scenario: Scenario,
    git_pool: GitPool,
) -> None:
    conn = scenario.conn
    scenario.operator("start", PR, "--review")
    again = reviews(head(git_pool), PR)
    scenario.review(again, reviewer=reviewer_reports(CLEAN))
    # Asked for again at a head already reviewed: no new review will end it, so the refusal that names the review does.
    scenario.operator("start", PR, "--review")
    scenario.refuses(again, dry_run=True)
    assert requests_of(conn)[-1] == (PR, "cli", None)
    assert [action for action, _ in scenario.refuses(again)] == ["refused:reviewed"]
    assert requests_of(conn) == [(PR, "cli", "reviewed"), (PR, "cli", "reviewed")]


def test_a_failed_review_leaves_the_request_open(
    requests_env: CanopyEnv,
    scenario: Scenario,
    git_pool: GitPool,
) -> None:
    scenario.operator("start", PR, "--review")
    failing = reviewer_reports({"status": "failed", "summary": "Could not read the diff."})
    assert scenario.review(reviews(head(git_pool), PR), reviewer=failing).status == "failed"
    assert requests_of(scenario.conn) == [(PR, "cli", None)]


def test_review_end_ends_a_request_whose_pr_merged_first_and_needs_a_tick(
    requests_env: CanopyEnv,
    scenario: Scenario,
) -> None:
    conn = scenario.conn
    scenario.operator("start", PR, "--review")
    assert "no tick is running" in scenario.operator("review", "end", "--pr", PR, "--reason", "closed", code=1).err
    with scenario.ticking(dry_run=True) as tick_id:
        scenario.overseer("review", "end", "--pr", PR, "--reason", "closed")
        assert [d[2:] for d in review_decisions(conn, tick_id)] == [("review:end", "dry run: not ended; closed")]
    assert requests_of(conn) == [(PR, "cli", None)]
    other = f"{PR}0"
    scenario.operator("start", other, "--review")
    # A PR in none of the workspace's repositories cannot be reviewed here.
    scenario.overseer("review", "end", "--pr", other, "--reason", "unknown_repo")
    with scenario.ticking() as tick_id:
        scenario.overseer("review", "end", "--pr", PR, "--reason", "stopped", code=2)
        scenario.overseer("review", "end", "--pr", PR, "--reason", "merged")
        refused = scenario.overseer("review", "end", "--pr", PR, "--reason", "merged", code=1)
        assert "review end refused (not_requested)" in refused.err
        assert [d[2:] for d in review_decisions(conn, tick_id)] == [
            ("review:end", "merged"),
            ("refused:not_requested", f"{PR} has no open request"),
        ]
    assert requests_of(conn) == [(PR, "cli", "merged"), (other, "cli", "unknown_repo")]


@pytest.mark.parametrize("variable", ["CANOPY_TICK_ID", "CANOPY_RUN_ID"])
def test_only_the_operator_requests_or_stops_a_review(
    requests_env: CanopyEnv,
    capsys: pytest.CaptureFixture[str],
    variable: str,
) -> None:
    conn = requests_env.journal()
    with mock.patch.dict(os.environ, {variable: "1"}):
        assert main(["start", PR, "--review"]) == 1
        assert "start refused (inside_run)" in capsys.readouterr().err
    assert operator("start", PR, "--review") == 0
    with mock.patch.dict(os.environ, {variable: "1"}):
        assert main(["stop", PR]) == 1
        assert "stop refused (inside_run)" in capsys.readouterr().err
    assert requests_of(conn) == [(PR, "cli", None)]


def test_a_request_refuses_recording_nothing(requests_env: CanopyEnv, scenario: Scenario) -> None:
    conn = scenario.conn
    db.set_unit(conn, "PROJ-1", str(requests_env.root), "repo", pr_url=LOOP_PR)
    refusals = [
        ([LOOP_PR, "--review"], "start refused (loop_pr)"),
        (["repo#12", "--review"], "start refused (bad_pr): name the PR by its plain https:// URL"),
        (["PROJ-1", "--review"], "start refused (bad_pr)"),
        (["https://github.com/acme/other/issues/3", "--review"], "start refused (bad_ref)"),
    ]
    for args, refusal in refusals:
        assert refusal in scenario.operator("start", *args, code=1).err
    # Without --review, a PR is M14's, so a missing flag never turns a review into work on someone else's branch.
    assert "start refused (unsupported)" in scenario.operator("start", PR, code=1).err
    scenario.operator("start", PR, "--review", "--repo", "repo", code=2)
    refused = scenario.operator("stop", PR, code=1)
    assert f"stop refused (not_requested): {PR} has no open review request" in refused.err

    scenario.configures(capacity={"max_reviews": 0})
    assert "start refused (reviews_off)" in scenario.operator("start", PR, "--review", code=1).err
    assert requests_of(conn) == []
    assert db.starts(conn) == []


def test_status_lists_an_open_request_and_stop_ends_it(requests_env: CanopyEnv, scenario: Scenario) -> None:
    scenario.operator("start", PR, "--review")
    assert f"{PR}  " in scenario.operator("status").out
    assert "review request is stopped" in scenario.operator("stop", PR).out
    assert requests_of(scenario.conn) == [(PR, "cli", "stopped")]
    assert "Review requests" not in scenario.operator("status").out


def test_the_state_block_carries_the_open_requests(
    requests_env: CanopyEnv,
    scenario: Scenario,
    git_pool: GitPool,
) -> None:
    # No request, no query, and agent_prs off: nothing about reviews reaches the overseer.
    scenario.tick(dry_run=True)
    assert "reviews" not in scenario.state()
    scenario.operator("start", PR, "--review")
    failing = reviewer_reports({"status": "failed", "summary": "Could not read the diff."})
    run_id = scenario.review(reviews(head(git_pool), PR), reviewer=failing).id
    scenario.tick(dry_run=True)
    section = scenario.state()["reviews"]
    assert (section["agent_prs"], section["query"]) == (False, None)
    [requested] = section["requests"]
    assert {k: requested[k] for k in ("url", "review_runs")} == {"url": PR, "review_runs": 1}
    # The overseer matches the PR's URL to a repository by the map's clone URL.
    assert [r["url"] for r in scenario.state()["repositories"]] == ["https://example.test/acme/repo.git"]
    assert (requested["latest"]["run_id"], requested["latest"]["status"]) == (run_id, "failed")
    assert [p["url"] for p in section["prs"]] == [PR]


def test_the_web_channel_requests_and_stops_a_review_as_the_cli_does(ctx: Context) -> None:
    c, headers = signed_in_client(ctx)

    def start(url: str, **params: str) -> httpx2.Response:
        return c.post("/api/pull-request/start", params={"url": url, **params}, headers=headers)

    def stop(url: str) -> httpx2.Response:
        return c.post("/api/pull-request/stop", params={"url": url}, headers=headers)

    assert refused(start("PROJ-1")).startswith("bad_pr")
    assert refused(stop(PR)).startswith("not_requested")
    assert c.post("/api/pull-request/start", params={"url": PR}).status_code == 403

    made = start(PR).json()
    assert (made["already"], made["request"]["channel"], made["request"]["ended_at"]) == (False, "web", None)
    assert made["request"]["notes"] is None
    assert start(PR).json()["already"] is True
    noted = c.post("/api/pull-request/start", params={"url": PR}, json={"notes": " The cache. "}, headers=headers)
    assert (noted.json()["already"], noted.json()["request"]["notes"]) == (True, "The cache.")
    blank = c.post("/api/pull-request/start", params={"url": PR}, json={"notes": ""}, headers=headers)
    assert blank.json()["request"]["notes"] == "The cache."
    page = c.get("/api/pull-request", params={"url": PR}).json()
    assert page["pull_request"]["review_request"]["ended_at"] is None
    assert page["pull_request"]["review_request"]["notes"] == "The cache."
    long = {"notes": "x" * (review_requests.MAX_NOTES + 1)}
    assert refused(c.post("/api/pull-request/start", params={"url": PR}, json=long, headers=headers)).startswith(
        "bad_notes",
    )
    assert [p["url"] for p in c.get("/api/pull-requests").json()] == [PR]

    stopped = stop(PR).json()
    assert stopped["running_review"] is None
    request = c.get("/api/pull-request", params={"url": PR}).json()["pull_request"]["review_request"]
    assert (request["end_reason"], request["ended_at"] is not None) == ("stopped", True)
    with pytest.raises(conversation.Refused, match="not_requested"):
        review_requests.stop(ctx.conn, conversation.parse_ref(PR))
