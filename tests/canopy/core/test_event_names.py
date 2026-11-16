"""The names notification events go by, and the patterns a sink takes them with (DESIGN §20)."""

from typing import get_type_hints

import pytest
from pydantic import TypeAdapter

from canopy.core import config, event_names, outbox
from canopy.core.event_names import Pattern


def takes(patterns: list[str], name: str) -> bool:
    """Whether a sink listing `patterns` takes event `name`."""
    return event_names.takes(event_names.parse_all(patterns), name)


def spec(kind: str) -> event_names.Spec:
    """The spec of event `kind`."""
    return next(s for s in event_names.SPECS if s.kind == kind)


@pytest.mark.parametrize(
    ("group", "kind", "fields", "name"),
    [
        ("runs", "run.started", {"ticket": "PROJ-1"}, "runs.PROJ-1.started"),
        ("runs", "plan.proposed", {"ticket": "PROJ-1"}, "runs.PROJ-1.plan_proposed"),
        ("runs", "epic.changed", {"epic": 4}, "runs.4.epic_changed"),
        ("chores", "chore.summary", {"chore": "briefing"}, "chores.briefing.summary"),
        ("reviews", "review.ended", {"repo": "api"}, "reviews.api.ended"),
        ("tasks", "task.ended", {"task": 7}, "tasks.7.ended"),
        ("loop", "ci.kicked", {"ticket": "PROJ-1"}, "loop.ci_kicked"),
        ("loop", "loop.failing", {}, "loop.failing"),
        # A subject that is missing, or would be more than one segment, is named as none.
        ("replies", "reply.refused", {"ticket": None}, "replies.-.refused"),
        ("reviews", "review.ended", {"repo": "a.b"}, "reviews.-.ended"),
        ("runs", "run.ended", {"ticket": True}, "runs.-.ended"),
        # A kind canopy does not know is named by its group alone.
        ("runs", "run.vanished", {"ticket": "PROJ-1"}, "runs"),
    ],
)
def test_an_event_is_named_by_its_group_subject_and_kind(
    group: str,
    kind: str,
    fields: dict[str, object],
    name: str,
) -> None:
    """The subject comes from the field its kind names."""
    assert event_names.name_of(group, kind, fields) == name


@pytest.mark.parametrize(
    ("patterns", "name", "taken"),
    [
        (["runs"], "runs.PROJ-1.started", True),
        (["runs"], "chores.deps.ended", False),
        (["attention"], "attention", True),
        (["runs.*.plan_proposed"], "runs.PROJ-1.plan_proposed", True),
        (["runs.*.plan_proposed"], "runs.PROJ-1.started", False),
        (["runs.PROJ-1.*"], "runs.PROJ-1.ended", True),
        (["runs.PROJ-1.*"], "runs.PROJ-2.ended", False),
        (["runs.**"], "runs.PROJ-1.ended", True),
        (["chores.**.summary"], "chores.briefing.summary", True),
        (["loop.failing", "loop.recovered"], "loop.budget_reached", False),
        # The last pattern that matches decides.
        (["runs.**", "!runs.*.started"], "runs.PROJ-1.started", False),
        (["runs.**", "!runs.*.started"], "runs.PROJ-1.ended", True),
        (["!runs.*.started", "runs.**"], "runs.PROJ-1.started", True),
        ([], "attention", False),
    ],
)
def test_the_last_pattern_that_matches_decides(patterns: list[str], name: str, *, taken: bool) -> None:
    """`*` is one segment, `**` any number, a bare group all of it, and `!` excludes."""
    assert takes(patterns, name) is taken


@pytest.mark.parametrize(
    ("pattern", "why"),
    [
        ("run", "must start with a group"),
        ("**", "must start with a group"),
        ("runs..ended", "each segment"),
        ("runs.PROJ 1.ended", "each segment"),
        ("runs.*.strated", "matches no event"),
        ("runs.*", "matches no event"),
        ("loop.*.failing", "matches no event"),
        ("chores.a.b.c.d", "matches no event"),
        # A subject no event can have: a task's id is a number, a chore's name is lowercase.
        ("tasks.deploy.ended", "matches no event"),
        ("chores.Briefing.summary", "matches no event"),
        ("runs." + "x" * 200, "longer than"),
    ],
)
def test_a_pattern_that_can_match_nothing_is_refused(pattern: str, why: str) -> None:
    """A typo is a config error, not a sink that silently hears nothing."""
    with pytest.raises(ValueError, match=why):
        Pattern.parse(pattern)


