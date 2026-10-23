# M41. Limits and trust settings from the web UI

REQUIREMENTS R16. A Limits and trust page under Settings changes the limits in `capacity`, `policy`, and `loop`, within
ceilings in code, and makes trust settings stricter, writing the workspace's private file (M49) in place with its
comments kept and then asking the loop to reload (DESIGN §12, §22, TRUST_MODEL T8, D128, D129).

Status: done 2026-10-16.
Learned: checking each bound on the values the edited copy loads to, rather than on the request, keeps the rules
whole whatever shape a request takes, and lets the page tighten a value the file set past its ceiling. Built first
against the user file, then moved to the private file once M49 was in: a key from the user file is written to the
private file whole, since `capacity.repo_slots` and the trust lists are each one key and the private file's would
otherwise drop what the page did not change. The operator closed it with its live check unrun, on request; that check
is SCENARIOS S65.
