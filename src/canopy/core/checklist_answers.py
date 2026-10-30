"""What a reminded worker answered of its repositories' checklists (DESIGN §42, The reminder).

A worker run given a list answers each of its items in its result line's `checklist` field, by repository and item id:
`pass`, `fixed`, `held` with the reason, or `n/a`. `_run` reads the field apart from the rest of the result, so a bad
answer costs the run nothing but that answer, and checks it against the lists the run was given, as its answers
directory holds them: an answer under a repository or an item those lists do not hold is dropped, and an item the result
answers nothing canopy can record is recorded `unanswered`, as is every item of a run whose result has no `checklist`,
never refused, since its push is already made. Every item of every list the run was given gets a row, so canopy can
count per repository and item how often it was reminded and what came of it.

The answers are the worker's words, which read the diff and the PR: they are recorded as data, for the operator to
read, and reach no agent's prompt.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import TYPE_CHECKING, Annotated, Literal

from pydantic import BaseModel, ConfigDict, StrictStr, ValidationError

from canopy.core import contract, records
from canopy.core.vocab import ItemAnswer

if TYPE_CHECKING:
    import sqlite3

    from canopy.core.checklists import Checklist

#: The placeholder of the result field's contract, which a worker run given a list carries.
CHECKLIST = "CHECKLIST"
#: How long a reason may be: a sentence or two, on the run's page beside its item.
MAX_REASON = 500
#: How many refused answers a note names; the rest are counted.
MAX_NAMED = 10

#: A worker's reason for its answer: one line, cut to `MAX_REASON`.
Reason = Annotated[StrictStr, contract.one_line, contract.bounded(MAX_REASON)]


class _Reported(BaseModel):
    """The result line's `checklist` field, read apart from the rest of the result, as review answers are.

    Untrusted, so each answer is checked in `check`: a value of any shape is read here, and one that is not answers by
    repository and item is refused there, never taken as the whole result being invalid.
    """

    model_config = ConfigDict(extra="ignore", frozen=True, defer_build=True)

    checklist: object = None


class _Said(BaseModel):
    """One answer, as the worker wrote it: a bare answer, or an object with its `reason`."""

    model_config = ConfigDict(extra="ignore", frozen=True, defer_build=True)

    answer: Literal["pass", "fixed", "held", "n/a"]
    reason: Reason | None = None


@dataclass(frozen=True)
class Answer:
    """One answer to record: the item, by its repository and id, and what the worker said of it."""

    repo: str
    item: str
    answer: ItemAnswer
    #: Why it held the item, or what it says of another answer; None when it said nothing.
    reason: str | None


@dataclass(frozen=True)
class Checked:
    """A run's `checklist`, checked: an answer for every item of its lists, and why each refused answer was refused."""

    answers: Sequence[Answer] = ()
    refused: Sequence[str] = ()

    def note(self) -> str:
        """The run's harness note about what was refused, or "" when nothing was.

        Returns:
            A sentence naming each refused answer with why, at most `MAX_NAMED` of them, and counting the rest.
        """
        if not self.refused:
            return ""
        parts = list(self.refused[:MAX_NAMED])
        rest = len(self.refused) - len(parts)
        if rest:
            parts.append(f"{rest} more, not named")
        return f"checklist answers not recorded: {'; '.join(parts)}"


def parse(text: str) -> object:
    """Return the `checklist` field of `text`'s result line, as the worker wrote it.

    Returns:
        The field's value, of any shape; None when there is no valid result line or it has no such field.
    """
    found = contract.last_line(_Reported, text)
    return found.checklist if found is not None else None


