"""The outline of its repositories' code in a worker's, a planner's, and a task's prompt (DESIGN §46, ROADMAP M70).

At `index.outline = "tree"` an `implement`'s, a `resume`'s, a plan's, a feedback plan's, and a task's prompt holds a
directory tree of each repository the run works in, opened by the ticket's or the task's words or by what the branch
changed; at `off`, the default, it holds none.
"""

import json
import sqlite3
from pathlib import Path

from canopy.core import db
from canopy.core.vocab import ResumeReason, RunKind, RunStatus
from canopy.infra import logs
from canopy.runs import outlines, task_starts, tasks
from tests.canopy.conftest import Ws
from tests.canopy.helpers import (
    BRANCH,
    DRAFTS_PR,
    KEY,
    LABEL,
    OUTLINE_HEADING,
    WORKER_DONE,
    commit_and_push,
    context,
    in_tick,
    inline_context,
    operator,
    outline_of,
    planner_does,
    present,
    tracked,
    worker_does,
)
from tests.canopy.scenario_helpers import Scenario, dispatches, feedback_planned, pushes
from tests.conftest import TRACKER_SOURCE, CanopyEnv, GitPool, git

#: A repository's files, as its base branch holds them.
FILES = (
    "README.md",
    "services/billing/invoices/render.py",
    "services/billing/invoices/totals.py",
    "services/billing/ledger.py",
    *(f"services/shipping/carrier_{n:02}_rate_table.py" for n in range(12)),
    *(f"vendor/third_party_library_{n:02}.py" for n in range(30)),
)
TREE = {"index": {"outline": "tree", "outline_chars": 500}}
#: The lines of FILES' outline that open the directory a text about invoices names.
INVOICES = ["services/", "  billing/", "    invoices/", "      render.py", "      totals.py", "    ledger.py"]
#: What a worker runs to add a guide page to its branch: the branch's change, which opens `docs/guide/`.
ADDS_A_GUIDE = (["mkdir", "-p", "docs/guide"], ["touch", "docs/guide/rounding.md"], ["git", "add", "docs"])


def ticket_says(connector_state: Path, title: str, body: str = "") -> None:
    """The tracker holds KEY, open and labeled, titled `title` with the description `body`."""
    line = {"kind": "ticket", "key": KEY, "title": title, "body": body, "state": "open", "labels": [{"name": LABEL}]}
    connector_state.write_text(json.dumps({TRACKER_SOURCE: {"lines": [line]}}))


def fetched(git_pool: GitPool) -> None:
    """Fetch origin in each slot: every slot of a real pool shares one git directory, so each holds what one pushed."""
    for slot in git_pool.slots:
        git("fetch", "--quiet", "origin", cwd=slot)


def test_with_the_outline_off_a_prompt_has_none(scenario: Scenario, git_pool: GitPool, tmp_path: Path) -> None:
    tracked(git_pool.origin, git_pool.slots, tmp_path, FILES)

    run = scenario.run(worker=pushes())

    assert run.status == RunStatus.DONE
    assert OUTLINE_HEADING not in run.prompt
    assert "services" not in run.prompt


def test_an_implements_prompt_holds_its_bases_tree_opened_by_the_tickets_words(
    scenario: Scenario,
    git_pool: GitPool,
    connector_state: Path,
    tmp_path: Path,
) -> None:
    tracked(git_pool.origin, git_pool.slots, tmp_path, FILES)
    scenario.configures(**TREE)
    ticket_says(connector_state, "Invoice totals round the wrong way", "Seen on every `InvoiceRenderer` since May.")

    run = scenario.run(worker=pushes())

    assert run.status == RunStatus.DONE
    assert "`repo`, as of `origin/main`:" in run.prompt
    shown = outline_of(run.prompt)
    # The directory the ticket names is open to its files; the others are a name and a count.
    assert shown[:6] == INVOICES
    assert "  shipping/ (12 files)" in shown
    assert "vendor/ (30 files)" in shown
    assert "46 files in all, 42 not listed by name." in run.prompt
    # The ticket's words rank and are rendered nowhere.
    assert "round the wrong way" not in run.prompt
    assert "InvoiceRenderer" not in run.prompt


def test_a_resumes_prompt_holds_its_branchs_tree_opened_where_the_branch_changed(
    scenario: Scenario,
    git_pool: GitPool,
    connector_state: Path,
    tmp_path: Path,
) -> None:
    tracked(git_pool.origin, git_pool.slots, tmp_path, FILES)
    scenario.configures(**TREE)
    ticket_says(connector_state, "Invoice totals round the wrong way")
    first = scenario.run(worker=worker_does(*ADDS_A_GUIDE, *commit_and_push(BRANCH)))
    assert first.status == RunStatus.DONE
    fetched(git_pool)

    resume = dispatches(kind=RunKind.RESUME, reasons=[ResumeReason.CI], cursors={"ci": "77"}, context="a red check")
    run = scenario.run(resume, worker=pushes())

    assert run.status == RunStatus.DONE
    assert f"`repo`, as of `origin/{BRANCH}`:" in run.prompt
    shown = outline_of(run.prompt)
    # The branch's own changes say where the work is, before the ticket's words do.
    assert shown[:3] == ["docs/", "  guide/", "    rounding.md"]
    assert "47 files in all, " in run.prompt


