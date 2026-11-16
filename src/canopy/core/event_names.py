"""The names notification events go by, and the patterns a sink takes them with (DESIGN §20).

Each event is named `<group>.<subject>.<kind>`: `runs.PROJ-1.started`, `chores.briefing.summary`. The subject is a name
canopy already validates, a ticket key, chore name, repository, epic, or task, and holds no dot; the loop's own
events, and the attention list, name none. A sink's `events` lists patterns over those names: `*` matches one
segment, `**` any number, a bare group stands for every event of it, and a leading `!` excludes. The last pattern
that matches decides. The names are config surface, so a rename needs an alias here.
"""

from __future__ import annotations

import re
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from enum import IntEnum
from typing import Literal

#: The groups an event belongs to, the first segment of its name. `attention` is the attention list's diff.
GROUPS = ("attention", "loop", "runs", "chores", "reviews", "tasks", "replies")
#: The subject of an event about nothing its kind names, such as a reply that named no ticket. No ticket key, chore,
#: repository, or number is spelled so.
NO_SUBJECT = "-"
#: What one literal segment of a pattern may hold: what a subject or a kind may.
SEGMENT_RE = re.compile(r"[A-Za-z0-9_-]+")
#: The longest pattern a sink may list.
MAX_PATTERN = 200
#: How a sink takes events of one name for some subjects: every one, none, or some, by its subject.
Taken = Literal["all", "some", "none"]
#: How each kind of subject is spelled, as config and the journal check it: a ticket key (`config.KEY_RE`), a chore's or
#: a repository's name (`CHORE_NAME_RE`, `REPO_NAME_RE`), and an epic's or a task's id. A pattern naming a subject no
#: event can have is refused, as `tasks.deploy.ended` is.
SUBJECTS: Mapping[str, re.Pattern[str]] = {
    "ticket": re.compile(r"[A-Za-z0-9][A-Za-z0-9_-]*"),
    "chore": re.compile(r"[a-z][a-z0-9-]*"),
    "repo": re.compile(r"[a-z][a-z0-9-]*"),
    "epic": re.compile(r"[0-9]+"),
    "task": re.compile(r"[0-9]+"),
}

_ONE = "*"
_ANY = "**"
_NOT = "!"


@dataclass(frozen=True)
class Spec:
    """One name an event can go by, and the kind its `json` format calls it."""

    #: The event's kind, as the `json` format's `kind` field and the outbox's row name it.
    kind: str
    group: str
    #: What the subject segment names, such as `ticket`, or None for a name without one.
    subject: str | None
    #: The field of the event that holds the subject; None for a name without one.
    field: str | None
    #: The name's last segment, or None for the attention list, whose name is its group alone.
    last: str | None

    @property
    def template(self) -> str:
        """The name as `canopy notify events` lists it, the subject in angle brackets: `runs.<ticket>.started`."""
        return ".".join(self._segments(f"<{self.subject}>"))

    def name(self, subject: str | None) -> str:
        """The name of an event of this kind about `subject`.

        Returns:
            The dotted name, its subject `NO_SUBJECT` when `subject` is None or not a single segment.
        """
        given = subject if subject is not None and SEGMENT_RE.fullmatch(subject) else NO_SUBJECT
        return ".".join(self._segments(given))

    def _segments(self, subject: str) -> list[str]:
        middle = [subject] if self.subject is not None else []
        return [self.group, *middle, *([self.last] if self.last is not None else [])]


