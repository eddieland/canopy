# M63. Attachments on tickets and tasks

DESIGN §22 and §36, TRUST_MODEL T1, T3, T6, and T8. The operator attaches text files to a ticket or a task (`canopy
attach` and `detach`, and each one's page in the web UI), within three limits under ceilings in code; each run of that
subject, a plan's and a feedback plan's among them, gets a copy in its slot, checked against its hash, named in its
prompt as data, and removed before the slot is returned.

Status: done 2026-11-11.
Learned: closed on the operator's own use, before the checks in Accept ran one by one. A run reading its subject's
attachment is what daily use shows, and the limits and the refused push are guards the tests with the fakes hold, so by
SCENARIOS' bar nothing is moved there.
