"""The outline of its repositories' code in a worker's prompt (DESIGN §46, ROADMAP M70 stage 1).

At `index.outline = "tree"` an `implement`'s and a `resume`'s prompt holds a directory tree of each repository the run
works in, opened by the ticket's words or by what the branch changed; at `off`, the default, it holds none.
"""

import json
import sqlite3
from collections.abc import Sequence
from pathlib import Path

from canopy.core import db
from canopy.core.vocab import ResumeReason, RunKind, RunStatus
from canopy.runs import outlines
from tests.canopy.conftest import Ws
from tests.canopy.helpers import BRANCH, KEY, LABEL, commit_and_push, context, worker_does
from tests.canopy.scenario_helpers import Scenario, dispatches, pushes
from tests.conftest import TRACKER_SOURCE, CanopyEnv, GitPool, git

HEADING = "## Code outline"
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


def tracked(origin: Path, slots: Sequence[Path], tmp_path: Path, files: Sequence[str] = FILES) -> None:
    """Commit `files` to `origin`'s `main`, and fetch it in each of `slots`, as a pool's lease does."""
    work = tmp_path / f"tracked-{origin.stem}"
    git("clone", "--quiet", str(origin), str(work), cwd=tmp_path)
    for name in files:
        (work / name).parent.mkdir(parents=True, exist_ok=True)
        (work / name).write_text(f"{name}\n")
    git("add", ".", cwd=work)
    git("commit", "--quiet", "-m", "the code", cwd=work)
    git("push", "--quiet", "origin", "HEAD:main", cwd=work)
    for slot in slots:
        git("fetch", "--quiet", "origin", cwd=slot)


def ticket_says(connector_state: Path, title: str, body: str = "") -> None:
    """The tracker holds KEY, open and labeled, titled `title` with the description `body`."""
    line = {"kind": "ticket", "key": KEY, "title": title, "body": body, "state": "open", "labels": [{"name": LABEL}]}
    connector_state.write_text(json.dumps({TRACKER_SOURCE: {"lines": [line]}}))


def outline_of(prompt: str) -> list[str]:
    """The tree's lines in `prompt`, each without its quote mark."""
    section = prompt.partition(f"{HEADING}\n")[2]
    return [line.removeprefix("> ") for line in section.splitlines() if line.startswith("> ")]


def test_with_the_outline_off_a_prompt_has_none(scenario: Scenario, git_pool: GitPool, tmp_path: Path) -> None:
    tracked(git_pool.origin, git_pool.slots, tmp_path)

    run = scenario.run(worker=pushes())

    assert run.status == RunStatus.DONE
    assert HEADING not in run.prompt
    assert "services" not in run.prompt


def test_an_implements_prompt_holds_its_bases_tree_opened_by_the_tickets_words(
    scenario: Scenario,
    git_pool: GitPool,
    connector_state: Path,
    tmp_path: Path,
) -> None:
    tracked(git_pool.origin, git_pool.slots, tmp_path)
    scenario.configures(**TREE)
    ticket_says(connector_state, "Invoice totals round the wrong way", "Seen on every `InvoiceRenderer` since May.")

    run = scenario.run(worker=pushes())

    assert run.status == RunStatus.DONE
    assert "`repo`, as of `origin/main`:" in run.prompt
    shown = outline_of(run.prompt)
    # The directory the ticket names is open to its files; the others are a name and a count.
    assert shown[:6] == [
        "services/",
        "  billing/",
        "    invoices/",
        "      render.py",
        "      totals.py",
        "    ledger.py",
    ]
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
    tracked(git_pool.origin, git_pool.slots, tmp_path)
    scenario.configures(**TREE)
    ticket_says(connector_state, "Invoice totals round the wrong way")
    adds = [["mkdir", "-p", "docs/guide"], ["touch", "docs/guide/rounding.md"], ["git", "add", "docs"]]
    first = scenario.run(worker=worker_does(*adds, *commit_and_push(BRANCH)))
    assert first.status == RunStatus.DONE
    # Every slot of a real pool shares one git directory, so each holds the branch the first run pushed.
    for slot in git_pool.slots:
        git("fetch", "--quiet", "origin", cwd=slot)

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
    assert run.prompt.count(HEADING) == 1
    api, _, web = run.prompt.partition(f"{HEADING}\n")[2].partition("`web`, as of `origin/main`:")
    assert "`api`, as of `origin/main`:" in api
    assert outline_of(HEADING + "\n" + api) == ["api/", "  handlers.py", "  models.py"]
    assert outline_of(HEADING + "\n" + web) == ["web/", "  handlers.py", "  models.py"]


def test_excluded_files_are_left_out_of_a_prompts_outline(
    scenario: Scenario,
    git_pool: GitPool,
    tmp_path: Path,
) -> None:
    tracked(git_pool.origin, git_pool.slots, tmp_path)
    scenario.configures(index={"outline": "tree", "exclude": ["services/shipping/", "vendor/", "**/*.md"]})

    run = scenario.run(worker=pushes())

    shown = outline_of(run.prompt)
    assert shown == ["services/", "  billing/", "    invoices/", "      render.py", "      totals.py", "    ledger.py"]
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


def test_a_plan_gets_no_outline_yet(
    canopy_env: CanopyEnv,
    conn: sqlite3.Connection,
    git_pool: GitPool,
    tmp_path: Path,
) -> None:
    del conn  # the journal, migrated
    tracked(git_pool.origin, git_pool.slots, tmp_path)
    canopy_env.append_user("\n[index]\noutline = 'tree'\n")
    ctx = context(canopy_env)
    slot = db.RunSlot(repo="repo", slot_path=git_pool.slots[0], lease_id="1", lease_holder="h", base_branch="main")

    assert outlines.for_run(ctx, 1, KEY, RunKind.PLAN, branch=BRANCH, slots=[slot]) == ""
    assert HEADING in outlines.for_run(ctx, 1, KEY, RunKind.IMPLEMENT, branch=BRANCH, slots=[slot])
