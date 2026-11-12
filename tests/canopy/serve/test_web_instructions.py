"""The settings page's standing instructions files (DESIGN §12, TRUST_MODEL T8): each agent's read, and its text saved.

Only the text of a file the loop's config names is written, never which file, with the core save's guards.
"""

import dataclasses
import hashlib
import os
from pathlib import Path
from unittest import mock

from canopy.core import conversation, prompts
from canopy.core.context import Context
from tests.canopy.web_helpers import refused, signed_in_client

RULES = "Commit review fixes as new commits.\n"


def instructed(ctx: Context, path: Path) -> Context:
    """`ctx` with `paths.worker_instructions` naming `path`."""
    paths = ctx.config.paths.model_copy(update={"worker_instructions": path})
    return dataclasses.replace(ctx, config=ctx.config.model_copy(update={"paths": paths}))


def test_the_page_reads_each_agents_file_and_saves_one_over_the_version_it_read(ctx: Context, tmp_path: Path) -> None:
    path = tmp_path / "worker.md"
    path.write_text(RULES)
    c, headers = signed_in_client(instructed(ctx, path))
    read_sha = hashlib.sha256(RULES.encode()).hexdigest()

    listed = c.get("/api/instructions").json()
    assert listed["max_bytes"] == prompts.MAX_STANDING_BYTES
    assert [f["agent"] for f in listed["files"]] == ["worker", "overseer", "reviewer", "chore"]
    assert listed["files"][0] == {
        "agent": "worker",
        "key": "paths.worker_instructions",
        "path": str(path),
        "text": RULES,
        "sha256": read_sha,
        "problem": None,
        "missing": False,
    }
    assert listed["files"][1] == {
        "agent": "overseer",
        "key": "paths.overseer_instructions",
        "path": None,
        "text": None,
        "sha256": None,
        "problem": None,
        "missing": False,
    }

    saved = c.put("/api/instructions/worker", json={"text": "Run the linters.", "sha256": read_sha}, headers=headers)
    assert saved.status_code == 200, saved.text
    assert saved.json()["text"] == "Run the linters.\n"
    assert path.read_text() == "Run the linters.\n"

    # The same read again is stale now; the file is left as the first save wrote it.
    again = c.put("/api/instructions/worker", json={"text": "Something else", "sha256": read_sha}, headers=headers)
    assert refused(again).startswith("stale: ")
    assert path.read_text() == "Run the linters.\n"


def test_a_save_the_config_names_no_file_for_or_inside_a_run_is_refused(ctx: Context, tmp_path: Path) -> None:
    path = tmp_path / "worker.md"
    c, headers = signed_in_client(instructed(ctx, path))

    assert refused(c.put("/api/instructions/chore", json={"text": RULES}, headers=headers)).startswith("not_set: ")
    with mock.patch.dict(os.environ, {conversation.RUN_ID_ENV: "7"}):
        inside = c.put("/api/instructions/worker", json={"text": RULES}, headers=headers)
        assert refused(inside).startswith("inside_run: ")
    assert not path.exists()


def test_an_agent_the_page_does_not_know_is_not_a_file(ctx: Context) -> None:
    c, headers = signed_in_client(ctx)

    assert c.put("/api/instructions/planner", json={"text": RULES}, headers=headers).status_code == 422
