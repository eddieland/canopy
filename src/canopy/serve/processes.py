"""The processes on the machine the loop runs on, for the system resources page: what is keeping it busy.

Read from Linux's `/proc`: each process's `stat` for its parent, state, processor time, memory, threads, and start;
its `cmdline`; and its directory's owner for the account it runs as. Off Linux there is no `/proc`, and nothing is
read: the standard library has no other way to the machine's processes, and starting `ps` for a page that asks every
ten seconds is not worth it.

A process's processor time is a count that only grows, so its share of the processors is how much the count grew
between two reads, over the time between them. The watch keeps the last read (`ProcessWatch`), and each answer is
measured against the one before it, which is the page's previous ask, ten seconds earlier while it is open. With none
recent, it reads twice, a second apart, so the first answer is already a measure and not a lifetime's average. Nothing
is read while no page asks.

The kernel's own threads, which its flags mark, are left out: they are hundreds on a busy machine, have no command
line, and are nothing the operator can stop. Not process 2 and its children, as on a machine's own: in a container's
process namespace, process 2 may be anything, the loop's parent among them.

A command line holds whatever its program was given, a token passed as an argument included; the page is behind the
listener secret (TRUST_MODEL T8), and `ps` shows the same to anyone on the machine.
"""

from __future__ import annotations

import os
import pwd
import threading
import time
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import TYPE_CHECKING

from canopy.serve import host
from canopy.serve.schema.host import HostProcess, HostProcesses, ProcessState

if TYPE_CHECKING:
    from collections.abc import Callable, Mapping
    from pathlib import Path

#: The most of a command line kept: enough to tell one build from another, not a whole generated argument list.
COMMAND_CHARS = 400
#: Seconds between the two reads of a first answer, or of one after the page was closed for a while.
BASELINE_SECONDS = 1.0
#: Seconds after which the last read is too old to measure against: the page was closed, and a share over minutes would
#: hide what is busy now.
STALE_SECONDS = 60.0
#: Seconds within which another ask is answered with the last answer: two tabs open, or a page and its refetch, would
#: otherwise measure over a moment too short to mean anything.
FRESH_SECONDS = 1.0
#: The flag `/proc/<pid>/stat` sets on a kernel thread (`PF_KTHREAD`).
_KERNEL_THREAD = 0x00200000
#: `/proc/<pid>/stat`'s state letters, as the page names them; any other is `other`.
_STATES: Mapping[str, ProcessState] = {
    "R": "running",
    "D": "disk",
    "S": "sleeping",
    "I": "idle",
    "T": "stopped",
    "t": "stopped",
    "Z": "zombie",
}


