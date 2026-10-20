"""The operator's standing instructions to the overseer (DESIGN §12): `paths.overseer_instructions` is rendered into the
overseer's prompt, never a worker's, and a file that cannot be used fails the tick instead of dropping them."""

from pathlib import Path

import pytest

from canopy.core import config, definitions, prompts
from canopy.core.vocab import TickStatus
from tests.canopy.helpers import PROMPT_VALUES, agent_runs
from tests.canopy.scenario_helpers import Scenario
from tests.conftest import CanopyEnv

URGENT = "Dispatch tickets labeled urgent before any other."
SECTION = "## Standing instructions from the operator\n\n"


def instruct(scenario: Scenario, text: str | bytes) -> Path:
    """Write the operator's instructions to the overseer and point `paths.overseer_instructions` at them."""
    path = scenario.env.user_file.parent / "overseer-instructions.md"
    path.parent.mkdir(parents=True, exist_ok=True)
    if isinstance(text, bytes):
        path.write_bytes(text)
    else:
        path.write_text(text)
    scenario.configures(paths={"overseer_instructions": str(path)})
    return path


def definition_of(env: CanopyEnv) -> str:
    snapshot = definitions.ensure(env.state_dir, config.load(env.root, env.user_file))
    return (snapshot / "agents" / "canopy-overseer.md").read_text()


def test_the_operators_instructions_reach_the_overseer(scenario: Scenario) -> None:
    instruct(scenario, f"\n{URGENT}\n\n")
    scenario.tick(dry_run=True)
    [run] = agent_runs(scenario.agent_log)
    env = run["env"]
    assert isinstance(env, dict)
    definition = (Path(env["OPENCODE_CONFIG_DIR"]) / "agents" / "canopy-overseer.md").read_text()
    assert f"{SECTION}{URGENT}\n\nThe operator set these" in definition
    # Not in the tick's message: the prompt is the cached system prompt (DESIGN §6).
    argv = run["argv"]
    assert isinstance(argv, list)
    assert URGENT not in argv[-1]


@pytest.mark.parametrize("blank", [False, True])
def test_without_instructions_there_is_no_section(scenario: Scenario, *, blank: bool) -> None:
    if blank:
        instruct(scenario, " \n\n")
    definition = definition_of(scenario.env)
    assert SECTION not in definition
    assert "Behave exactly as you would otherwise.\n" in definition


def test_an_override_with_the_old_placeholder_gets_the_text_alone(scenario: Scenario) -> None:
    # One written before `{{STANDING_SECTION}}` holds its own heading and framing around `{{STANDING_INSTRUCTIONS}}`.
    overrides = scenario.env.user_file.parent / "prompts"
    overrides.mkdir(parents=True)
    (overrides / "overseer.md").write_text("# my overseer\n\n## Mine\n\n{{STANDING_INSTRUCTIONS}}\n")
    assert "## Mine\n\nNone.\n" in definition_of(scenario.env)
    instruct(scenario, URGENT)
    assert f"## Mine\n\n{URGENT}\n" in definition_of(scenario.env)


@pytest.mark.parametrize(
    ("text", "error"),
    [
        (None, "cannot read overseer instructions"),
        (b"\xff\xfe not UTF-8\n", "cannot read overseer instructions"),
        ("x" * (prompts.MAX_STANDING_BYTES + 1), f"over {prompts.MAX_STANDING_BYTES}"),
    ],
    ids=["missing", "not-utf8", "too-large"],
)
def test_instructions_that_cannot_be_used_fail_the_tick(
    scenario: Scenario, text: str | bytes | None, error: str
) -> None:
    # The operator set them for the overseer; one that ran without them would decide as if they were never written.
    path = instruct(scenario, text if text is not None else "")
    if text is None:
        path.unlink()
    ticked = scenario.tick(dry_run=True, code=1)
    assert ticked.tick.status == TickStatus.OVERSEER_FAILED
    assert error in (ticked.tick.summary or "")
    assert agent_runs(scenario.agent_log) == []


@pytest.mark.parametrize("instructed", [False, True])
def test_an_override_without_the_placeholder_fails_closed_once_instructions_are_set(
    scenario: Scenario,
    instructed: bool,  # noqa: FBT001  (a parametrized fixture)
) -> None:
    # An override written before the placeholder existed keeps serving an operator who sets no instructions.
    if instructed:
        instruct(scenario, URGENT)
    overrides = scenario.env.user_file.parent / "prompts"
    overrides.mkdir(parents=True)
    (overrides / "overseer.md").write_text("# my overseer\n\nKeep {{THIS}} as it is.\n")
    cfg = config.load(scenario.env.root, scenario.env.user_file)
    if not instructed:
        assert "Keep {{THIS}} as it is." in prompts.render_overseer(cfg)
        return
    with pytest.raises(
        definitions.DefinitionsError,
        match=r"missing required placeholder \{\{STANDING_SECTION\}\} or \{\{STANDING_INSTRUCTIONS",
    ):
        definitions.ensure(scenario.env.state_dir, cfg)


@pytest.mark.parametrize("kind", ["implement", "resume"])
def test_the_overseers_instructions_never_reach_a_worker(scenario: Scenario, kind: str) -> None:
    instruct(scenario, URGENT)
    text = prompts.render_worker(config.load(scenario.env.root, scenario.env.user_file), kind, PROMPT_VALUES)
    assert SECTION not in text
    assert URGENT not in text
