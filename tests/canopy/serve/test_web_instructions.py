"""The settings' instructions page's API (DESIGN §12, TRUST_MODEL T8): each agent's file read, saved, and deleted.

Only an agent's own file, the one its key names or its default, never which file, with the core's guards, and the kept
versions of each.
"""

import dataclasses
import hashlib
import os
from pathlib import Path
from unittest import mock

from canopy.core import conversation, prompts, standing
from canopy.core.context import Context
from tests.canopy.web_helpers import refused, signed_in_client

RULES = "Commit review fixes as new commits.\n"


def instructed(ctx: Context, worker: Path, defaults: Path) -> Context:
    """`ctx` with `paths.worker_instructions` naming `worker`, and the other agents' defaults in `defaults`."""
    paths = ctx.config.paths.model_copy(update={"worker_instructions": worker, "instructions": defaults})
    return dataclasses.replace(ctx, config=ctx.config.model_copy(update={"paths": paths}))


def sha(text: str) -> str:
    """The hash a read of a file holding `text` gives."""
    return hashlib.sha256(text.encode()).hexdigest()


def test_the_page_reads_each_agents_file_and_saves_one_over_the_version_it_read(ctx: Context, tmp_path: Path) -> None:
    path = tmp_path / "worker.md"
    path.write_text(RULES)
    defaults = tmp_path / "instructions"
    c, headers = signed_in_client(instructed(ctx, path, defaults))

    listed = c.get("/api/instructions").json()
    assert listed["max_bytes"] == prompts.MAX_STANDING_BYTES
    assert [f["agent"] for f in listed["files"]] == ["worker", "overseer", "reviewer", "chore"]
    assert listed["files"][0] == {
        "agent": "worker",
        "key": "paths.worker_instructions",
        "path": str(path),
        "source": "config",
        "text": RULES,
        "sha256": sha(RULES),
        "problem": None,
        "missing": False,
        "versions": 0,
    }
    assert listed["files"][1] == {
        "agent": "overseer",
        "key": "paths.overseer_instructions",
        "path": str(defaults / "overseer.md"),
        "source": "default",
        "text": None,
        "sha256": None,
        "problem": None,
        "missing": True,
        "versions": 0,
    }

    saved = c.put("/api/instructions/worker", json={"text": "Run the linters.", "sha256": sha(RULES)}, headers=headers)
    assert saved.status_code == 200, saved.text
    assert (saved.json()["text"], saved.json()["versions"]) == ("Run the linters.\n", 1)
    assert path.read_text() == "Run the linters.\n"

    # The same read again is stale now; the file is left as the first save wrote it.
    again = c.put("/api/instructions/worker", json={"text": "Something else", "sha256": sha(RULES)}, headers=headers)
    assert refused(again).startswith("stale: ")
    assert path.read_text() == "Run the linters.\n"

    versions = c.get("/api/instructions/worker/versions").json()
    assert versions["keep"] == standing.KEEP_VERSIONS
    assert [(v["kind"], v["text"], v["sha256"]) for v in versions["versions"]] == [("edit", RULES, sha(RULES))]


def test_a_default_is_made_and_deleted_and_a_file_a_key_names_is_not(ctx: Context, tmp_path: Path) -> None:
    path = tmp_path / "worker.md"
    path.write_text(RULES)
    defaults = tmp_path / "instructions"
    c, headers = signed_in_client(instructed(ctx, path, defaults))

    made = c.put("/api/instructions/overseer", json={"text": "Dispatch urgent first."}, headers=headers)
    assert made.status_code == 200, made.text
    assert (defaults / "overseer.md").read_text() == "Dispatch urgent first.\n"

    gone = c.post("/api/instructions/overseer/delete", json={"sha256": made.json()["sha256"]}, headers=headers)
    assert gone.status_code == 200, gone.text
    assert (gone.json()["missing"], gone.json()["versions"]) == (True, 1)
    assert not (defaults / "overseer.md").exists()
    assert c.get("/api/instructions/overseer/versions").json()["versions"][0]["kind"] == "delete"

    kept = c.post("/api/instructions/worker/delete", json={"sha256": sha(RULES)}, headers=headers)
    assert refused(kept).startswith("configured: ")
    assert path.read_text() == RULES


def test_a_change_inside_a_run_is_refused(ctx: Context, tmp_path: Path) -> None:
    path = tmp_path / "worker.md"
    c, headers = signed_in_client(instructed(ctx, path, tmp_path / "instructions"))

    with mock.patch.dict(os.environ, {conversation.RUN_ID_ENV: "7"}):
        inside = c.put("/api/instructions/worker", json={"text": RULES}, headers=headers)
        assert refused(inside).startswith("inside_run: ")
    assert not path.exists()


def test_an_agent_the_page_does_not_know_is_not_a_file(ctx: Context) -> None:
    c, headers = signed_in_client(ctx)

    assert c.put("/api/instructions/planner", json={"text": RULES}, headers=headers).status_code == 422
