# M68. Messages to running workers

DESIGN §44, TRUST_MODEL T1, T4, and T8. The operator tells a running worker, planner, or task's run that its scope
changed, without ending it: `canopy reply run:ID` with words, or the ticket's reply form in the web UI, recorded as an
operator message; canopy's plugin adds a `[canopy]` line saying only that a message waits, and the text comes back
from canopy's own `messages` tool, which nothing can forge; a message a run fetched and reported on is not dispatched
again, and one it did not stays for the next run's prompt.

Status: done 2026-11-11.
Learned: closed on the operator's own use, before the checks in Accept ran one by one; a message heard mid-run,
sandboxed and not, and the week's count of messages fetched, are SCENARIOS S80. Stage 0's source read found that
neither OpenCode refuses a user turn sent to a busy session: 2 queues it cleanly, and 1 merges it only if it names the
run's agent and model, and can lose one sent as the loop ends. A queued turn stays rejected, since it gives the plugin
a power T4 says it has not. The `messages` tool reads the run's answers directory, not the journal, which a sandboxed
run's servers cannot read.
Next: stage 2, a notice set or cleared mid-run, was not built, and is on the deferred list.