def test_a_joint_runs_prompt_holds_a_tree_for_each_repository(ws_scenario: Scenario, ws: Ws, tmp_path: Path) -> None:
    for name, origin in ws.origins.items():
        slot = ws.root / ".treehouse" / f"{name}-fake" / "1" / name
        tracked(origin, [slot], tmp_path, files=(f"{name}/handlers.py", f"{name}/models.py"))
    ws_scenario.configures(**TREE)

    run = ws_scenario.run(dispatches(repo=("api", "web")), worker=pushes(repos=("api", "web")))

    assert run.status == RunStatus.DONE
    assert run.prompt.count(OUTLINE_HEADING) == 1
    api, _, web = run.prompt.partition(f"{OUTLINE_HEADING}\n")[2].partition("`web`, as of `origin/main`:")
    assert "`api`, as of `origin/main`:" in api
    assert outline_of(OUTLINE_HEADING + "\n" + api) == ["api/", "  handlers.py", "  models.py"]
    assert outline_of(OUTLINE_HEADING + "\n" + web) == ["web/", "  handlers.py", "  models.py"]


def test_excluded_files_are_left_out_of_a_prompts_outline(
    scenario: Scenario,
    git_pool: GitPool,
    tmp_path: Path,
) -> None:
    tracked(git_pool.origin, git_pool.slots, tmp_path, FILES)
    scenario.configures(index={"outline": "tree", "exclude": ["services/shipping/", "vendor/", "**/*.md"]})

    run = scenario.run(worker=pushes())

    assert outline_of(run.prompt) == INVOICES
    assert "3 files in all, 0 not listed by name." in run.prompt


def test_a_repository_git_cannot_list_gets_no_outline_and_the_dispatch_goes_on(
    canopy_env: CanopyEnv,
    conn: sqlite3.Connection,
    tmp_path: Path,
) -> None:
    del conn  # the journal, migrated
    canopy_env.append_user("\n[index]\noutline = 'tree'\n")
    ctx = context(canopy_env)
    # A slot that is no repository, as a pool whose slot lost its `.git`.
    slot = db.RunSlot(repo="repo", slot_path=tmp_path, lease_id="1", lease_holder="h", base_branch="main")

    assert outlines.for_run(ctx, 1, KEY, RunKind.IMPLEMENT, branch=BRANCH, slots=[slot]) == ""


def test_a_plans_prompt_holds_its_bases_tree_opened_by_the_tickets_words(
    scenario: Scenario,
    git_pool: GitPool,
    connector_state: Path,
    tmp_path: Path,
) -> None:
    tracked(git_pool.origin, git_pool.slots, tmp_path, FILES)
    scenario.configures(**TREE)
    ticket_says(connector_state, "Invoice totals round the wrong way")

    run = scenario.run(dispatches(kind=RunKind.PLAN), worker=planner_does(plan="# Plan\n\nRound half up.\n"))

    assert run.status == RunStatus.DONE
    assert "`repo`, as of `origin/main`:" in run.prompt
    assert outline_of(run.prompt)[:6] == INVOICES


def test_a_feedback_plans_prompt_holds_its_branchs_tree_opened_where_the_branch_changed(
    scenario: Scenario,
    git_pool: GitPool,
    connector_state: Path,
    github_state: Path,
    tmp_path: Path,
) -> None:
    tracked(git_pool.origin, git_pool.slots, tmp_path, FILES)
    scenario.configures(**TREE)
    ticket_says(connector_state, "Invoice totals round the wrong way")
    opened = json.dumps(json.loads(WORKER_DONE) | {"prs": {"repo": DRAFTS_PR}})
    first = scenario.run(
        dispatches(slug="work"),
        worker=worker_does(*ADDS_A_GUIDE, *commit_and_push(BRANCH), result=opened),
    )
    assert first.status == RunStatus.DONE
    scenario.configures("private", policy={"feedback_plan": "approve"}, trust={"trusted_reviewers": ["alice"]})
    fetched(git_pool)

    run_id = feedback_planned(scenario, github_state)

    prompt = (scenario.env.state_dir / "runs" / f"{run_id}.prompt").read_text()
    assert f"`repo`, as of `origin/{BRANCH}`:" in prompt
    assert outline_of(prompt)[:3] == ["docs/", "  guide/", "    rounding.md"]


def test_a_tasks_prompt_holds_its_bases_tree_opened_by_the_tasks_text(
    canopy_env: CanopyEnv,
    git_pool: GitPool,
    tmp_path: Path,
) -> None:
    tracked(git_pool.origin, git_pool.slots, tmp_path, FILES)
    canopy_env.append_user("\n[index]\noutline = 'tree'\noutline_chars = 500\n")
    ctx = inline_context(canopy_env)
    assert operator("task", "submit", "Find out why invoice totals round the wrong way.") == 0

    with in_tick(ctx.conn) as tick_id:
        [started] = task_starts.start_queued(ctx, tick_id, logs.for_tick(tick_id))

    run = present(tasks.get_run(ctx.conn, started.run_id))
    prompt = task_starts.prompt_file(Path(run.log_path)).read_text()
    assert "`repo`, as of `origin/main`:" in prompt
    assert outline_of(prompt)[:6] == INVOICES
    assert "46 files in all, 42 not listed by name." in prompt


def test_with_the_outline_off_a_tasks_prompt_has_none(canopy_env: CanopyEnv, git_pool: GitPool, tmp_path: Path) -> None:
    tracked(git_pool.origin, git_pool.slots, tmp_path, FILES)
    ctx = inline_context(canopy_env)
    assert operator("task", "submit", "Find out why invoice totals round the wrong way.") == 0

    with in_tick(ctx.conn) as tick_id:
        [started] = task_starts.start_queued(ctx, tick_id, logs.for_tick(tick_id))

    run = present(tasks.get_run(ctx.conn, started.run_id))
    prompt = task_starts.prompt_file(Path(run.log_path)).read_text()
    assert OUTLINE_HEADING not in prompt
    assert "services" not in prompt
