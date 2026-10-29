"""The API's types for the system resources page: the machine the loop runs on, and the loop's own process.

Built on `schema.Model`, as every API type is (schema/__init__.py). A figure the operating system does not give from
the standard library, such as the memory a Mac has available, is None, and the UI says it was not read.
"""

from __future__ import annotations

from datetime import datetime
from typing import Annotated, Literal

from pydantic import Field

from canopy.serve.schema import Model

type DiskUse = Annotated[
    Literal["workspace", "journal", "temp"],
    Field(
        description="What canopy keeps on a disk: `workspace` its repositories and worktrees, `journal` the journal "
        "and the runs' logs, `temp` the temporary directory its agents and their builds write to.",
    ),
]


class Cpu(Model):
    """The machine's processors and how busy they are."""

    cores: int | None
    """How many processors this process may run on; None when the operating system does not say."""
    load: list[float] | None
    """The load averages over the last 1, 5, and 15 minutes; None where the operating system keeps none."""


class Memory(Model):
    """The machine's memory and swap, in bytes."""

    total: int | None
    """All of its memory; None when the operating system does not say."""
    available: int | None
    """What a new process could use without swapping; None where only Linux's `/proc/meminfo` says."""
    swap_total: int | None
    """All of its swap; None where only Linux's `/proc/meminfo` says."""
    swap_free: int | None
    """The swap not in use; None where only Linux's `/proc/meminfo` says."""


class Disk(Model):
    """One filesystem canopy writes to, in bytes, with what it keeps there."""

    holds: list[DiskUse]
    """What canopy keeps on it, in the order the page names them; two uses on one filesystem share a disk."""
    path: str
    """The directory read for the first of `holds`."""
    total: int
    """Its size."""
    free: int
    """What a process that is not root may still write."""
    floor: int | None
    """The free space under which a tick runs no overseer, `loop.min_free_disk_mib` in bytes (DESIGN §6), on a disk
    with the workspace or the journal; None on another, or while the check is off."""


class LoopProcess(Model):
    """The process that serves the page, which in `canopy loop` is the loop itself."""

    pid: int
    """Its process id."""
    started_at: datetime | None
    """When it started; None where only Linux's `/proc` says."""
    rss: int | None
    """The memory it holds now, in bytes; None where only Linux's `/proc` says."""
    peak_rss: int | None
    """The most memory it has held at once, in bytes; None when the operating system does not say."""
    threads: int
    """How many threads it runs."""
    open_files: int | None
    """How many files, sockets, and pipes it holds open; None where only Linux's `/proc` says."""
    max_open_files: int | None
    """How many it may hold open at once, its soft limit; None when unlimited."""


class HostResources(Model):
    """The machine the loop runs on, as read when it was asked."""

    hostname: str
    """The machine's name."""
    system: str
    """Its operating system and release, as `uname` names them, such as `Linux 6.8.0`."""
    machine: str
    """Its processor architecture, such as `x86_64` or `arm64`."""
    python: str
    """The Python version canopy runs on."""
    booted_at: datetime | None
    """When the machine started; None where only Linux's `/proc` says."""
    read_at: datetime
    """When these figures were read."""
    cpu: Cpu
    """Its processors."""
    memory: Memory
    """Its memory."""
    disks: list[Disk]
    """Each filesystem canopy writes to, the workspace's first; one that could not be read is left out."""
    process: LoopProcess
    """The loop's own process."""


class DiskSample(Model):
    """One disk's free space at a reading."""

    path: str
    """The disk's directory, as `Disk.path` names it, so the page finds the disk the sample is of."""
    free: int
    """What a process that is not root could still write, in bytes."""


class HostSample(Model):
    """What the system resources page's graphs draw of one reading of the machine."""

    at: datetime
    """When it was read."""
    load: float | None
    """The load average over the last minute; None where the operating system keeps none."""
    memory_used: int | None
    """The memory not available to a new process, in bytes; None where only Linux's `/proc/meminfo` says."""
    rss: int | None
    """The memory the loop's process held, in bytes; None where only Linux's `/proc` says."""
    disks: list[DiskSample]
    """Each disk read, in the order `HostResources.disks` has them."""


class HostHistory(Model):
    """The readings of the machine the server keeps in memory, from when it started: the last hour's at most."""

    every_seconds: int
    """The seconds from one reading to the next."""
    kept: int
    """How many readings it keeps at most; past that the oldest is dropped."""
    samples: list[HostSample]
    """The readings, oldest first. A gap longer than `every_seconds` is a time the server was not reading."""