def test_many_double_stars_are_matched_quickly() -> None:
    """A pattern of many `**` neither recurses without end nor refuses: it matches what one `**` does."""
    assert takes(["runs." + ".".join(["**"] * 60)], "runs.PROJ-1.started")
    assert takes(["runs." + ".".join(["**", "*"] * 2) + ".**"], "runs.PROJ-1.started")


@pytest.mark.parametrize(
    ("patterns", "kind", "taken"),
    [
        (["runs"], "run.started", "all"),
        (["runs.PROJ-1.*"], "run.started", "some"),
        (["runs.**", "!runs.PROJ-1.started"], "run.started", "some"),
        (["runs.**", "!runs.*.started"], "run.started", "none"),
        (["runs.PROJ-1.*", "runs.**"], "run.started", "all"),
        # The last match decides for each subject, so overlapping patterns are read whole.
        (["runs.PROJ-1.*", "!runs.PROJ-1.*"], "run.started", "none"),
        (["runs.**", "!runs.PROJ-1.*", "runs.PROJ-1.started"], "run.started", "all"),
        (["runs.PROJ-1.*", "runs.PROJ-2.*", "!runs.PROJ-1.ended"], "run.ended", "some"),
        (["loop"], "loop.failing", "all"),
        (["loop.failing"], "ci.kicked", "none"),
        (["attention"], "attention", "all"),
        ([], "attention", "none"),
    ],
)
def test_a_sink_takes_a_name_for_all_some_or_no_subjects(
    patterns: list[str],
    kind: str,
    taken: event_names.Taken,
) -> None:
    """`canopy notify events` says which sinks take a name only for some tickets, chores, or repositories."""
    assert event_names.taken(event_names.parse_all(patterns), spec(kind)) == taken


def test_the_groups_a_sink_may_take_leave_out_what_it_only_excludes() -> None:
    """Only the groups of patterns that take events are read from the outbox."""
    patterns = event_names.parse_all(["chores.*.summary", "!runs.*.started", "loop"])
    assert event_names.groups(patterns) == ["loop", "chores"]


def test_every_name_has_a_template_and_an_example_of_its_fields() -> None:
    """Every kind is named once, and `canopy notify events` shows each kind's fields, all of them."""
    kinds = [s.kind for s in event_names.SPECS]
    assert len(kinds) == len(set(kinds))
    assert len({s.template for s in event_names.SPECS}) == len(kinds)
    assert set(outbox.EXAMPLES) == set(kinds) - {outbox.ATTENTION}
    shapes = {
        "run.started": outbox.RunStarted,
        "run.ended": outbox.RunEnded,
        "plan.proposed": outbox.PlanProposed,
        "plan.approved": outbox.PlanApproved,
        "follow_ups.filed": outbox.FollowUpsFiled,
        "ci.flaky": outbox.CiFlaky,
        "epic.changed": outbox.EpicChanged,
        "chore.ended": outbox.ChoreEnded,
        "chore.summary": outbox.ChoreSummary,
        "review.ended": outbox.ReviewEnded,
        "task.ended": outbox.TaskEnded,
        "reply.recorded": outbox.ReplyRecorded,
        "reply.refused": outbox.ReplyRefused,
        "loop.failing": outbox.LoopFailing,
        "loop.recovered": outbox.LoopRecovered,
        "loop.sink_failing": outbox.SinkFailing,
        "loop.budget_reached": outbox.BudgetReached,
        "ci.kicked": outbox.CiKicked,
    }
    assert set(shapes) == set(outbox.EXAMPLES)
    for kind, shape in shapes.items():
        assert set(outbox.EXAMPLES[kind]) == set(get_type_hints(shape)), kind
        # Each value of the type its field is, too.
        TypeAdapter(shape).validate_python(outbox.EXAMPLES[kind], strict=True)
        named = event_names.name_of(spec(kind).group, kind, outbox.EXAMPLES[kind])
        assert named.split(".")[-1] == spec(kind).last, kind


def test_a_subject_is_spelled_as_config_checks_it() -> None:
    """A pattern's subject is held to what config accepts, so the two cannot drift apart."""
    assert event_names.SUBJECTS["ticket"].pattern == config.KEY_RE.pattern
    assert event_names.SUBJECTS["chore"].pattern == config.CHORE_NAME_RE.pattern
    assert event_names.SUBJECTS["repo"].pattern == config.REPO_NAME_RE.pattern
