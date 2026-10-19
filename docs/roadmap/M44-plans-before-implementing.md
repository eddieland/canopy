# M44. Plans before implementing

REQUIREMENTS R18, DESIGN §25. Under `policy.plan = "approve"` a ticket is planned by a read-only planner before it is
implemented; the operator edits, comments on, approves, or skips the plan from the CLI or the ticket's page, and the
`implement` and `resume` that follow work from the approved plan, kept on disk and never on the ticket.

Status: done 2026-10-17.
Learned: the live check ran in the toy workspace (TOY_REPOS): GH-11 was planned, the operator commented on a passage
from the web UI and asked for changes, the second plan answered the comment, `canopy plan --approve` approved it, and
the `implement` that followed worked from it, reporting its one departure from the plan, though not naming the plan
by number. Nothing about the plan reached the ticket or the PR. The plan a week later is SCENARIOS S41. The operator
found the plan inline on the ticket page awkward and hard to find (#636). Under the gate the overseer also dispatched
a plan for a ticket without the queue label, which the planner refused as not authorized, and a planner on a smaller
model once ended without a valid result line.
Next: #636, the plan on a page of its own.
