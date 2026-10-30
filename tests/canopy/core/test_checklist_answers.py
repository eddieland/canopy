"""A run's answers to its checklists, checked against the lists it was given (DESIGN §42), and the contract it reads.

The answers are the worker's, so each is checked alone: one canopy refuses leaves its item unanswered, never the rest.
"""

from __future__ import annotations

from canopy.core import checklist_answers, checklists
from canopy.core.checklist_answers import Answer
from canopy.core.vocab import ItemAnswer

#: A repository's list of two items.
LIST = checklists.Checklist(
    "repo",
    *checklists.parse("repo's list", "## general-types\nThe most general type.\n\n## newspaper\nTop-down.\n"),
)


def test_a_run_given_no_list_records_nothing_and_reads_no_contract() -> None:
    assert checklist_answers.check({"repo": {"general-types": "pass"}}, []) is None
    assert checklist_answers.contract_text([]) == ""


def test_each_item_gets_an_answer_in_the_lists_order() -> None:
    checked = checklist_answers.check({"repo": {"newspaper": {"answer": "fixed", "reason": " Moved. "}}}, [LIST])
    assert checked == checklist_answers.Checked(
        answers=(
            Answer("repo", "general-types", ItemAnswer.UNANSWERED, None),
            Answer("repo", "newspaper", ItemAnswer.FIXED, "Moved."),
        ),
    )


def test_answers_under_a_repository_that_are_not_an_object_are_refused() -> None:
    checked = checklist_answers.check({"repo": "pass"}, [LIST])
    assert checked is not None
    assert {a.answer for a in checked.answers} == {ItemAnswer.UNANSWERED}
    assert checked.note() == "checklist answers not recorded: the answers under repo are not an object"


def test_an_answer_with_more_than_canopy_reads_keeps_what_it_reads() -> None:
    checked = checklist_answers.check({"repo": {"general-types": {"answer": "pass", "why": "typed"}}}, [LIST])
    assert checked is not None
    assert checked.answers[0] == Answer("repo", "general-types", ItemAnswer.PASS, None)


def test_a_note_names_ten_refusals_and_counts_the_rest() -> None:
    refused = [f"item {n} of repo: held, with no reason" for n in range(12)]
    note = checklist_answers.Checked(refused=refused).note()
    assert note.endswith("item 9 of repo: held, with no reason; 2 more, not named")


def test_the_contract_names_each_repository_given_a_list() -> None:
    web = checklists.Checklist("web", LIST.items, LIST.text)
    text = checklist_answers.contract_text([LIST, web])
    assert text.startswith("\n\ncanopy may hold your first push in `repo` and `web` for that repository's checklist")
    assert "a held push is not a rejection" in text
    assert f"at most {checklist_answers.MAX_REASON} characters" in text
