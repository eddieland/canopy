"""A worker's prompt as its run sends it: its fixed instructions as the agent's body, the run's own as the message.

Runs of one kind share the body, and so the snapshot that holds it and the prefix the provider caches (DESIGN §13).
"""

import json
from pathlib import Path
from typing import NamedTuple

import pytest

from canopy.core import prompts
from canopy.core.vocab import ResumeReason, RunKind
from canopy.runtime import agents
from tests.canopy.helpers import LABEL, commit_and_push, private_worker_does
from tests.canopy.scenario_helpers import Ran, Scenario, Worker, dispatches, pushes
from tests.conftest import GitPool

#: What the shipped worker definitions end with when a run gives them no body: the stub, after the frontmatter.
STUB = 'Your task is the prompt canopy starts this run with. If it is not a "# canopy worker" prompt, print\n'


class Sent(NamedTuple):
    """What the fake agent was started with for one run: its message, and the snapshot it loaded."""

    message: str
    snapshot: Path

    def definition(self, agent: str) -> str:
        """The definition of `agent` in the snapshot."""
        return (self.snapshot / "agents" / f"{agent}.md").read_text()


def body_of(ran: Ran) -> str:
    """The fixed instructions of `ran`'s prompt, which it has."""
    body = prompts.split(ran.prompt).body
    assert body is not None, ran.prompt
    return body


def sent(agent_log: Path, ran: Ran) -> Sent:
    """What `ran`'s worker was started with."""
    entries = [json.loads(line) for line in agent_log.read_text().splitlines()]
    [entry] = [e for e in entries if e["env"].get("CANOPY_RUN_ID") == str(ran.id)]
    # The tests' templates pass the prompt last, and the snapshot as OpenCode's config directory.
    return Sent(str(entry["argv"][-1]), Path(entry["env"]["OPENCODE_CONFIG_DIR"]))


def worker(key: str, branch: str, *, private: bool) -> Worker:
    """A worker that pushes `branch` and reports done, the private one for a private ticket."""
    if not private:
        return pushes(branch)
    result: dict[str, object] = {"status": "done", "summary": "did it", "branch": branch}
    return private_worker_does(*commit_and_push(branch, f"{key}: the change"), result=result)


@pytest.mark.parametrize("private", [False, True])
def test_two_runs_of_a_kind_share_their_body_and_snapshot_and_are_sent_only_their_own(
    scenario: Scenario,
    git_pool: GitPool,
    agent_log: Path,
    *,
    private: bool,
) -> None:
    if private:
        scenario.seen("PROJ-2")
        for key in ("PROJ-1", "PROJ-2"):
            scenario.operator("start", key)
    # A started ticket needs no label: its start record authorizes it.
    label = None if private else LABEL
    first = scenario.run(
        dispatches("PROJ-1", label=label),
        worker=worker("PROJ-1", "agent/PROJ-1-work", private=private),
    )
    second = scenario.run(
        dispatches("PROJ-2", label=label, slug="other"),
        worker=worker("PROJ-2", "agent/PROJ-2-other", private=private),
    )
    assert body_of(first) == body_of(second)
    for ran in (first, second):
        # The fixed instructions hold nothing of a run's own: no ticket, branch, or slot.
        assert ran.key not in body_of(ran)
        assert str(ran.branch) not in body_of(ran)
        assert "/pool" not in body_of(ran)
        message = prompts.split(ran.prompt).message
        assert message.startswith(f"## Run\n\nYou are working ticket {ran.key} in ")
        assert sent(agent_log, ran).message == message
    # Both loaded one snapshot, whose definition holds the fixed instructions as its body.
    assert sent(agent_log, first).snapshot == sent(agent_log, second).snapshot
    agent = agents.PRIVATE_WORKER if private else agents.WORKER
    assert sent(agent_log, first).definition(agent).endswith(f"---\n\n{body_of(first)}")


def test_a_resume_has_a_body_of_its_own_whatever_its_reasons(
    scenario: Scenario,
    git_pool: GitPool,
    agent_log: Path,
) -> None:
    implemented = scenario.run(dispatches(), worker=pushes())
    ci = scenario.run(dispatches(kind=RunKind.RESUME, reasons=[ResumeReason.CI]), worker=pushes())
    found = sent(agent_log, ci)
    review = scenario.run(dispatches(kind=RunKind.RESUME, reasons=[ResumeReason.REVIEW]), worker=pushes())
    assert body_of(ci) == body_of(review) != body_of(implemented)
    assert "This is attempt" not in body_of(ci)
    assert found.snapshot == sent(agent_log, review).snapshot != sent(agent_log, implemented).snapshot


def test_an_override_without_the_marker_is_sent_whole_with_the_definitions_stub(
    scenario: Scenario,
    git_pool: GitPool,
    agent_log: Path,
) -> None:
    overrides = scenario.env.user_file.parent / "prompts"
    overrides.mkdir()
    (overrides / prompts.WORKER[RunKind.IMPLEMENT]).write_text(
        "# canopy worker\n\nWork {{KEY}} for {{LABELS}}.{{DRAFTS}}\n",
    )
    ran = scenario.run(dispatches(), worker=pushes())
    assert sent(agent_log, ran).message == ran.prompt
    assert ran.prompt.startswith("# canopy worker\n\nWork PROJ-1 for `agent-ready-tester`.")
    assert f"---\n\n{STUB}" in sent(agent_log, ran).definition(agents.WORKER)
