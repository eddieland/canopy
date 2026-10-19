# M51. The loop, detached

DESIGN §6 (The loop), D042. `canopy daemon start`, `stop`, and `status` run `canopy loop` in its own session, so it
outlives the terminal, without tmux or anything installed with the OS.

Status: done 2026-10-17.
Learned: the live check ran in the toy workspace (TOY_REPOS), not the operator's own: started from a shell that then
exited, the daemon kept ticking and served the web UI on that workspace's private port, and `stop` during a tick waited
for it to end `ok`. A daemon with no listener secret ticks but serves nothing, and says so only in `daemon.log`.
