---
description: Writes for a coworker new to the code: PRs, commits, replies, and plans that say why as well as what.
---

Write for a coworker who is new to this code and will review or maintain the change. A PR's description says why as
well as what: the problem the work solves, why this approach over the obvious other one, and what a reviewer should
read first. Name the parts of the code it touches and how they fit together, a sentence or two each.

A commit message says why the change is made, not only what it does. A comment in the code explains what a reader
could not see from the code itself, such as a constraint, an edge case, or why something is not done the obvious way;
it never narrates what the next line does.

When you reply to a review comment, say what you changed and why, so the reviewer can follow without reading the diff
again.

Explain without padding: a short change gets a short explanation. When a PR already has a body, edit it only to
correct or complete it, never to restyle it or summarize the run.

When you plan, say why each step is there as well as what it does.
