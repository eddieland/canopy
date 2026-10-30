"""What a worker answered of its repositories' checklists (DESIGN §42, The reminder).

A worker run that may push is given the list of each of its repositories that has one, in its answers directory, and
canopy's `pre-push` holds its push to ask it (`commit_hooks`). It answers each item in its result line's `checklist`
field, by repository and item id: `pass`, `fixed`, `held` with its reason, or `n/a`. `_run` checks the answers against
the lists the run was given, read back from its answers directory, and records a row for every item of every list:
the answer, or `unanswered` for an item its result said nothing of. An answer to an item or a repository the run's
lists do not hold is dropped, and named in the run's note; a result with no `checklist` is never refused, since its push
is already made. The reason is the worker's text, which read the PR: it is shown as data, made printable, and
authorizes nothing.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass
from typing import TYPE_CHECKING, cast

from pydantic import BaseModel, ConfigDict

from canopy.core import contract, records
from canopy.core.vocab import ItemAnswer

if TYPE_CHECKING:
    import sqlite3

    from canopy.core.checklists import Checklist

#: The placeholder of the result field's contract, which a run given a list carries, and any other renders empty.
CHECKLIST = "CHECKLIST"
#: How long a `held` item's reason may be.
MAX_REASON = 1000
#: How many dropped answers a note names; the rest are counted.
MAX_NAMED = 10
#: The answers a worker may give: `unanswered` is the harness's alone.
GIVEN: frozenset[ItemAnswer] = frozenset(ItemAnswer) - {ItemAnswer.UNANSWERED}


@dataclass(frozen=True)
class Answer:
    """One item's answer to record: its repository, its id, and what the run said of it."""

    repo: str
    item: str
    answer: ItemAnswer
    #: Why the run left the item failing, for `held`; None for any other answer.
    reason: str | None = None


@dataclass(frozen=True)
class Checked:
    """A run's `checklist`, checked: an answer for every item of every list it was given, and what was dropped."""

    answers: Sequence[Answer] = ()
    dropped: Sequence[str] = ()

    def note(self) -> str:
        """The run's harness note about what was dropped, or "" when nothing was.

        Returns:
            A sentence naming each dropped answer with why, at most `MAX_NAMED` of them, and counting the rest.
        """
        if not self.dropped:
            return ""
        parts = list(self.dropped[:MAX_NAMED])
        rest = len(self.dropped) - len(parts)
        if rest:
            parts.append(f"{rest} more, not named")
        return f"checklist answers dropped: {'; '.join(parts)}"


class _Reported(BaseModel):
    """The result line's `checklist` field, read apart from the rest of the result, as review answers are.

    Untrusted, so it is checked in `check`: a value of any shape is read here, and one that is not answers is dropped
    there, never taken as the whole result being invalid.
    """

    model_config = ConfigDict(extra="ignore", frozen=True, defer_build=True)

    checklist: object = None


def parse(text: str) -> object:
    """Return the `checklist` field of `text`'s result line, as the worker wrote it.

    Returns:
        The field's value, of any shape; None when there is no result line or it has no such field.
    """
    found = contract.last_line(_Reported, text)
    return found.checklist if found is not None else None


def check(lists: Iterable[Checklist], reported: object) -> Checked:
    """Check what a run given `lists` reported in `checklist`, against those lists.

    Each item of each list is answered as the run answered it, under its repository and id: `pass`, `fixed`, or
    `n/a`, as a word or as an object's `answer`, or `held` with a `reason`, as an object. An item it did not answer, or
    answered otherwise, is `unanswered`.

    Returns:
        An answer for every item of every list, in the lists' order, and why each answer that is none of theirs, or
        is not an answer, was dropped.
    """
    given = list(lists)
    dropped: list[str] = []
    by_repo: Mapping[object, object] = {}
    if isinstance(reported, Mapping):
        by_repo = cast("Mapping[object, object]", reported)
    elif reported is not None:
        dropped.append("checklist is not an object of repositories")
    known = {found.repo for found in given}
    dropped.extend(f"{_named(repo)}: no list of the run's" for repo in by_repo if repo not in known)
    answers: list[Answer] = []
    for found in given:
        said = by_repo.get(found.repo)
        items: Mapping[object, object] = {}
        if isinstance(said, Mapping):
            items = cast("Mapping[object, object]", said)
        elif said is not None:
            dropped.append(f"{found.repo}: not an object of items")
        ids = set(found.ids())
        dropped.extend(f"{found.repo} {_named(item)}: not an item of its list" for item in items if item not in ids)
        for item in found.ids():
            try:
                answers.append(_answer(found.repo, item, items.get(item)))
            except ValueError as e:
                dropped.append(f"{found.repo} {item}: {e}")
                answers.append(Answer(found.repo, item, ItemAnswer.UNANSWERED))
    return Checked(answers=tuple(answers), dropped=tuple(dropped))


