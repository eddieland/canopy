"""The codemods' runner and command line: which files they take, what `--check` reports, and what gets written."""

from pathlib import Path
from typing import Final

import pytest
from canopy_codemods import main, run
from canopy_codemods.registry import CODEMODS
from click.testing import CliRunner

BEFORE: Final = "LIMIT = 3\n"
AFTER: Final = "from typing import Final\n\nLIMIT: Final = 3\n"


def invoke(*args: object) -> tuple[int, str]:
    result = CliRunner().invoke(main, [str(arg) for arg in args])
    return result.exit_code, result.output


def test_a_directory_gives_its_python_and_its_python_scripts_but_nothing_hidden_or_installed(tmp_path: Path) -> None:
    for name in ("a.py", "pkg/b.py", ".venv/c.py", "node_modules/d.py", "pkg/__pycache__/e.py", "notes.md"):
        path = tmp_path / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(BEFORE)
    (tmp_path / "fake").write_text(f"#!/usr/bin/env python3\n{BEFORE}")
    (tmp_path / "script").write_text("#!/bin/sh\n")
    (tmp_path / "LICENSE").write_text("MIT\n")

    assert run.files([tmp_path]) == [tmp_path / "a.py", tmp_path / "fake", tmp_path / "pkg" / "b.py"]


def test_a_file_named_outright_is_taken_whatever_its_name(tmp_path: Path) -> None:
    hidden = tmp_path / ".venv" / "c.pyi"
    hidden.parent.mkdir()
    hidden.write_text(BEFORE)

    assert run.files([hidden, hidden]) == [hidden]


def test_applying_rewrites_the_files_a_codemod_changes_and_no_other(tmp_path: Path) -> None:
    stale, clean = tmp_path / "stale.py", tmp_path / "clean.py"
    stale.write_text(BEFORE)
    clean.write_text(AFTER)
    written = clean.stat().st_mtime_ns

    code, output = invoke(tmp_path)

    assert (code, output) == (0, f"Rewrote {stale}\n")
    assert stale.read_text() == AFTER
    assert clean.stat().st_mtime_ns == written


def test_check_prints_the_diff_and_fails_and_changes_nothing(tmp_path: Path) -> None:
    stale = tmp_path / "stale.py"
    stale.write_text(BEFORE)

    code, output = invoke("--check", tmp_path)

    assert code == 1
    assert f"+++ {stale}" in output
    assert "-LIMIT = 3\n+from typing import Final\n+\n+LIMIT: Final = 3\n" in output
    assert "1 file would be rewritten; run `make fmt`" in output
    assert stale.read_text() == BEFORE


def test_check_passes_and_says_nothing_when_no_codemod_has_anything_to_do(tmp_path: Path) -> None:
    (tmp_path / "clean.py").write_text(AFTER)

    assert invoke("--check", tmp_path) == (0, "")


def test_a_file_that_does_not_parse_fails_the_run_by_name_and_the_others_are_still_rewritten(tmp_path: Path) -> None:
    broken, stale = tmp_path / "broken.py", tmp_path / "stale.py"
    broken.write_text("LIMIT = (\n")
    stale.write_text(BEFORE)

    code, output = invoke(tmp_path)

    assert code == 1
    assert f"{broken}: final-constants: " in output
    assert "1 file could not be rewritten" in output
    assert stale.read_text() == AFTER
    assert broken.read_text() == "LIMIT = (\n"


def test_many_files_are_rewritten_as_few_are(tmp_path: Path) -> None:
    for i in range(20):
        (tmp_path / f"m{i:02}.py").write_text(BEFORE if i % 2 else AFTER)

    rewrites = run.rewrite_all([tmp_path], list(CODEMODS))

    assert [r.path.name for r in rewrites] == [f"m{i:02}.py" for i in range(20)]
    assert [r.changed for r in rewrites] == [bool(i % 2) for i in range(20)]
    assert {r.after for r in rewrites} == {AFTER}


def test_list_names_every_codemod_and_needs_no_path() -> None:
    code, output = invoke("--list")

    assert code == 0
    assert output.splitlines() == [f"{name}  {codemod.DESCRIPTION}" for name, codemod in CODEMODS.items()]


def test_no_path_is_a_usage_error() -> None:
    code, output = invoke()

    assert code == 2
    assert "Give the files or directories to rewrite." in output


@pytest.mark.parametrize("name", list(CODEMODS))
def test_every_codemod_has_a_description_and_leaves_alone_what_it_wrote(name: str) -> None:
    once = run.rewrite(BEFORE, [name])

    assert CODEMODS[name].DESCRIPTION
    assert run.rewrite(once, [name]) == once
