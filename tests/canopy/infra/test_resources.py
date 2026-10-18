"""Where canopy finds its own files, and whether a checkout's web UI was built before its source changed."""

import os
from pathlib import Path
from unittest import mock

from canopy.infra import resources

# An hour apart, so the order of two files' modification times is never in doubt.
_BUILT = 1_800_000_000.0
_EARLIER = _BUILT - 3600
_LATER = _BUILT + 3600


def test_a_checkouts_build_is_behind_once_a_file_under_ui_src_is_newer(tmp_path: Path) -> None:
    dist = _checkout(tmp_path, source_at=_LATER)

    with mock.patch.object(resources, "_SOURCE", tmp_path):
        built = resources.ui_built_before_source(dist)

    assert built is not None
    assert built.timestamp() == _BUILT
    assert built.tzinfo is not None


def test_a_checkouts_build_newer_than_all_of_ui_src_is_not_behind(tmp_path: Path) -> None:
    dist = _checkout(tmp_path, source_at=_EARLIER)

    with mock.patch.object(resources, "_SOURCE", tmp_path):
        assert resources.ui_built_before_source(dist) is None


def test_a_bundled_build_is_never_behind_whatever_a_checkout_beside_it_holds(tmp_path: Path) -> None:
    _checkout(tmp_path, source_at=_LATER)
    bundled = tmp_path / "bundled"
    bundled.mkdir()

    with mock.patch.object(resources, "_SOURCE", tmp_path):
        assert resources.ui_built_before_source(bundled) is None


def _checkout(root: Path, *, source_at: float) -> Path:
    """A checkout's `ui/` under `root`, built at `_BUILT`, with one source file nested in `ui/src` at `source_at`."""
    dist = root / "ui" / "dist"
    dist.mkdir(parents=True)
    (dist / "index.html").write_text("<html></html>", encoding="utf-8")
    os.utime(dist / "index.html", (_BUILT, _BUILT))
    source = root / "ui" / "src" / "components" / "page.tsx"
    source.parent.mkdir(parents=True)
    source.write_text("export {}\n", encoding="utf-8")
    os.utime(source, (source_at, source_at))
    return dist