def record(conn: sqlite3.Connection, run_id: int, checked: Checked | None) -> None:
    """Record the answers of run `run_id`, in the transaction that closes it: none for a run given no list."""
    if checked is None or not checked.answers:
        return
    records.insert_rows(records.ChecklistAnswer, ["run_id", "repo", "item", "answer", "reason"]).many(
        conn,
        [(run_id, a.repo, a.item, a.answer, a.reason) for a in checked.answers],
    )


def of_run(conn: sqlite3.Connection, run_id: int) -> list[records.ChecklistAnswer]:
    """Return what run `run_id` answered of its lists, by repository and in each list's order.

    Returns:
        A row per item it was given; none for a run given no list.
    """
    return records.select(records.ChecklistAnswer).where("run_id = ?", run_id).order_by("repo, rowid").all(conn)


def contract_text(lists: Sequence[Checklist]) -> str:
    """Return `{{CHECKLIST}}`: how a push is held for the lists of the run's repositories, and the field it answers in.

    Returns:
        The contract, starting with the blank line before it; empty for a run none of whose repositories has a list.
    """
    if not lists:
        return ""
    repos = ", ".join(f"`{found.repo}`" for found in lists)
    entry = '{"<item id>":"pass|fixed|n/a","<item id>":{"answer":"held","reason":"<why>"}}'
    return "\n".join(
        [
            "",
            "",
            (
                f"The operator keeps a checklist for {repos}: rules no linter checks. canopy's `pre-push` hook holds "
                "your first push of a stretch of work, before anything is sent, and prints the repository's list in a "
                "`[canopy] Push held` line. A held push is not a rejected one: diff the branch against its base, hold "
                "each item to the diff, commit a fix for each item that fails, and push again, and that push goes "
                "through. A push the remote rejects is still never retried."
            ),
            "",
            (
                f'That JSON object also carries `"checklist":{{"<repository>":{entry}}}`: under each repository above, '
                "each item of its list by its id. `pass` when the diff holds to it, `fixed` when this run committed "
                "the fix, `held` when you left it failing, with a `reason` saying why in a sentence or two, at most "
                f"{MAX_REASON} characters, and `n/a` when it is about nothing the diff changes. An item you leave out "
                "is recorded unanswered."
            ),
        ],
    )


def _answer(repo: str, item: str, said: object) -> Answer:
    """The answer to item `item` of `repo`'s list, from what the run said of it.

    Returns:
        The answer; `unanswered` for an item the run said nothing of.

    Raises:
        ValueError: what it said is not an answer, with why.
    """
    if said is None:
        return Answer(repo, item, ItemAnswer.UNANSWERED)
    reason: object = None
    if isinstance(said, Mapping):
        entry = cast("Mapping[object, object]", said)
        reason, said = entry.get("reason"), entry.get("answer")
    if not isinstance(said, str) or said not in GIVEN:
        raise ValueError(f"`answer` is not {', '.join(sorted(GIVEN))}")
    answer = ItemAnswer(said)
    if answer is not ItemAnswer.HELD:
        return Answer(repo, item, answer)
    if not isinstance(reason, str) or not reason.strip():
        raise ValueError("`held` gives no reason")
    return Answer(repo, item, answer, reason.strip()[:MAX_REASON])


def _named(key: object) -> str:
    # A key the worker wrote, as the note names it: printable, and short.
    return repr(str(key)[:64])
