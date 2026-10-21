"""Each bundled prompt, persona, agent definition, and skill, checked against the size `.agents/sizes.toml` records
for it.

An agent run reads these files whole, and the overseer's prompt goes out on every tick, so a change to one's size
changes what every run after it costs. The recorded size is a record, not a limit: a prompt grows or shrinks as the
work needs, and the PR that changes it updates its number, so the diff shows by how much. The test measures the
files, never a model's output (AGENTS.md, Testing).

Run as a script, `make prompt-sizes`, it prints each file's size in characters and estimated tokens, to read before
and after a prompt edit.
"""

import sys
import tomllib
from collections.abc import Mapping
from pathlib import Path

#: Where the bundled files sit in a checkout. The record names each file by its path relative to this.
AGENTS = Path(__file__).resolve().parents[2] / ".agents"
#: The directories whose every file has a recorded size: what agent runs read. The operator's skill is not among them.
HELD = ("agents", "personas", "prompts", "skills")
#: The record: each file's size in characters, one line per file.
SIZES = AGENTS / "sizes.toml"
#: The record's path as the messages name it, from the repository root.
SHOWN = SIZES.relative_to(AGENTS.parent).as_posix()
#: How many characters under its recorded size a file may shrink before its number is updated too. Any growth shows;
#: a trim of up to 512 characters need not, but a larger one does, so the record stays accurate.
SLACK = 512
#: Characters per token, for the rough estimate the script prints.
CHARS_PER_TOKEN = 4


def test_each_bundled_file_matches_its_recorded_size() -> None:
    found = problems(measure(), recorded())
    assert not found, "\n".join(found)


def test_the_check_reports_growth_a_shrink_a_new_file_and_a_removed_one() -> None:
    # b.md shrank 513 characters, one past SLACK; e.md shrank 512, which needs no update.
    measured = {"a.md": 1001, "b.md": 1000, "c.md": 10, "d.md": 900, "e.md": 388}
    record = {"a.md": 1000, "b.md": 1513, "d.md": 900, "e.md": 900, "f.md": 300}
    assert problems(measured, record) == [
        (
            "a.md is now 1001 characters (recorded 1000). Changing a prompt's size is fine: update its line in"
            f' {SHOWN} to "a.md" = 1001 so the diff shows it.'
        ),
        (
            "b.md is now 1000 characters (recorded 1513). Changing a prompt's size is fine: update its line in"
            f' {SHOWN} to "b.md" = 1000 so the diff shows it.'
        ),
        f'c.md is new, at 10 characters. Adding a file is fine: add "c.md" = 10 to {SHOWN} so the diff shows it.',
        f"f.md is gone. Removing a file is fine: remove its line from {SHOWN} so the record matches.",
    ]


def measure() -> dict[str, int]:
    """Each held file's size in characters, by its path relative to `.agents/`."""
    return {
        path.relative_to(AGENTS).as_posix(): len(path.read_text(encoding="utf-8"))
        for held in HELD
        for path in sorted((AGENTS / held).rglob("*"))
        if path.is_file()
    }


def recorded() -> dict[str, int]:
    """The record in `.agents/sizes.toml`: each file's size in characters, by its path relative to `.agents/`."""
    record = tomllib.loads(SIZES.read_text(encoding="utf-8"))
    sizes: dict[str, int] = {}
    for path, size in record.items():
        assert isinstance(size, int), f"{SHOWN}: {path} = {size!r} is not a number of characters"
        sizes[path] = size
    return sizes


def problems(measured: Mapping[str, int], record: Mapping[str, int]) -> list[str]:
    """Where `record` no longer matches `measured`, each with the change to the record that brings it up to date: a
    file grown past its number or shrunk well under it, a file with no number, and a number for a file that is gone."""
    found: list[str] = []
    for path in sorted(measured.keys() | record.keys()):
        new, old = measured.get(path), record.get(path)
        line = f'"{path}" = {new}'
        if new is None:
            found.append(
                f"{path} is gone. Removing a file is fine: remove its line from {SHOWN} so the record matches.",
            )
        elif old is None:
            found.append(
                f"{path} is new, at {new} characters. Adding a file is fine: add {line} to {SHOWN} so the diff"
                " shows it.",
            )
        elif new > old or new < old - SLACK:
            found.append(
                f"{path} is now {new} characters (recorded {old}). Changing a prompt's size is fine: update its line"
                f" in {SHOWN} to {line} so the diff shows it.",
            )
    return found


def main() -> None:
    """Print each held file's size in characters and estimated tokens, beside its recorded size, and the totals."""
    measured, record = measure(), recorded()
    width = max(len(path) for path in measured)
    rows = [(path, size, record.get(path)) for path, size in measured.items()]
    rows.append(("total", sum(measured.values()), sum(record.values())))
    out = [f"{'file':<{width}}  {'characters':>10}  {'~tokens':>8}  {'recorded':>8}"]
    for path, size, noted in rows:
        out.append(f"{path:<{width}}  {size:>10}  {round(size / CHARS_PER_TOKEN):>8}  {noted or '-':>8}")
    out.append(f"~tokens is characters / {CHARS_PER_TOKEN}, a rough estimate; the recorded sizes are in {SHOWN}.")
    sys.stdout.write("\n".join(out) + "\n")


if __name__ == "__main__":
    main()
