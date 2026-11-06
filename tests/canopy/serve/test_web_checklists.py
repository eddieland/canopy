"""The checklists page's read (DESIGN §42): each mapped repository's list, as the next worker run in it would hear it.

Read from the operator's files when asked, and changing nothing.
"""

from typing import Any

from canopy.core import db
from canopy.infra import resources
from canopy.serve.backend import Backend
from tests.canopy.helpers import checklists_dir, context
from tests.canopy.web_helpers import client, signed_in_client
from tests.conftest import REPO_NAME, CanopyEnv

#: A list of two items, the second with every optional line.
LIST = """\
## general-types
A parameter takes the most general type its body needs.

## migration-companion
paths: migrations/, tests/**/migrations/
severity: major

A new migration has its companion.
Passes: both files. Fails: a migration alone.
"""


def test_without_a_directory_no_repository_has_a_list(canopy_env: CanopyEnv) -> None:
    """`paths.checklists` unset: each repository is listed, with no file and nothing asked of it."""
    found = read(canopy_env)
    assert found == {"directory": None, "repos": [{"repo": REPO_NAME, "file": None, "items": [], "error": None}]}


def test_each_item_is_read_from_the_file_as_a_run_reads_it_and_an_edit_shows_at_once(canopy_env: CanopyEnv) -> None:
    """Its id, paths, severity (`minor` unless named), and rule, in the list's order; read again on every ask."""
    directory = checklists_dir(canopy_env)
    ctx = context(canopy_env)
    db.migrate(ctx.conn, resources.migrations_dir())
    c, _ = signed_in_client(ctx)
    # A repository without a file is listed with none.
    assert c.get("/api/checklists").json()["repos"] == [
        {"repo": REPO_NAME, "file": str(directory / f"{REPO_NAME}.md"), "items": [], "error": None},
    ]
    (directory / f"{REPO_NAME}.md").write_text(LIST)
    found = c.get("/api/checklists").json()
    assert found["directory"] == str(directory)
    [repo] = found["repos"]
    assert repo["error"] is None
    assert repo["items"] == [
        {
            "id": "general-types",
            "paths": [],
            "severity": "minor",
            "rule": "A parameter takes the most general type its body needs.",
        },
        {
            "id": "migration-companion",
            "paths": ["migrations/", "tests/**/migrations/"],
            "severity": "major",
            "rule": "A new migration has its companion.\nPasses: both files. Fails: a migration alone.",
        },
    ]
    (directory / f"{REPO_NAME}.md").write_text("## no-any\nNo `any`.\n")
    assert [i["id"] for i in c.get("/api/checklists").json()["repos"][0]["items"]] == ["no-any"]


def test_a_list_canopy_cannot_use_says_why_as_its_runs_refusal_would(canopy_env: CanopyEnv) -> None:
    """No items, and the parser's reason, which names the file: a run in the repository is refused for it."""
    directory = checklists_dir(canopy_env)
    (directory / f"{REPO_NAME}.md").write_text("Some notes first.\n\n## general-types\nA rule.\n")
    [repo] = read(canopy_env)["repos"]
    assert repo["items"] == []
    assert repo["error"] == (
        f"the checklist of {REPO_NAME} at {directory / f'{REPO_NAME}.md'}: line 1: each item opens with a '## <id>' "
        "heading"
    )


def test_the_mock_keeps_the_lists_its_runs_answered(backend: Backend) -> None:
    """`api`'s and `web`'s, whose ids are the items the checklist's counts count; `mobile` none."""
    c = client(None, backend)
    found = c.get("/api/checklists").json()
    assert [(r["repo"], len(r["items"]), r["error"]) for r in found["repos"]] == [
        ("api", 4, None),
        ("mobile", 0, None),
        ("web", 4, None),
    ]
    counted = c.get("/api/reports/checklist").json()["items"]
    listed = [(r["repo"], i["id"]) for r in found["repos"] for i in r["items"]]
    assert listed == [(row["repo"], row["item"]) for row in counted]


def test_the_mocks_held_run_shows_what_it_pushed_after_its_list(backend: Backend) -> None:
    """ABC-103's run, which fixed `query-keys`, keeps the stretch's diff; the mock's other runs keep none."""
    c = client(None, backend)
    [stretch] = c.get("/api/runs/38").json()["checklist_stretches"]
    assert stretch["repo"] == "web"
    assert stretch["diff"] is not None
    assert [f["path"] for f in stretch["diff"]["files"]] == ["src/api/queries.ts", "src/billing/InvoiceLines.tsx"]
    assert c.get("/api/runs/39").json()["checklist_stretches"] == []


def read(env: CanopyEnv) -> dict[str, Any]:
    """What `GET /api/checklists` answers over `env`'s workspace, its config read now."""
    ctx = context(env)
    db.migrate(ctx.conn, resources.migrations_dir())
    c, _ = signed_in_client(ctx)
    found = c.get("/api/checklists").json()
    assert isinstance(found, dict)
    return found
