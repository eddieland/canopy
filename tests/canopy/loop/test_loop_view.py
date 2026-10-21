"""What `canopy loop` draws between ticks, tested on its own: the rest is tested through `repeat.run`."""

import pytest

from canopy.loop import loop_view


@pytest.mark.parametrize(
    ("seconds", "text"),
    [(0, "0s"), (44.6, "45s"), (60, "1m"), (185, "3m 05s"), (3600, "1h"), (7800, "2h 10m"), (-3, "0s")],
)
def test_duration(seconds: float, text: str) -> None:
    assert loop_view.duration(seconds) == text
