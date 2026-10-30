"""The system resources page's read: the machine the loop runs on, and the loop's own process.

Each read is a handful of small files under `/proc` and a `statvfs` per directory, no process started, so it costs less
than a journal read and the page asks for it every few seconds while it is open. Everything comes from the standard
library: on Linux from `/proc`, elsewhere what `os`, `resource`, and `shutil` give, which leaves out the memory
available, the swap, when the machine and the process started, and what the process holds; those are None there.

A disk is each filesystem canopy writes to: the workspace's, with its repositories and worktrees, where agents check
out and build; the journal's, with the runs' logs; and the temporary directory, which builds fill. Two on one
filesystem are one disk, so its free space is not counted twice.

The page's graphs are the last hour of readings, which the server takes itself every SAMPLE_SECONDS from when it
starts (`sampling`), page open or not, and keeps in memory alone (`Samples`): they are the machine's, not the
journal's, and a restart that loses them loses an hour of numbers the next hour replaces.
"""

from __future__ import annotations

import asyncio
import logging
import os
import platform
import resource
import shutil
import sys
import tempfile
import threading
from collections import deque
from datetime import UTC, datetime
from pathlib import Path
from typing import TYPE_CHECKING

from canopy.serve.schema.host import (
    Cpu,
    Disk,
    DiskSample,
    DiskUse,
    HostHistory,
    HostResources,
    HostSample,
    LoopProcess,
    Memory,
)

if TYPE_CHECKING:
    from collections.abc import Callable, Iterable, Mapping

    from canopy.core.config import Config
    from canopy.core.workspace import Workspace

#: Where Linux keeps what the kernel knows of the machine and each process.
PROC = Path("/proc")
#: The unit `/proc/meminfo` and `/proc/self/status` count in.
_KIB = 1024
#: The uses on a disk the tick's free-space check reads (DESIGN §6).
_CHECKED: frozenset[DiskUse] = frozenset({"workspace", "journal"})
#: Seconds from one reading the server keeps to the next: the page's own pace, so each read it makes finds a new one.
SAMPLE_SECONDS = 10
#: How many readings the server keeps: an hour's.
KEPT = 3600 // SAMPLE_SECONDS

_log = logging.getLogger(__name__)


def read(config: Config, workspace: Workspace) -> HostResources:
    """The machine the loop on `config` and `workspace` runs on, read now.

    Returns:
        Its figures, with the disks under the workspace, the journal, and the temporary directory.
    """
    places: list[tuple[DiskUse, Path]] = [
        ("workspace", workspace.root),
        ("journal", workspace.state_dir),
        ("temp", Path(tempfile.gettempdir())),
    ]
    floor = config.loop.min_free_disk_mib * _KIB * _KIB
    return read_at(places, proc=PROC, now=datetime.now(UTC), floor=floor or None)


class Samples:
    """The last `kept` readings of the machine, oldest first, in memory: what the page's graphs draw.

    Added to by the sampler's thread and read by the requests', so each holds the lock.
    """

    def __init__(self, kept: int = KEPT, every: int = SAMPLE_SECONDS, seeded: Iterable[HostSample] = ()) -> None:
        """Keep the last `kept` readings, taken `every` seconds apart, starting from `seeded`, as the mock's does."""
        self.every = every
        self._kept: deque[HostSample] = deque(seeded, maxlen=kept)
        self._lock = threading.Lock()

    def add(self, found: HostResources) -> None:
        """Keep what the graphs draw of `found`, dropping the oldest reading once `kept` are kept."""
        taken = sample(found)
        with self._lock:
            self._kept.append(taken)

    def history(self) -> HostHistory:
        """The readings kept, oldest first.

        Returns:
            Them, with how far apart they are taken and how many are kept at most.
        """
        with self._lock:
            kept = list(self._kept)
            most = self._kept.maxlen or 0
        return HostHistory(every_seconds=self.every, kept=most, samples=kept)


def sample(found: HostResources) -> HostSample:
    """What the page's graphs draw of a reading: the load over a minute, the memory in use, the loop's, each disk free.

    Returns:
        The sample, read when `found` was.
    """
    memory = found.memory
    used = None if memory.total is None or memory.available is None else memory.total - memory.available
    return HostSample(
        at=found.read_at,
        load=found.cpu.load[0] if found.cpu.load else None,
        memory_used=used,
        rss=found.process.rss,
        disks=[DiskSample(path=d.path, free=d.free) for d in found.disks],
    )


async def sampling(read_now: Callable[[], HostResources], samples: Samples) -> None:
    """Read the machine every `samples.every` seconds into `samples`, until cancelled, starting now.

    Each read is on a thread, as the routes keep their work off the event loop. One that fails, however, is logged and
    skipped: the graph shows a gap there rather than the server stopping its readings, which nothing would notice.
    """
    while True:
        try:
            samples.add(await asyncio.to_thread(read_now))
        # Any error, not only the operating system's: one escaping would end the task with no line in the log.
        except Exception:  # noqa: BLE001
            _log.warning("could not read the host's resources", exc_info=True)
        await asyncio.sleep(samples.every)


