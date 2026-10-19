# M1. Read-only tick

Config, journal, lock, and treehouse; `canopy init`, `tick --dry-run`, `decide`, `attention`, and `status`; the
OpenCode deny canary.

Status: done 2026-09-24.
Learned: dry runs found plans a live tick would not carry out, so a dry-run dispatch checks the guards (D036). The first
real failures were setup, not the loop: treehouse versions and the overseer's missing GitHub MCP server. Accept was
narrowed from days of dry runs to sensible plans on an empty queue and on a labeled candidate.
