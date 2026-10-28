"""Attachments (DESIGN §22): text files the operator attaches to a ticket or a task, held to `policy`'s limits."""

import io
import stat
import sys
from pathlib import Path
from typing import Final
from unittest import mock

import pytest

from canopy.core import attachments, config, conversation
from canopy.core.conversation import Ref
from tests.canopy.helpers import present
from tests.canopy.scenario_helpers import Scenario
from tests.conftest import CanopyEnv

DOC: Final = "# Importer\n\nShard the queue by tenant.\n"
TASK: Final = Ref(conversation.TASK, "1")


@pytest.fixture
def doc(tmp_path: Path) -> Path:
    """A design doc as a person sent it, under a name with a space and parentheses."""
    path = tmp_path / "Importer design (v2).md"
    path.write_text(DOC)
    return path


def text_file(tmp_path: Path, name: str, data: bytes) -> Path:
    path = tmp_path / name
    path.write_bytes(data)
    return path


def test_a_file_attached_to_a_task_is_kept_for_the_operator_alone_and_shown(scenario: Scenario, doc: Path) -> None:
    scenario.operator("task", "submit", "Review the attached design against the code.")
    printed = scenario.operator("attach", "task:1", str(doc))
    assert "Attached Importer-design-v2.md (39 bytes) to task:1; its next run reads it." in printed.out
    [attached] = attachments.of(scenario.conn, TASK)
    assert (attached.name, attached.size, attached.channel, attached.removed_at) == (
        "Importer-design-v2.md",
        39,
        "cli",
        None,
    )
    path = attachments.path(scenario.env.state_dir, attached)
    assert path.read_text() == DOC
    assert stat.S_IMODE(path.stat().st_mode) == 0o600
    assert stat.S_IMODE(path.parent.stat().st_mode) == 0o700
    shown = scenario.operator("show", "task:1").out
    assert "Attachments (1):\n  Importer-design-v2.md  39 bytes  attached" in shown


def test_a_ticket_canopy_knows_takes_an_attachment_and_one_it_does_not_is_refused(
    scenario: Scenario,
    doc: Path,
) -> None:
    scenario.operator("start", "PROJ-1")
    scenario.operator("attach", "PROJ-1", str(doc), "--name", "design.md")
    scenario.seen("PROJ-2")
    scenario.operator("attach", "PROJ-2", str(doc), "--name", "design.md")
    assert (
        "attach refused (unknown): canopy has no record of PROJ-3"
        in scenario.operator(
            "attach",
            "PROJ-3",
            str(doc),
            code=1,
        ).err
    )
    assert [a.name for a in attachments.of(scenario.conn, Ref(conversation.TICKET, "PROJ-1"))] == ["design.md"]
    assert "Attachments (1):\n  design.md" in scenario.operator("show", "PROJ-2").out


@pytest.mark.parametrize(
    ("ref", "said"),
    [
        ("chore:lint", "attach refused (unsupported): chore:lint is a chore, which takes only reply, dismiss, show"),
        ("run:1", "attach refused (unsupported): run:1 is a run, which takes only show"),
        ("task:9", "attach refused (unknown): canopy has no task:9"),
    ],
)
def test_only_a_ticket_or_a_task_takes_an_attachment(scenario: Scenario, doc: Path, ref: str, said: str) -> None:
    assert said in scenario.operator("attach", ref, str(doc), code=1).err


def test_a_stopped_task_takes_no_attachment(scenario: Scenario, doc: Path) -> None:
    scenario.operator("task", "submit", "look")
    scenario.operator("stop", "task:1")
    assert "attach refused (stopped)" in scenario.operator("attach", "task:1", str(doc), code=1).err


@pytest.mark.parametrize(
    ("data", "said"),
    [
        (b"\x89PNG\r\n\x1a\n\xff\xfe", "attach refused (not_text): f.md is not UTF-8 text"),
        (b"text\x00more", "attach refused (not_text): f.md holds a NUL byte"),
        (b" \n\t\n", "attach refused (empty): f.md is empty"),
    ],
)
def test_only_plain_text_is_attached(scenario: Scenario, tmp_path: Path, data: bytes, said: str) -> None:
    scenario.operator("task", "submit", "look")
    assert said in scenario.operator("attach", "task:1", str(text_file(tmp_path, "f.md", data)), code=1).err
    assert attachments.of(scenario.conn, TASK) == []


