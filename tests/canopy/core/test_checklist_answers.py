"""A worker's answers to its checklists, checked against the lists it was given (DESIGN §42).

Every item of every list gets a row: the run's answer, or `unanswered`. An answer to an item or a repository the lists
do not hold is dropped and named, and so is one that is no answer; neither costs the run its result.
"""

from __future__ import annotations

from canopy.core import checklist_answers, checklists
from canopy.core.checklist_answers import Answer
from canopy.core.vocab import ItemAnswer


def listed(repo: str, *ids: str) -> checklists.Checklist:
    """A list of `repo`'s, of an item for each of `ids`."""
    text = "\n".join(f"## {i}\nThe rule of {i}.\n" for i in ids)
    return checklists.Checklist(repo, *checklists.parse(repo, text))


API = listed("api", "general-types", "newspaper", "doc-comments")
WEB = listed("web", "no-any")


def test_each_item_is_recorded_as_the_run_answered_it() -> None:
    """A word or an object's `answer`, and `held` with its reason."""
    reported = {
        "api": {
            "general-types": "pass",
            "newspaper": {"answer": "fixed"},
            "doc-comments": {"answer": "held", "reason": "  A field of a NamedTuple, which Sphinx reads anyway.  "},
        },
        "web": {"no-any": "n/a"},
    }
    checked = checklist_answers.check([API, WEB], reported)
    assert checked.answers == (
        Answer("api", "general-types", ItemAnswer.PASSED),
        Answer("api", "newspaper", ItemAnswer.FIXED),
        Answer("api", "doc-comments", ItemAnswer.HELD, "A field of a NamedTuple, which Sphinx reads anyway."),
        Answer("web", "no-any", ItemAnswer.NOT_APPLICABLE),
    )
    assert checked.note() == ""


def test_an_item_left_out_is_unanswered() -> None:
    """A run with no `checklist`, or one that answers only some items, still records every item it was given."""
    assert [a.answer for a in checklist_answers.check([API], None).answers] == [ItemAnswer.UNANSWERED] * 3
    checked = checklist_answers.check([API, WEB], {"api": {"newspaper": "pass"}})
    assert [(a.item, a.answer) for a in checked.answers] == [
        ("general-types", ItemAnswer.UNANSWERED),
        ("newspaper", ItemAnswer.PASSED),
        ("doc-comments", ItemAnswer.UNANSWERED),
        ("no-any", ItemAnswer.UNANSWERED),
    ]
    assert checked.note() == ""


def test_answers_the_lists_do_not_hold_are_dropped_and_named() -> None:
    """An item or a repository the run was not given is dropped, and so is an answer that is none."""
    reported = {
        "api": {
            "general-types": "unanswered",
            "newspaper": {"answer": "held"},
            "doc-comments": "skipped",
            "made-up": "pass",
        },
        "docs": {"spelling": "pass"},
        "web": ["no-any"],
    }
    checked = checklist_answers.check([API, WEB], reported)
    assert {a.answer for a in checked.answers} == {ItemAnswer.UNANSWERED}
    assert checked.note() == (
        "checklist answers dropped: 'docs': no list of the run's; api 'made-up': not an item of its list; "
        "api general-types: `answer` is not fixed, held, n/a, pass; api newspaper: `held` gives no reason; "
        "api doc-comments: `answer` is not fixed, held, n/a, pass; web: not an object of items"
    )
    assert checklist_answers.check([WEB], "all pass").note() == (
        "checklist answers dropped: checklist is not an object of repositories"
    )


def test_a_reason_is_bounded() -> None:
    """A `held` item's reason is the worker's text: kept to `MAX_REASON` characters."""
    reported = {"web": {"no-any": {"answer": "held", "reason": "x" * 5000}}}
    [answer] = checklist_answers.check([WEB], reported).answers
    assert answer.reason == "x" * checklist_answers.MAX_REASON


def test_the_contract_names_each_repository_with_a_list() -> None:
    """Only a run given a list is told its push may be held; the others' prompts are as they were."""
    assert checklist_answers.contract_text([]) == ""
    text = checklist_answers.contract_text([API, WEB])
    assert text.startswith("\n\nThe operator keeps a checklist for `api`, `web`: rules no linter checks.")
    assert '"checklist":{"<repository>":' in text
