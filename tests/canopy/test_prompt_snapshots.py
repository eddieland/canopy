"""Each bundled prompt and agent definition, held by a snapshot of it as an agent receives it.

A snapshot shows in a PR's diff what a change to a prompt does to the text an agent reads, its placeholders filled. So
every file under `.agents/prompts/` and `.agents/agents/` has one, and this test names it: a new prompt fails here until
a snapshot test renders it and `HELD_BY` names that snapshot.
"""

from pathlib import Path

from canopy.runtime import definitions as runtime_definitions

#: Where the bundled files sit in a checkout. `HELD_BY` names each by its path relative to this.
AGENTS = Path(__file__).resolve().parents[2] / ".agents"
#: The directories whose every file has a snapshot: what agent runs read as their prompt and their definition.
HELD = ("agents", "prompts")
#: Where the snapshots sit. `HELD_BY` names each by its path relative to this.
TESTS = Path(__file__).resolve().parent
#: The snapshot of an agent's definition as rendered, by the agent's name.
DEFINITION = "core/__snapshots__/test_definitions/test_each_agent_definition_as_rendered[{}].md"
#: Each bundled prompt and agent definition, and a snapshot that holds it rendered. The overseer's prompt reaches its
#: agent only inside its definition, so the definition's snapshot holds it.
HELD_BY: dict[str, str] = {
    "prompts/overseer.md": DEFINITION.format("canopy-overseer"),
    "prompts/reviewer.md": "reviews/__snapshots__/test_reviews/test_the_reviewer_prompt[defaults].md",
    **{
        f"prompts/worker-{kind}.md": (
            f"core/__snapshots__/test_memory_prompts/test_with_memory_off_every_worker_prompt_is_as_it_was[{kind}].md"
        )
        for kind in ("implement", "implement-private", "plan", "resume", "resume-private")
    },
    **{f"agents/{name}.md": DEFINITION.format(name) for name in runtime_definitions.agent_names()},
}


def test_each_prompt_and_agent_definition_has_a_snapshot() -> None:
    bundled = {path.relative_to(AGENTS).as_posix() for held in HELD for path in (AGENTS / held).iterdir()}
    unheld = sorted(bundled - HELD_BY.keys())
    assert not unheld, (
        f"no snapshot holds {', '.join(unheld)}: add a snapshot test that renders it as its agent receives it, and "
        "name the snapshot in HELD_BY"
    )
    assert not HELD_BY.keys() - bundled


def test_each_snapshot_holds_the_file_it_is_named_for() -> None:
    for name, snapshot in HELD_BY.items():
        path = TESTS / snapshot
        assert path.is_file(), f"{name}: {snapshot} is missing; `make snapshots` records it"
        # A prompt's title is its first line; a definition's, its description.
        lines = (AGENTS / name).read_text(encoding="utf-8").splitlines()
        title = lines[0] if name.startswith("prompts/") else next(x for x in lines if x.startswith("description:"))
        assert title in path.read_text(encoding="utf-8").splitlines(), f"{snapshot} does not hold {name}"
