# M0. Skeleton

Repository layout, `make check` in CI, the treehouse and agent fakes, and `procs.py` as the one subprocess boundary.

Status: done 2026-09-23.
Learned: the treehouse fake follows treehouse's real JSON shapes and exit codes, read from its source. The subprocess
boundary is a lint rule (D015), and a timeout kills the child's whole process group.
