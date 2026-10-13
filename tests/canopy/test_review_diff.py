"""A review run's diff, read back for the web UI's review page (DESIGN §21, Reading reviews)."""

import os
from pathlib import Path

import pytest

from canopy.core import review_diff

DIFF = """\
diff --git a/src/retry.py b/src/retry.py
index 1111111..2222222 100644
--- a/src/retry.py
+++ b/src/retry.py
@@ -40,4 +40,5 @@ def retry(call):
     attempts = 0
-    while attempts < 3:
+    while True:
+        attempts = 0
         call()
         attempts += 1
diff --git a/docs/old name.md b/docs/new name.md
similarity index 90%
rename from docs/old name.md
rename to docs/new name.md
diff --git a/logo.png b/logo.png
new file mode 100644
index 0000000..3333333
Binary files /dev/null and b/logo.png differ
diff --git a/gone.txt b/gone.txt
deleted file mode 100644
--- a/gone.txt
+++ /dev/null
@@ -1 +0,0 @@
-bye
\\ No newline at end of file
"""


def test_a_diff_parses_into_files_hunks_and_numbered_lines() -> None:
    diff = review_diff.parse(DIFF)
    assert [(f.path, f.old_path, f.binary) for f in diff.files] == [
        ("src/retry.py", None, False),
        ("docs/new name.md", "docs/old name.md", False),
        ("logo.png", None, True),
        ("gone.txt", None, False),
    ]
    [hunk] = diff.files[0].hunks
    assert hunk.header == "def retry(call):"
    assert [(ln.kind, ln.old, ln.new, ln.text) for ln in hunk.lines] == [
        ("ctx", 40, 40, "    attempts = 0"),
        ("del", 41, None, "    while attempts < 3:"),
        ("add", None, 41, "    while True:"),
        ("add", None, 42, "        attempts = 0"),
        ("ctx", 42, 43, "        call()"),
        ("ctx", 43, 44, "        attempts += 1"),
    ]
    assert [(ln.kind, ln.old, ln.text) for ln in diff.files[3].hunks[0].lines] == [("del", 1, "bye")]
    assert not diff.truncated


@pytest.mark.parametrize(
    ("location", "anchored"),
    [
        ("src/retry.py:41", (0, 41)),
        ("src/retry.py:L42-44", (0, 42)),
        ("./src/retry.py:43", (0, 43)),
        ("retry.py:44", (0, 44)),  # a unique suffix
        ("src/retry.py:7", (0, None)),  # the file, not a line the diff shows
        ("src/retry.py", (0, None)),
        ("docs/old name.md", (1, None)),
        ("elsewhere.py:3", (None, None)),
        ("", (None, None)),
    ],
)
def test_a_finding_anchors_where_the_diff_shows_its_line(
    location: str, anchored: tuple[int | None, int | None]
) -> None:
    assert review_diff.anchor(review_diff.parse(DIFF), location) == anchored


def test_a_deleted_line_is_not_an_anchor() -> None:
    # A finding's line is in the commit it reviewed: the new side.
    assert review_diff.anchor(review_diff.parse(DIFF), "gone.txt:1") == (3, None)


def test_control_characters_become_spaces_and_tabs_stay() -> None:
    diff = review_diff.parse("diff --git a/x b/x\n--- a/x\n+++ b/x\n@@ -1 +1 @@\n-a\x1b[2J\n+\tb\x07\n")
    assert [ln.text for ln in diff.files[0].hunks[0].lines] == ["a [2J", "\tb "]


def test_bounds_cut_a_diff_and_say_so(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(review_diff, "MAX_LINES", 3)
    diff = review_diff.parse(DIFF)
    assert diff.truncated
    assert sum(len(h.lines) for f in diff.files for h in f.hunks) == 3
    monkeypatch.setattr(review_diff, "MAX_FILES", 1)
    assert [f.path for f in review_diff.parse(DIFF).files] == ["src/retry.py"]
    long = review_diff.parse(f"diff --git a/x b/x\n@@ -1 +1 @@\n+{'y' * 5000}\n")
    assert len(long.files[0].hunks[0].lines[0].text) == review_diff.MAX_LINE_CHARS


def test_reading_a_diff_beside_a_log(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    path = review_diff.path_for(tmp_path / "7.log")
    assert path == tmp_path / "7.diff"
    assert review_diff.read(path) is None
    path.write_text(DIFF)
    found = review_diff.read(path)
    assert found is not None
    assert len(found.files) == 4
    assert not found.truncated
    monkeypatch.setattr(review_diff, "MAX_BYTES", 200)
    cut = review_diff.read(path)
    assert cut is not None
    assert cut.truncated


def test_a_diff_that_is_not_a_regular_file_is_not_read(tmp_path: Path) -> None:
    target = tmp_path / "secret"
    target.write_text(DIFF)
    link = tmp_path / "1.diff"
    link.symlink_to(target)
    assert review_diff.read(link) is None
    fifo = tmp_path / "2.diff"
    os.mkfifo(fifo)
    assert review_diff.read(fifo) is None