def read_at(
    places: Iterable[tuple[DiskUse, Path]],
    *,
    proc: Path,
    now: datetime,
    floor: int | None = None,
) -> HostResources:
    """The machine as `proc` describes it, with a disk for each filesystem under `places`, read at `now`.

    Args:
        places: What canopy keeps where, each a disk's use and a directory on it.
        proc: Where Linux's `/proc` is; one that is not there leaves out what only it says.
        now: When it is read.
        floor: The free space under which a tick runs no overseer, in bytes; None while the check is off.

    Returns:
        Its figures. Those `proc` lacks, as it does off Linux, are None.
    """
    uname = platform.uname()
    meminfo = _fields(proc / "meminfo")
    booted = booted_at(proc)
    return HostResources(
        hostname=uname.node,
        system=f"{uname.system} {uname.release}".strip(),
        machine=uname.machine,
        python=platform.python_version(),
        booted_at=booted,
        read_at=now,
        # The machine's cores, not this process's affinity: the load average counts what is runnable on the whole
        # machine, inside a container too, so it is weighed against all of them.
        cpu=Cpu(cores=os.cpu_count(), load=_load()),
        memory=Memory(
            total=_kib(meminfo, "MemTotal") or _physical(),
            available=_kib(meminfo, "MemAvailable"),
            swap_total=_kib(meminfo, "SwapTotal"),
            swap_free=_kib(meminfo, "SwapFree"),
        ),
        disks=disks(places, floor),
        process=_process(proc, booted),
    )


def disks(places: Iterable[tuple[DiskUse, Path]], floor: int | None = None) -> list[Disk]:
    """A disk per filesystem under `places`, in their order, each holding every use on it.

    The tick's check reads the workspace's and the journal's filesystems (DESIGN §6), so `floor` is set on theirs alone.

    Returns:
        One disk per filesystem; a directory that is missing or unreadable is left out.
    """
    found: dict[int, Disk] = {}
    for use, path in places:
        try:
            device = path.stat().st_dev
            usage = shutil.disk_usage(path)
        except OSError:
            continue
        held = found.get(device)
        holds = [*held.holds, use] if held is not None else [use]
        checked = floor if any(h in _CHECKED for h in holds) else None
        found[device] = Disk(
            holds=holds,
            path=held.path if held is not None else str(path),
            total=usage.total,
            free=usage.free,
            floor=checked,
        )
    return list(found.values())


def booted_at(proc: Path) -> datetime | None:
    """When the machine started, as `/proc/stat`'s `btime` says: the seconds since the epoch it started at.

    Returns:
        That moment; None where `proc` has no such file, as off Linux.
    """
    try:
        lines = (proc / "stat").read_text(encoding="utf-8").splitlines()
    except OSError:
        return None
    for line in lines:
        name, _, value = line.partition(" ")
        if name == "btime" and value.strip().isdigit():
            return datetime.fromtimestamp(int(value), UTC)
    return None


def _fields(path: Path) -> dict[str, str]:
    # `Name:   value unit` lines, as /proc/meminfo and /proc/self/status write them; none where the file is not.
    try:
        text = path.read_text(encoding="utf-8")
    except OSError:
        return {}
    pairs = (line.partition(":") for line in text.splitlines())
    return {name.strip(): value.strip() for name, sep, value in pairs if sep}


def _kib(fields: Mapping[str, str], name: str) -> int | None:
    value = fields.get(name, "").split()
    return int(value[0]) * _KIB if value and value[0].isdigit() else None


def _physical() -> int | None:
    # Off Linux, the pages the machine has, which macOS and the BSDs give too.
    try:
        pages, size = os.sysconf("SC_PHYS_PAGES"), os.sysconf("SC_PAGE_SIZE")
    except (ValueError, OSError):
        return None
    return pages * size if pages > 0 and size > 0 else None


def _load() -> list[float] | None:
    try:
        return [round(n, 2) for n in os.getloadavg()]
    except OSError:
        return None


def _process(proc: Path, booted: datetime | None) -> LoopProcess:
    status = _fields(proc / "self" / "status")
    threads = status.get("Threads", "")
    try:
        # Listing the directory opens a descriptor on it, which the listing holds too.
        open_files: int | None = max(0, sum(1 for _ in (proc / "self" / "fd").iterdir()) - 1)
    except OSError:
        open_files = None
    soft, _ = resource.getrlimit(resource.RLIMIT_NOFILE)
    # ru_maxrss is in KiB on Linux and in bytes on macOS.
    peak = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
    return LoopProcess(
        pid=os.getpid(),
        started_at=_started(proc, booted),
        rss=_kib(status, "VmRSS"),
        peak_rss=(peak if sys.platform == "darwin" else peak * _KIB) or None,
        threads=int(threads) if threads.isdigit() else threading.active_count(),
        open_files=open_files,
        max_open_files=None if soft == resource.RLIM_INFINITY else soft,
    )


def _started(proc: Path, booted: datetime | None) -> datetime | None:
    # /proc/self/stat's 22nd field is when the process started, in clock ticks after the machine did. The second field,
    # its name, is in parentheses and may hold spaces, so the fields are counted from after its closing one.
    if booted is None:
        return None
    try:
        text = (proc / "self" / "stat").read_text(encoding="utf-8")
        ticks = int(text[text.rindex(")") + 2 :].split()[19])
    except (OSError, ValueError, IndexError):
        return None
    return datetime.fromtimestamp(booted.timestamp() + ticks / os.sysconf("SC_CLK_TCK"), UTC)
