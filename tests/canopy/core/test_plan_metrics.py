"""How long a plan is, measured from its Markdown: words, lines in the plan editor, and what is not prose."""

from __future__ import annotations

from canopy.core.plan_metrics import DIAGRAM_LINES, LINE_CHARS, Metrics, measure

# A plan with every kind of block a planner writes, a list's items continued and nested, and a fence left open.
EVERY_KIND = """\
# Plan

Change the **parser** and [its docs](https://example.com/docs).

## Steps

1. Read the input.
   It may be long.
2. Write the output.
   - [ ] nested and checked

> A note.

---

```python
def parse(text):
    return text
```

| file | change |
|------|--------|
| a.py | new    |

```mermaid
flowchart LR
  A --> B
```

~~~
an unclosed fence runs to the end
"""


def test_a_paragraph_wraps_at_the_editors_width_however_its_markdown_is_wrapped() -> None:
    """A paragraph of two and a half lines' text fills three, written on one line or hard-wrapped over five."""
    words = ["word"] * (LINE_CHARS * 5 // 2 // 5)
    one_line = " ".join(words)
    wrapped = "\n".join(" ".join(words[i : i + 10]) for i in range(0, len(words), 10))
    assert measure(one_line) == measure(wrapped)
    assert measure(one_line).lines == 3
    assert measure(one_line).words == len(words)


def test_code_tables_and_diagrams_are_counted_and_their_code_is_not_words() -> None:
    """Every kind of block a planner writes: code and a diagram add lines but no words, a table's cells are words."""
    found = measure(EVERY_KIND)
    assert (found.code_blocks, found.tables, found.diagrams) == (2, 1, 1)
    # Plan, the sentence (its link's address dropped), Steps, each item with its continuation, the note, and the
    # table's four cells.
    assert found.words == 1 + 6 + 1 + (7 + 3 + 3) + 2 + 4
    assert found.lines > DIAGRAM_LINES


def test_an_empty_plan_and_a_bare_line_are_measured() -> None:
    """No text measures nothing; a line no rule takes, such as a lone pipe, is a paragraph."""
    assert measure("") == Metrics(words=0, lines=0, code_blocks=0, tables=0, diagrams=0)
    assert measure("|") == Metrics(words=1, lines=1, code_blocks=0, tables=0, diagrams=0)
