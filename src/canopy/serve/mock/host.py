"""The mock's machine, for the system resources page of `python -m canopy.serve --mock`.

A fixed reading, never the host's: the pages show the same machine on every run, and the public demo (demo.py) tells
nobody about the machine it runs on. Every figure is one canopy reads on Linux, so the page shows them all, and none
is under pressure, so the header's readout is calm.
"""

from __future__ import annotations

from datetime import datetime, timedelta

from canopy.serve.schema.host import Cpu, Disk, HostResources, LoopProcess, Memory

_GIB = 1024**3
_MIB = 1024**2


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
