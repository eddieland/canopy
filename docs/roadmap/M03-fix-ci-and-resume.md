# M3. Fix-CI and resume

Phases for red CI, requested changes, and human replies; the `fix-ci` and `resume` workers; attempt limits, cooldowns,
per-ticket cursors, and notification of the attention list.

Status: done 2026-10-13.
Learned: closed on the operator's real use; a check taken to the limit and a conflicted PR are SCENARIOS S9 to S11.
Authorship is checked when a comment is read, so adding an account to `authorized_repliers` authorizes its earlier
comments too. A bot's review comments drive `resume`, though they never count as approval.