#: Every name canopy can send, in the order `canopy notify events` lists them.
SPECS: tuple[Spec, ...] = (
    Spec("attention", "attention", None, None, None),
    Spec("run.started", "runs", "ticket", "ticket", "started"),
    Spec("run.ended", "runs", "ticket", "ticket", "ended"),
    Spec("plan.proposed", "runs", "ticket", "ticket", "plan_proposed"),
    Spec("plan.approved", "runs", "ticket", "ticket", "plan_approved"),
    Spec("follow_ups.filed", "runs", "ticket", "ticket", "follow_ups_filed"),
    Spec("ci.flaky", "runs", "ticket", "ticket", "ci_flaky"),
    Spec("epic.changed", "runs", "epic", "epic", "epic_changed"),
    Spec("chore.ended", "chores", "chore", "chore", "ended"),
    Spec("chore.summary", "chores", "chore", "chore", "summary"),
    Spec("review.ended", "reviews", "repo", "repo", "ended"),
    Spec("task.ended", "tasks", "task", "task", "ended"),
    Spec("reply.recorded", "replies", "ticket", "ticket", "recorded"),
    Spec("reply.refused", "replies", "ticket", "ticket", "refused"),
    Spec("loop.failing", "loop", None, None, "failing"),
    Spec("loop.recovered", "loop", None, None, "recovered"),
    Spec("loop.sink_failing", "loop", None, None, "sink_failing"),
    Spec("loop.budget_reached", "loop", None, None, "budget_reached"),
    Spec("ci.kicked", "loop", None, None, "ci_kicked"),
)
_BY_KIND = {s.kind: s for s in SPECS}


def name_of(group: str, kind: str, fields: Mapping[str, object]) -> str:
    """The name of an event of `kind` in `group` with `fields`, as a sink's patterns match it.

    Returns:
        Its dotted name, the subject read from its fields; for a kind canopy does not know, its group alone.
    """
    spec = _BY_KIND.get(kind)
    if spec is None or spec.group != group:
        return group
    subject = fields.get(spec.field) if spec.field is not None else None
    return spec.name(str(subject) if isinstance(subject, str | int) and not isinstance(subject, bool) else None)


class Fit(IntEnum):
    """How a pattern matches names: for none, for some subjects only, or for every one. Ordered, so `min` is `and`."""

    NO = 0
    SOME = 1
    YES = 2


@dataclass(frozen=True)
class Pattern:
    """One entry of a sink's `events`: the segments it matches, and whether it takes or excludes what it matches."""

    segments: Sequence[str]
    exclude: bool

    @classmethod
    def parse(cls, text: str) -> Pattern:
        """Read one entry of a sink's `events`.

        Returns:
            The pattern. A bare group stands for every event of it, `<group>.**`.

        Raises:
            ValueError: It is too long, its first segment is not a group, a segment is empty or holds what no name
                does, or it matches no event canopy sends.
        """
        if len(text) > MAX_PATTERN:
            raise ValueError(f"event pattern {text[:40]!r}... is longer than {MAX_PATTERN} characters")
        exclude = text.startswith(_NOT)
        segments = text.removeprefix(_NOT).split(".")
        if segments[0] not in GROUPS:
            raise ValueError(f"event pattern {text!r} must start with a group: {', '.join(GROUPS)}")
        for segment in segments[1:]:
            if segment not in (_ONE, _ANY) and not SEGMENT_RE.fullmatch(segment):
                raise ValueError(
                    f"event pattern {text!r}: each segment after the group is *, **, or letters, digits, - and _",
                )
        if len(segments) == 1:
            segments.append(_ANY)
        # `**.**` matches what `**` does, so the matcher never meets a run of them.
        kept = [s for i, s in enumerate(segments) if not (s == _ANY and i > 0 and segments[i - 1] == _ANY)]
        pattern = cls(tuple(kept), exclude)
        if not any(pattern.could_match(s) for s in SPECS):
            raise ValueError(f"event pattern {text!r} matches no event canopy sends: see `canopy notify events`")
        return pattern

    def matches(self, name: str) -> bool:
        """Whether this pattern matches event name `name`, regardless of whether it takes or excludes it.

        Returns:
            True when it matches.
        """
        return _match(self.segments, name.split("."), subject=None) is Fit.YES

    def could_match(self, spec: Spec) -> bool:
        """Whether this pattern matches events of `spec` for at least one subject.

        Returns:
            True when it matches some name of `spec`.
        """
        return self.fits(spec) is not Fit.NO

    def fits(self, spec: Spec) -> Fit:
        """How this pattern matches events of `spec`: for every subject, for some, or for none.

        Returns:
            The fit.
        """
        subject = (1, SUBJECTS[spec.subject]) if spec.subject is not None else None
        template = spec.template.split(".")
        return _match(self.segments, template, subject=subject)


