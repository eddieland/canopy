"""The skills page's read (DESIGN §13): every skill the runtime finds, where its file is, and its text."""

import json
from pathlib import Path

from canopy.core.context import Context
from canopy.serve.backend import Backend
from tests.canopy.web_helpers import SECRET, client, signed_in, signed_in_client


def test_each_skill_is_listed_with_its_file_and_its_text_from_one_start_of_the_runtime(
    ctx: Context,
    opencode_state: Path,
) -> None:
    root = ctx.ws.root
    linked = root / "linked-skills"
    linked.symlink_to(Path.home() / ".config" / "opencode" / "skills")
    release = {
        "name": "release-notes",
        "description": "When to add a changelog line.",
        "location": str(root / ".opencode" / "skills" / "release-notes" / "SKILL.md"),
        "content": "# Release notes\n\nAdd a line under `Unreleased`.\n",
    }
    skills = [
        release,
        # Through a link to the operator's own, as OpenCode 2's snapshot reaches their config: theirs, not the root's.
        {"name": "terse", "location": str(linked / "terse" / "SKILL.md"), "content": "Be brief.\n"},
        {"name": "tracker-jira", "location": str(ctx.ws.state_dir / "defs" / "skills" / "tracker-jira" / "SKILL.md")},
        {"name": "outside", "location": "/opt/skills/outside/SKILL.md"},
        # A file the runtime did not name: not mistaken for one it carries.
        {"name": "unplaced", "location": ""},
        "customize-opencode",
    ]
    opencode_state.write_text(json.dumps({"skills": skills}))
    c, _ = signed_in_client(ctx)

    found = c.get("/api/skills").json()
    assert found["error"] is None
    by_name = {s["name"]: s for s in found["skills"]}
    assert list(by_name) == ["customize-opencode", "outside", "release-notes", "terse", "tracker-jira", "unplaced"]
    assert [(s["source"], s["path"]) for s in found["skills"]] == [
        ("built-in", "x"),
        ("other", "/opt/skills/outside/SKILL.md"),
        ("workspace", ".opencode/skills/release-notes/SKILL.md"),
        ("home", "~/.config/opencode/skills/terse/SKILL.md"),
        ("canopy", ".canopy/defs/skills/tracker-jira/SKILL.md"),
        ("other", ""),
    ]
    notes = by_name["release-notes"]
    assert (notes["description"], notes["body"]) == (release["description"], release["content"])
    assert by_name["terse"]["description"] is None
    # The skills alone: one `debug skill`, and no agent's rules, which would start the runtime once for each agent.
    started = [json.loads(line)["argv"] for line in (opencode_state.parent / "opencode.jsonl").read_text().splitlines()]
    assert started == [["debug", "skill"]]


def test_a_runtime_that_cannot_list_its_skills_is_the_error(ctx: Context, opencode_state: Path) -> None:
    opencode_state.write_text(json.dumps({"exit": 1, "stderr": "Error: bad config: token = ghp_s3cret\n"}))
    c, _ = signed_in_client(ctx)
    found = c.get("/api/skills").json()
    assert found == {"skills": [], "error": "`opencode debug skill` exited 1; run it to see why"}


def test_the_mock_lists_a_skill_from_each_place_one_comes_from(backend: Backend) -> None:
    c = client(None, backend, key=SECRET)
    signed_in(c)
    found = c.get("/api/skills").json()
    assert found["error"] is None
    assert [(s["name"], s["source"]) for s in found["skills"]] == [
        ("canopy-artifacts", "canopy"),
        ("release-notes", "workspace"),
        ("terse", "home"),
        ("tracker-jira", "canopy"),
        ("write-a-skill", "built-in"),
    ]
    assert found["skills"][0]["path"] == ".canopy/definitions-3f9c2a71/skills/canopy-artifacts/SKILL.md"