class ProcessWatch:
    """The machine's processes, each answer measured against the read before it, kept here between asks.

    Asked from the requests' threads, so each ask holds the lock, a first one through its second's wait.
    """

    def __init__(
        self,
        proc: Path = host.PROC,
        *,
        clock: Callable[[], float] = time.monotonic,
        wait: Callable[[float], None] = time.sleep,
        now: Callable[[], datetime] = lambda: datetime.now(UTC),
    ) -> None:
        """Read the processes `proc` lists, timing reads by `clock`, waiting by `wait`, and dating answers by `now`."""
        self.proc = proc
        self._clock = clock
        self._wait = wait
        self._now = now
        self._lock = threading.Lock()
        self._last: _Read | None = None
        self._served: HostProcesses | None = None
        self._users: dict[int, str] = {}

    def read(self) -> HostProcesses:
        """The processes on the machine now, with the processors each kept busy since the read before.

        Returns:
            Them, by process id; with no processes where `proc` is not there, as off Linux.
        """
        with self._lock:
            if not self.proc.is_dir():
                return HostProcesses(read_at=self._now(), over_seconds=None, processes=None)
            last = self._last
            if last is not None and self._served is not None and self._clock() - last.at < FRESH_SECONDS:
                return self._served
            if last is None or self._clock() - last.at > STALE_SECONDS:
                last = self._take()
                self._wait(BASELINE_SECONDS)
            taken = self._take()
            served = self._measured(last, taken)
            self._last, self._served = taken, served
            return served

    def _take(self) -> _Read:
        found: dict[tuple[int, int], _Seen] = {}
        page = os.sysconf("SC_PAGE_SIZE")
        for entry in self.proc.iterdir():
            if not entry.name.isdigit():
                continue
            seen = _seen(entry, page)
            if seen is not None and not seen.kernel:
                found[seen.pid, seen.start] = seen
        return _Read(at=self._clock(), found=found)

    def _measured(self, last: _Read, taken: _Read) -> HostProcesses:
        # A process the last read did not find started since, so all the time it used is in the interval.
        over = max(taken.at - last.at, 1e-9)
        tick = os.sysconf("SC_CLK_TCK")
        booted = host.booted_at(self.proc)
        processes: list[HostProcess] = []
        for key, seen in sorted(taken.found.items()):
            before = last.found.get(key)
            used = seen.ticks - (before.ticks if before is not None else 0)
            processes.append(
                HostProcess(
                    pid=seen.pid,
                    parent=seen.parent,
                    name=seen.name,
                    command=seen.command,
                    user=self._user(seen.uid),
                    state=seen.state,
                    cpu=round(max(0, used) / tick / over, 3),
                    rss=seen.rss,
                    threads=seen.threads,
                    started_at=None
                    if booted is None
                    else datetime.fromtimestamp(booted.timestamp() + seen.start / tick, UTC),
                ),
            )
        return HostProcesses(read_at=self._now(), over_seconds=round(over, 2), processes=processes)

    def _user(self, uid: int) -> str:
        # Kept by uid for the server's life: an account renamed while it runs is rare, and a lookup per process per read
        # reads /etc/passwd hundreds of times.
        name = self._users.get(uid)
        if name is None:
            try:
                name = pwd.getpwuid(uid).pw_name
            except KeyError:
                name = str(uid)
            self._users[uid] = name
        return name


@dataclass(frozen=True)
class _Seen:
    """One process as a read found it."""

    pid: int
    parent: int
    name: str
    command: str
    uid: int
    state: ProcessState
    #: Whether it is one of the kernel's own threads.
    kernel: bool
    #: Its processor time so far, its own and the kernel's for it, in clock ticks.
    ticks: int
    rss: int
    threads: int
    #: When it started, in clock ticks after the machine did: with the pid, what tells it from a later process that
    #: took the same pid.
    start: int


@dataclass(frozen=True)
class _Read:
    """Every process one read found, and when, on the watch's clock."""

    at: float
    found: Mapping[tuple[int, int], _Seen]


def _seen(directory: Path, page: int) -> _Seen | None:
    # None for a process that ended between the listing and the read, or whose files say what this cannot parse.
    try:
        stat = (directory / "stat").read_text(encoding="utf-8", errors="replace")
        argv = (directory / "cmdline").read_bytes()
        uid = directory.stat().st_uid
    except OSError:
        return None
    # The second field, the name, is in parentheses and may hold spaces and parentheses itself, so it runs to the last
    # closing one, and the fields after it are counted from there: the state is the third field, the first after it,
    # and the flags the ninth.
    head, _, tail = stat.rpartition(")")
    fields = tail.split()
    try:
        return _Seen(
            pid=int(head.partition(" ")[0]),
            parent=int(fields[1]),
            name=_printable(head.partition("(")[2]),
            command=_command(argv),
            uid=uid,
            state=_STATES.get(fields[0], "other"),
            kernel=bool(int(fields[6]) & _KERNEL_THREAD),
            ticks=int(fields[11]) + int(fields[12]),
            rss=int(fields[21]) * page,
            threads=int(fields[17]),
            start=int(fields[19]),
        )
    except (ValueError, IndexError):
        return None


def _command(argv: bytes) -> str:
    # The arguments are NUL-terminated; a program that rewrote its own may have left spaces or more NULs at the end.
    words = [w.decode("utf-8", errors="replace") for w in argv.split(b"\0") if w]
    return _printable(" ".join(words).strip())[:COMMAND_CHARS]


def _printable(text: str) -> str:
    # An argument may hold a newline or a terminal's escape; the page shows one line of text.
    return "".join(c if c.isprintable() else " " for c in text)
