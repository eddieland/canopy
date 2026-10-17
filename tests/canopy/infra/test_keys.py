"""`infra.keys`: single keypresses from a terminal, here a pseudo-terminal this test types into."""

import io
import os
import pty
import termios
import time
from collections.abc import Callable, Generator

import pytest

from canopy.infra import keys


@pytest.fixture
def terminal() -> Generator[tuple[int, int]]:
    """A pseudo-terminal: the end a person types into, and the end canopy reads."""
    typed, read = pty.openpty()
    yield typed, read
    os.close(typed)
    os.close(read)


def read_soon(pressed: Callable[[], str]) -> str:
    """What `pressed` returns once the pseudo-terminal has passed on what was typed."""
    deadline = time.monotonic() + 5
    while not (text := pressed()) and time.monotonic() < deadline:
        time.sleep(0.01)
    return text


def test_keys_arrive_without_enter_and_the_terminal_is_put_back(terminal: tuple[int, int]) -> None:
    typed, read = terminal
    before = termios.tcgetattr(read)
    with open(read, closefd=False) as stream, keys.listen(stream) as pressed:
        assert pressed is not None
        assert not termios.tcgetattr(read)[3] & (termios.ICANON | termios.ECHO)
        assert pressed() == ""  # nothing typed yet, and it did not wait for anything
        os.write(typed, b"xt")
        assert read_soon(pressed) == "xt"
        assert pressed() == ""  # each key is returned once
    assert termios.tcgetattr(read) == before


def test_no_terminal_reads_no_keys() -> None:
    with keys.listen(None) as pressed:
        assert pressed is None
    with keys.listen(io.StringIO("t")) as pressed:  # no descriptor, as when pytest captures stdin
        assert pressed is None
    r, w = os.pipe()
    try:
        with open(r, closefd=False) as stream, keys.listen(stream) as pressed:
            assert pressed is None
    finally:
        os.close(r)
        os.close(w)
