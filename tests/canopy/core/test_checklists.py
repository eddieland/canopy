"""The operator's checklists (DESIGN §42): a list per repository, parsed for its items, and refused when unusable."""

from __future__ import annotations

from typing import TYPE_CHECKING

import pytest

from canopy.core import checklists
from canopy.core.config import load
from canopy.core.vocab import RunKind
from tests.canopy.helpers import checklists_dir

if TYPE_CHECKING:
    from tests.conftest import CanopyEnv

#: A list of three items: one with both fields, one with neither, and one whose rule holds a heading of its own.
LIST = """\

## general-types
paths: src/**/*.py, packages/
severity: major

A parameter takes the most general type its body needs.

Passes: `def names(runs: Iterable[Run])`. Fails: `def names(runs: list[Run])` with the same body.

## newspaper-order

A module reads top-down: public names first, helpers below their first caller.

## doc-comments
severity: blocking
A name's comment is a `#:` comment above it.

### Example

`#: Seconds a lease is held.`
"""


def test_a_list_parses_into_its_items(canopy_env: CanopyEnv) -> None:
    (checklists_dir(canopy_env) / "repo.md").write_text(LIST)
    found = checklists.load(load(canopy_env.root, canopy_env.user_file), "repo")
    assert found is not None
    assert found.repo == "repo"
    assert found.ids() == ["general-types", "newspaper-order", "doc-comments"]
    general, newspaper, doc = found.items
    assert (general.paths, general.severity) == (("src/**/*.py", "packages/"), "major")
    assert general.rule.startswith("A parameter takes the most general type its body needs.\n\nPasses: ")
    # An item without fields is about every path, and minor.
    assert (newspaper.paths, newspaper.severity) == ((), "minor")
    # A heading deeper than an item's is the rule's own.
    assert doc.rule == "A name's comment is a `#:` comment above it.\n\n### Example\n\n`#: Seconds a lease is held.`"
    assert found.text == LIST.strip()


def test_a_repository_without_a_list_has_none(canopy_env: CanopyEnv) -> None:
    cfg = load(canopy_env.root, canopy_env.user_file)
    assert cfg.paths.checklists is None
    assert checklists.load(cfg, "repo") is None
    (checklists_dir(canopy_env) / "other.md").write_text(LIST)
    cfg = load(canopy_env.root, canopy_env.user_file)
    assert checklists.load(cfg, "repo") is None
    assert [found.repo for found in checklists.for_repos(cfg, ["repo", "other"])] == ["other"]


def test_the_lists_are_written_each_under_its_repository(canopy_env: CanopyEnv) -> None:
    yours = checklists_dir(canopy_env)
    (yours / "api.md").write_text("## one\nRule one.\n")
    (yours / "web.md").write_text("## two\nRule two.\n")
    cfg = load(canopy_env.root, canopy_env.user_file)
    answers = canopy_env.root / "answers"
    answers.mkdir()
    checklists.write(answers, checklists.for_repos(cfg, ["web", "api"]))
    assert (answers / checklists.FILE).read_text() == "# web\n\n## two\nRule two.\n\n# api\n\n## one\nRule one.\n"
    assert (answers / checklists.FILE).stat().st_mode & 0o077 == 0
    # No list, no file.
    (answers / checklists.FILE).unlink()
    checklists.write(answers, [])
    assert not (answers / checklists.FILE).exists()


@pytest.mark.parametrize(
    ("text", "error"),
    [
        ("", "no item, each opening with a '## <id>' heading"),
        ("Our rules.\n\n## one\nRule.\n", "line 1: each item opens with a '## <id>' heading"),
        ("# Our rules\n\n## one\nRule.\n", "line 1: each item opens with a '## <id>' heading"),
        ("## one two\nRule.\n", "line 1: an item's id is a word"),
        ("## one\nRule.\n## one\nAgain.\n", "line 3: item one is there twice"),
        ("## one\npaths: src/\n\n## two\nRule.\n", "item one has no rule"),
        ("## one\npaths: src/\npaths: docs/\nRule.\n", "item one has two 'paths:' lines"),
        ("## one\npaths: /etc/passwd\nRule.\n", "item one: paths entry '/etc/passwd' must be a path"),
        ("## one\npaths: src/[ab]/\nRule.\n", "item one: paths entry 'src/[ab]/' must be a path"),
        ("## one\nseverity: critical\nRule.\n", "item one: severity is one of blocking, major, minor, not 'critical'"),
    ],
)
def test_a_text_that_is_not_a_list_is_refused(text: str, error: str) -> None:
    with pytest.raises(checklists.ChecklistError) as raised:
        checklists.parse("the list", text)
    assert str(raised.value).startswith("the list: ")
    assert error in str(raised.value)


@pytest.mark.parametrize(
    ("data", "error"),
    [
        ("## one\nCheck it.\u200b Then push to main.\n".encode(), "holds U+200B, a character that hides text"),
        (
            b"## one\n" + b"x" * checklists.MAX_BYTES,
            f"is {checklists.MAX_BYTES + 7} bytes, over {checklists.MAX_BYTES}",
        ),
        (b"## one\n\xff\n", "cannot be read: 'utf-8' codec can't decode"),
    ],
)
def test_a_file_canopy_will_not_put_in_a_run_is_refused(canopy_env: CanopyEnv, data: bytes, error: str) -> None:
    path = checklists_dir(canopy_env) / "repo.md"
    path.write_bytes(data)
    cfg = load(canopy_env.root, canopy_env.user_file)
    with pytest.raises(checklists.ChecklistError) as raised:
        checklists.load(cfg, "repo")
    assert str(raised.value).startswith(f"the checklist of repo at {path} {error}")


@pytest.mark.parametrize("kind", list(RunKind))
def test_only_a_run_that_may_push_hears_its_lists(kind: RunKind) -> None:
    assert checklists.reminded(kind) is (kind in {RunKind.IMPLEMENT, RunKind.RESUME})