def test_the_limits_hold_each_file_and_what_a_subject_holds_together(scenario: Scenario, tmp_path: Path) -> None:
    scenario.configures(policy={"max_attachments": 2, "max_attachment_kib": 2, "max_attachments_total_kib": 3})
    scenario.operator("task", "submit", "look")
    kib = b"x" * attachments.KIB
    over = text_file(tmp_path, "big.md", kib * 2 + b"x")
    assert (
        "attach refused (too_large): big.md is over the 2 KiB one attachment may hold"
        in scenario.operator(
            "attach",
            "task:1",
            str(over),
            code=1,
        ).err
    )
    scenario.operator("attach", "task:1", str(text_file(tmp_path, "a.md", kib * 2)))
    said = scenario.operator("attach", "task:1", str(text_file(tmp_path, "b.md", kib + b"x")), code=1).err
    assert "attach refused (too_large): task:1's attachments would hold 3.0 KiB, over the 3 KiB" in said
    scenario.operator("attach", "task:1", str(text_file(tmp_path, "b.md", kib)))
    said = scenario.operator("attach", "task:1", str(text_file(tmp_path, "c.md", b"c")), code=1).err
    assert "attach refused (too_many): task:1 has 2 attachments, the most it may hold; remove one first" in said
    assert [a.name for a in attachments.of(scenario.conn, TASK)] == ["a.md", "b.md"]


def test_attaching_is_off_at_no_attachments(scenario: Scenario, doc: Path) -> None:
    scenario.configures(policy={"max_attachments": 0})
    scenario.operator("task", "submit", "look")
    said = scenario.operator("attach", "task:1", str(doc), code=1).err
    assert "attach refused (too_many): attaching is off: policy.max_attachments is 0" in said


def test_a_name_is_plain_and_unique_among_what_a_subject_holds(scenario: Scenario, doc: Path) -> None:
    scenario.operator("task", "submit", "look")
    said = scenario.operator("attach", "task:1", str(doc), "--name", "../x.md", code=1).err
    assert "attach refused (bad_name): '../x.md' is not a plain file name" in said
    scenario.operator("attach", "task:1", str(doc), "--name", "design.md")
    said = scenario.operator("attach", "task:1", str(doc), "--name", "design.md", code=1).err
    assert "attach refused (taken): task:1 already has an attachment named design.md" in said


def test_stdin_is_attached_under_the_name_given(scenario: Scenario, doc: Path) -> None:
    scenario.operator("task", "submit", "look")
    assert "name it with --name" in scenario.operator("attach", "task:1", "-", code=2).err
    with mock.patch.object(sys, "stdin", io.TextIOWrapper(io.BytesIO(doc.read_bytes()))):
        scenario.operator("attach", "task:1", "-", "--name", "notes.md")
    [attached] = attachments.of(scenario.conn, TASK)
    assert attachments.path(scenario.env.state_dir, attached).read_text() == DOC


def test_a_detached_file_is_deleted_and_its_row_kept(scenario: Scenario, doc: Path) -> None:
    scenario.operator("task", "submit", "look")
    scenario.operator("attach", "task:1", str(doc), "--name", "design.md")
    [attached] = attachments.of(scenario.conn, TASK)
    path = attachments.path(scenario.env.state_dir, attached)
    assert "Removed design.md from task:1." in scenario.operator("detach", "task:1", "design.md").out
    assert not path.exists()
    assert attachments.of(scenario.conn, TASK) == []
    removed = present(attachments.get(scenario.conn, attached.id))
    assert (removed.removed_channel, removed.sha256) == ("cli", attached.sha256)
    assert removed.removed_at is not None
    said = scenario.operator("detach", "task:1", "design.md", code=1).err
    assert "detach refused (unknown): task:1 has no attachment named 'design.md'" in said
    # The name is free again.
    scenario.operator("attach", "task:1", str(doc), "--name", "design.md")
    assert [a.name for a in attachments.of(scenario.conn, TASK)] == ["design.md"]


