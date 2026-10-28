"""`infra.hangup` and SIGHUP in `canopy loop`: a terminal hanging up ends the loop, and a deliberate SIGHUP reloads.

A terminal can hang up only on the process it controls, so each case runs in a child of its own, in a new session.
"""

import signal
import sys
import textwrap
from typing import Final

from canopy.infra import procs

# The child takes a pseudo-terminal as its controlling terminal, then hangs it up by closing the end a terminal emulator
# would hold. SIGHUP is ignored so the child lives to print what it saw.
_HANG_UP: Final = """
import fcntl, os, pty, signal, termios
from canopy.infra import hangup
signal.signal(signal.SIGHUP, signal.SIG_IGN)
emulator, terminal = pty.openpty()
if CONTROLLED:
    fcntl.ioctl(terminal, termios.TIOCSCTTY, 0)
with hangup.watch() as hung_up:
    before = hung_up()
    os.close(emulator)
    print(before, hung_up())
"""

# SIGHUP in the loop, with the terminal said to have hung up or not.
_LOOP: Final = """
import os, signal
from canopy.loop import repeat, reread
if IGNORED:
    signal.signal(signal.SIGHUP, signal.SIG_IGN)
stop, reload = repeat.Stop(), reread.Reload()
with repeat.signals(stop, reload, hung_up=lambda: HUNG_UP):
    os.kill(os.getpid(), signal.SIGHUP)
    print("survived", reload.requested, stop.requested)
"""


def child(script: str, **values: bool) -> procs.Result:
    for name, value in values.items():
        script = script.replace(name.upper(), str(value))
    return procs.SubprocessRunner().run([sys.executable, "-c", textwrap.dedent(script)], timeout=30)


def test_a_hangup_is_seen_on_the_controlling_terminal() -> None:
    result = child(_HANG_UP, controlled=True)
    assert result.returncode == 0, result.stderr
    assert result.stdout.split() == ["False", "True"]


def test_with_no_controlling_terminal_nothing_is_a_hangup() -> None:
    result = child(_HANG_UP, controlled=False)
    assert result.returncode == 0, result.stderr
    assert result.stdout.split() == ["False", "False"]


def test_sighup_asks_for_a_reload_while_the_terminal_is_there() -> None:
    result = child(_LOOP, ignored=False, hung_up=False)
    assert result.returncode == 0, result.stderr
    assert result.stdout.split() == ["survived", "True", "False"]


def test_a_hangup_ends_the_loop_as_sighup_always_did() -> None:
    result = child(_LOOP, ignored=False, hung_up=True)
    assert result.returncode == -signal.SIGHUP
    assert "survived" not in result.stdout


def test_under_nohup_the_loop_outlives_its_terminal_and_reloads() -> None:
    result = child(_LOOP, ignored=True, hung_up=True)
    assert result.returncode == 0, result.stderr
    assert result.stdout.split() == ["survived", "True", "False"]
