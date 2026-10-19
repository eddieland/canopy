# M15. Sessions and recent runs

REQUIREMENTS R4 and R6, D055. Each run records its OpenCode session id and the session is titled for its ticket;
`canopy status` lists recent runs with outcome, PR, summary, cost, log, and session; `fix-ci` and `resume` start a fresh
session, with the ticket's latest runs' reports in the prompt (DESIGN §8).

Status: done 2026-10-17.
Learned: closed by the operator on a week of real use at work, with workers against OpenCode's server not built: the
session ids and the web UI's transcripts (M27) proved enough to follow a run. `run --format json` prints no event with
OpenCode's own title, so canopy names sessions rather than reading them back. A session's check against `opencode
export` is SCENARIOS S30.
Next: workers against OpenCode's server, for prompting a running worker, is on the deferred list.
