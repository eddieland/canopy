"""The mock's machine, for the system resources page of `python -m canopy.serve --mock`.

A fixed reading, never the host's: the pages show the same machine on every run, and the public demo (demo.py) tells
nobody about the machine it runs on. Every figure is one canopy reads on Linux, so the page shows them all, and none
is under pressure, so the header's readout is calm. Its hour of readings (`samples`) is as fixed: a build ran twenty
minutes before, so the graphs have a shape to show.
"""

from __future__ import annotations

import math
from datetime import datetime, timedelta

from canopy.serve import host
from canopy.serve.schema.host import Cpu, Disk, DiskSample, HostResources, HostSample, LoopProcess, Memory

_GIB = 1024**3
_MIB = 1024**2
#: The minutes before the last reading a build started, and ended: the hour's readings rise and settle with it.
_BUILD_START, _BUILD_END = 25, 15


def machine(now: datetime) -> HostResources:
    """The mock's machine as read at `now`.

    Returns:
        A 12-core Linux box with the workspace and journal on one disk and the temporary directory on another.
    """
    return HostResources(
        hostname="build-box",
        system="Linux 6.8.0",
        machine="x86_64",
        python="3.13.1",
        booted_at=now - timedelta(days=9, hours=4),
        read_at=now,
        cpu=Cpu(cores=12, load=[2.41, 1.87, 1.52]),
        memory=Memory(total=64 * _GIB, available=23 * _GIB + 410 * _MIB, swap_total=8 * _GIB, swap_free=7 * _GIB),
        disks=[
            Disk(
                holds=["workspace", "journal"],
                path="/home/operator/acme",
                total=931 * _GIB,
                free=412 * _GIB,
                floor=2 * _GIB,
            ),
            Disk(holds=["temp"], path="/tmp", total=32 * _GIB, free=27 * _GIB + 300 * _MIB, floor=None),  # noqa: S108
        ],
        process=LoopProcess(
            pid=48213,
            started_at=now - timedelta(hours=3, minutes=12),
            rss=268 * _MIB,
            peak_rss=412 * _MIB,
            threads=19,
            open_files=61,
            max_open_files=65536,
        ),
    )


def samples(now: datetime) -> host.Samples:
    """The mock's hour of readings, ending with `machine(now)`'s.

    Returns:
        A full hour, every `host.SAMPLE_SECONDS`: the load and memory rise with a build from 25 to 15 minutes before
        and settle again, the temporary directory fills while it runs and is cleared after, the workspace's disk keeps
        what it wrote, and the loop's own memory climbs slowly, as a long-lived process's does.
    """
    last = machine(now)
    readings = [_reading(now, i) for i in range(host.KEPT - 1, 0, -1)]
    return host.Samples(seeded=[*readings, host.sample(last)])


def _reading(now: datetime, back: int) -> HostSample:
    # `back` readings before the last: a smooth wobble, plus a build's bump `build` from 0 to 1 and back.
    minutes = back * host.SAMPLE_SECONDS / 60
    lasted = _BUILD_START - _BUILD_END
    running = _BUILD_END <= minutes <= _BUILD_START
    build = max(0.0, math.sin(math.pi * (_BUILD_START - minutes) / lasted)) if running else 0.0
    wobble = math.sin(back / 7) * 0.35 + math.sin(back / 23) * 0.25
    # What the build wrote to the workspace stays: before it, 1.6 GiB more was free.
    written = 0.0 if minutes < _BUILD_END else 1.6 if minutes > _BUILD_START else 1.6 * (minutes - _BUILD_END) / lasted
    return HostSample(
        at=now - timedelta(seconds=back * host.SAMPLE_SECONDS),
        load=round(max(0.2, 1.9 + wobble + 5.2 * build), 2),
        memory_used=int((40.6 + wobble * 0.8 + 9.5 * build) * _GIB),
        rss=int((268 - minutes * 0.45 + (back % 31) * 0.3) * _MIB),
        disks=[
            DiskSample(path="/home/operator/acme", free=int((412 + written) * _GIB)),
            DiskSample(path="/tmp", free=int((27.3 - 11 * build) * _GIB)),  # noqa: S108
        ],
    )
