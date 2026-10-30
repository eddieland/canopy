# M55. Trivial work skips its plan

REQUIREMENTS R22, DESIGN §25, TRUST_MODEL T1 and T7, D126. Asked for by the operator (2026-10-17): with plans on, a
typo fix or a one-line config change should not wait on the operator's approval of a plan nobody needed. Delivered by
the planner's own word rather than a judge before it: under the private `policy.planner_may_approve`, at `strict`,
`normal`, or `lenient`, the planner that wrote a plan may say it needs no review, with a reason, and the harness
approves it as the planner's, failing closed; a plan touching security, credentials, destructive data changes, or
migrations always waits on the operator.

Status: done 2026-10-30.
Learned: the sketch's cheaper triage agent was built and removed (D126): it judged too few tickets trivial for its runs
to save what they cost, while the planner has already read the ticket and the code, so its word costs no run. The plan
run stays and the operator's click goes. Closed on the operator's real use: the plans it approved were ones the operator
agreed needed no review. The Accept's live checks were for triage, so none move to SCENARIOS.
Next: in use, `normal` errs strict, holding back plans the operator would have let through; its bar in the planner's
prompt can loosen.
