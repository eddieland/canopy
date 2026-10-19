# M32. Shadow PR reviews in the web UI

A review's page shows canopy's own review of a PR, never posted on it (D114): its findings on the diff `_review` keeps,
each dismissed from its card (`canopy dismiss review:ID N`) or, on the loop's own PRs, ticked and sent to a worker
(`canopy send review:ID N...`), and the pull requests pages make the PR the subject (DESIGN §21, §22).

Status: done 2026-10-15.
Learned: closed on the operator's request before the live check against a real PR, which is SCENARIOS S36. Sending
findings needed no new channel: it is a reply on the review's ticket naming them by number, which the overseer already
reads as the go-ahead on review feedback (D089), so the reviewer's text never reaches a prompt as the operator's words.
Next: a finding still has no id that lasts across commits, so a dismissal or a send is one run's (DESIGN §21, Open).
A review of a PR the loop does not own offers no send; publishing it on the PR after iterating on it is M43.
