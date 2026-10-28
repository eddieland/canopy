"""The system resources page's read: the machine the loop runs on, and the loop's own process.

Each read is a handful of small files under `/proc` and a `statvfs` per directory, no process started, so it costs less
than a journal read and the page asks for it every few seconds while it is open. Everything comes from the standard
library: on Linux from `/proc`, elsewhere what `os`, `resource`, and `shutil` give, which leaves out the memory
available, the swap, when the machine and the process started, and what the process holds; those are None there.

A disk is each filesystem canopy writes to: the workspace's, with its repositories and worktrees, where agents check
out and build; the journal's, with the runs' logs; and the temporary directory, which builds fill. Two on one
filesystem are one disk, so its free space is not counted twice.
"""

from __future__ import annotations

import os
import platform
import resource
import shutil
import sys
import tempfile
import threading
from datetime import UTC, datetime
from pathlib import Path
from typing import TYPE_CHECKING

from canopy.serve.schema.host import Cpu, Disk, DiskUse, HostResources, LoopProcess, Memory

if TYPE_CHECKING:
    from collections.abc import Iterable, Mapping

    from canopy.core.context import Context

#: Where Linux keeps what the kernel knows of the machine and each process.
PROC = Path("/proc")
#: The unit `/proc/meminfo` and `/proc/self/status` count in.
_KIB = 1024
#: The uses on a disk the tick's free-space check reads (DESIGN §6).
_CHECKED: frozenset[DiskUse] = frozenset({"workspace", "journal"})


def read(ctx: Context) -> HostResources:
    """The machine `ctx`'s loop runs on, read now.

    Returns:
        Its figures, with the disks under the workspace, the journal, and the temporary directory.
    """
    places: list[tuple[DiskUse, Path]] = [
        ("workspace", ctx.workspace.root),
        ("journal", ctx.state_dir),
        ("temp", Path(tempfile.gettempdir())),
    ]
    floor = ctx.config.loop.min_free_disk_mib * _KIB * _KIB
    return read_at(places, proc=PROC, now=datetime.now(UTC), floor=floor or None)


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
    booted = _booted(proc)
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


def _booted(proc: Path) -> datetime | None:
    # /proc/stat's `btime`: the seconds since the epoch at which the machine started.
    try:
        lines = (proc / "stat").read_text(encoding="utf-8").splitlines()
    except OSError:
        return None
    for line in lines:
        name, _, value = line.partition(" ")
        if name == "btime" and value.strip().isdigit():
            return datetime.fromtimestamp(int(value), UTC)
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