def check(reported: object, lists: Sequence[Checklist]) -> Checked | None:
    """Check what a run given `lists` reported in `checklist`, each answer alone, into an answer for every item.

    An answer is kept when it is under a repository of `lists` and names an item of that repository's list, and is
    `pass`, `fixed`, `held` with a reason, or `n/a`. One under another repository or item is dropped, counted in the
    note but not named, since its names are the worker's; an item with no answer kept is `unanswered`.

    Returns:
        An answer for each item of each of `lists`, in their order, and why each answer refused was; None for a run
        given no list, which records nothing.
    """
    if not lists:
        return None
    refused: list[str] = []
    if reported is not None and not isinstance(reported, Mapping):
        refused.append("checklist is not an object")
    by_repo: Mapping[object, object] = reported if isinstance(reported, Mapping) else {}
    repos = {found.repo for found in lists}
    unknown = sum(1 for repo in by_repo if repo not in repos)
    answers: list[Answer] = []
    for found in lists:
        kept, why, others = _answers_to(found, by_repo.get(found.repo))
        answers += kept
        refused += why
        unknown += others
    if unknown:
        refused.append(f"answers under a repository or an item the run's lists do not hold: {unknown}")
    return Checked(answers=tuple(answers), refused=tuple(refused))


def record(conn: sqlite3.Connection, run_id: int, checked: Checked | None) -> None:
    """Record the answers run `run_id` gave, in the transaction that closes it; nothing for a run given no list."""
    if checked is None or not checked.answers:
        return
    records.insert_rows(records.ChecklistAnswer, ["run_id", "repo", "item", "answer", "reason"]).many(
        conn,
        [(run_id, a.repo, a.item, a.answer, a.reason) for a in checked.answers],
    )


def contract_text(lists: Sequence[Checklist]) -> str:
    """Return `{{CHECKLIST}}`: what a held push is, and the result field a run given `lists` answers them in.

    Returns:
        The contract, starting with the blank line before it; "" for a run given no list.
    """
    if not lists:
        return ""
    repos = " and ".join(f"`{found.repo}`" for found in lists)
    entry = '{"<repo>":{"<item id>":"pass|fixed|n/a","<item id>":{"answer":"held","reason":"<why>"}}}'
    return "\n".join(
        [
            "",
            "",
            (
                f"canopy may hold your first push in {repos} for that repository's checklist, which it prints: a held "
                "push is not a rejection. Diff the branch against its base, hold each item to the diff, commit a fix "
                "for each that fails, and push again, once: that push goes through. That JSON object then also carries "
                f'`"checklist":{entry}`, answering each item of each list: `fixed` for one you committed a fix for, '
                f"`held` with a `reason` of at most {MAX_REASON} characters for one you leave the diff failing, and "
                "`n/a` for one about nothing the diff changes."
            ),
        ],
    )


def _answers_to(found: Checklist, items: object) -> tuple[list[Answer], list[str], int]:
    """Check what a run answered under `found`'s repository, `items`, into an answer for each of `found`'s items.

    Returns:
        An answer for each item, in the list's order, `unanswered` where none was kept; why each answer refused was;
        and how many answers name an item the list does not hold.
    """
    refused: list[str] = []
    said: dict[object, Answer] = {}
    unknown = 0
    if items is not None and not isinstance(items, Mapping):
        refused.append(f"the answers under {found.repo} are not an object")
    ids = set(found.ids())
    for item, value in (items if isinstance(items, Mapping) else {}).items():
        if item not in ids:
            unknown += 1
            continue
        try:
            said[item] = _answer(found.repo, str(item), value)
        except ValueError as e:
            refused.append(f"item {item} of {found.repo}: {e}")
    answers = [said.get(item, Answer(found.repo, item, ItemAnswer.UNANSWERED, None)) for item in found.ids()]
    return answers, refused, unknown


def _answer(repo: str, item: str, value: object) -> Answer:
    """One answer as an answer to record: a bare answer, or an object with its `answer` and `reason`.

    Returns:
        The answer.

    Raises:
        ValueError: it is not `pass`, `fixed`, `held` with a reason, or `n/a`, with why.
    """
    try:
        said = _Said.model_validate(value if isinstance(value, Mapping) else {"answer": value})
    except ValidationError:
        raise ValueError("not pass, fixed, held with a reason, or n/a") from None
    reason = said.reason.strip() if said.reason is not None else ""
    if said.answer == ItemAnswer.HELD and not reason:
        raise ValueError("held, with no reason")
    return Answer(repo, item, ItemAnswer(said.answer), reason or None)