@pytest.mark.parametrize("variable", ["CANOPY_RUN_ID", "CANOPY_TICK_ID"])
def test_attaching_or_detaching_inside_a_run_or_a_tick_is_refused(
    scenario: Scenario,
    doc: Path,
    variable: str,
) -> None:
    scenario.operator("task", "submit", "look")
    scenario.operator("attach", "task:1", str(doc), "--name", "design.md")
    limits = attachments.Limits.from_policy(config.Policy())
    with mock.patch.dict("os.environ", {variable: "7"}), pytest.raises(conversation.Refused, match="inside_run"):
        attachments.attach(scenario.conn, scenario.env.state_dir, TASK, "x.md", b"x", limits=limits, channel="cli")
    with mock.patch.dict("os.environ", {variable: "7"}), pytest.raises(conversation.Refused, match="inside_run"):
        attachments.remove(scenario.conn, scenario.env.state_dir, TASK, "design.md", channel="cli")
    assert [a.name for a in attachments.of(scenario.conn, TASK)] == ["design.md"]


@pytest.mark.parametrize(
    ("file_name", "name"),
    [
        ("design.md", "design.md"),
        ("/home/me/Downloads/Importer design (v2).md", "Importer-design-v2.md"),
        ("C:\\Users\\me\\spec v1.txt", "spec-v1.txt"),
        (".hidden.md", "hidden.md"),
        ("résumé notes", "r-sum-notes"),
        ("()", None),
        ("..", None),
    ],
)
def test_a_name_is_made_plain_from_a_file_s(file_name: str, name: str | None) -> None:
    assert attachments.name_from(file_name) == name


def test_a_workspace_file_may_lower_the_limits_but_not_raise_them(canopy_env: CanopyEnv) -> None:
    canopy_env.configure(canopy_env.shared_file, {"policy": {"max_attachments": 9, "max_attachment_kib": 1024}})
    policy = config.load(canopy_env.root, canopy_env.user_file).policy
    assert (policy.max_attachments, policy.max_attachment_kib) == (5, 512)
    canopy_env.configure(canopy_env.shared_file, {"policy": {"max_attachments": 1, "max_attachment_kib": 64}})
    policy = config.load(canopy_env.root, canopy_env.user_file).policy
    assert (policy.max_attachments, policy.max_attachment_kib) == (1, 64)


@pytest.mark.parametrize(
    ("key", "value"),
    [
        ("max_attachments", config.ATTACHMENTS_CEILING + 1),
        ("max_attachment_kib", config.ATTACHMENT_KIB_CEILING + 1),
        ("max_attachments_total_kib", config.ATTACHMENTS_TOTAL_KIB_CEILING + 1),
        ("max_attachment_kib", 0),
    ],
)
def test_a_limit_past_its_ceiling_is_refused(canopy_env: CanopyEnv, key: str, value: int) -> None:
    canopy_env.configure(canopy_env.user_file, {"policy": {key: value}})
    with pytest.raises(config.ConfigError, match=rf"policy\.{key}"):
        config.load(canopy_env.root, canopy_env.user_file)


def test_a_file_a_rolled_back_attach_left_does_not_block_the_next(scenario: Scenario, doc: Path) -> None:
    scenario.operator("task", "submit", "look")
    # What an attach that wrote its file and then rolled back leaves: a file at the id the next attach takes.
    left = scenario.env.state_dir / attachments.DIR_NAME / "task.1" / "1.txt"
    left.parent.mkdir(parents=True, mode=0o700)
    left.parent.parent.chmod(0o700)
    left.write_text("half of something else")
    scenario.operator("attach", "task:1", str(doc), "--name", "design.md")
    [attached] = attachments.of(scenario.conn, TASK)
    assert attached.id == 1
    assert attachments.path(scenario.env.state_dir, attached).read_text() == DOC