def parse_all(texts: Sequence[str]) -> tuple[Pattern, ...]:
    """Read a sink's `events`.

    Returns:
        Its patterns, in order.
    """
    return tuple(Pattern.parse(t) for t in texts)


def takes(patterns: Sequence[Pattern], name: str) -> bool:
    """Whether a sink with `patterns` takes event `name`: the last pattern that matches decides, and none excludes.

    Returns:
        True when the last pattern that matches `name` takes it.
    """
    for pattern in reversed(patterns):
        if pattern.matches(name):
            return not pattern.exclude
    return False


def taken(patterns: Sequence[Pattern], spec: Spec) -> Taken:
    """Whether a sink with `patterns` takes events of `spec`, for `canopy notify events`.

    Returns:
        `all` when it takes them whatever their subject, `none` when it takes none, and `some` when it depends on the
        subject, as `runs.PROJ-1.*` takes `run.started` for one ticket.
    """
    if spec.subject is None:
        return "all" if takes(patterns, spec.name(None)) else "none"
    # A subject no pattern spells is taken as any other such subject is, so the subjects patterns spell, and one
    # none does, are every case there is.
    literals = {s for p in patterns for s in p.segments}
    spelled = {s for s in literals if SUBJECTS[spec.subject].fullmatch(s)}
    other = next(f"{spec.subject}{n}" for n in range(len(literals) + 1) if f"{spec.subject}{n}" not in literals)
    outcomes = {takes(patterns, spec.name(subject)) for subject in (*spelled, other)}
    if outcomes == {True}:
        return "all"
    return "none" if outcomes == {False} else "some"


def groups(patterns: Sequence[Pattern]) -> list[str]:
    """The groups a sink with `patterns` may take an event of, in `GROUPS` order.

    Returns:
        Each group some pattern that takes events names.
    """
    named = {p.segments[0] for p in patterns if not p.exclude}
    return [g for g in GROUPS if g in named]


def _match(pattern: Sequence[str], name: Sequence[str], *, subject: _Subject | None) -> Fit:
    """Match `pattern` to `name`'s segments, the segment at `subject`'s index standing for any subject it spells.

    A literal segment matches the subject only for some subjects, and only if it spells one; `*` and `**` match it for
    every one.

    Returns:
        The best fit of any way to match.
    """
    return _fit(tuple(pattern), tuple(name), 0, 0, subject)


#: Where a name's subject is, and how a subject is spelled.
_Subject = tuple[int, re.Pattern[str]]


def _fit(pattern: tuple[str, ...], name: tuple[str, ...], p: int, n: int, subject: _Subject | None) -> Fit:
    if p == len(pattern):
        return Fit.YES if n == len(name) else Fit.NO
    if sum(1 for s in pattern[p:] if s != _ANY) > len(name) - n:
        # More segments left to match than the name has: no way to match, however many `**` there are.
        return Fit.NO
    head = pattern[p]
    if head == _ANY:
        # `**` takes none of the rest, or one more segment and tries again.
        best = _fit(pattern, name, p + 1, n, subject)
        if n < len(name):
            best = max(best, _fit(pattern, name, p, n + 1, subject))
        return best
    if n == len(name):
        return Fit.NO
    if head == _ONE:
        here = Fit.YES
    elif subject is not None and n == subject[0]:
        here = Fit.SOME if subject[1].fullmatch(head) else Fit.NO
    else:
        here = Fit.YES if head == name[n] else Fit.NO
    if here is Fit.NO:
        return Fit.NO
    return min(here, _fit(pattern, name, p + 1, n + 1, subject))
