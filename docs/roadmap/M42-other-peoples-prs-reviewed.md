# M42. Other people's PRs, reviewed on request

A review request is a journal fact the operator makes for a PR the loop does not own, by its URL alone, with `canopy
start URL --review` or the web UI's reviews page, and ends with `canopy stop URL`; it authorizes one review of
that PR at its head, as `review.query` would, and turns reviews on by itself. The overseer reads each one through MCP,
finds its repository by the map's clone URL, which the state block now carries, and reviews its head, or ends it with
`canopy review end` once the PR merged or closed first or is in none of the workspace's repositories; the harness ends
it when its review ends `done` (DESIGN §21, §22; `core/review_requests.py`, migration 0029).

Status: done 2026-10-16.
Learned: closed on the operator's request with the tests with the fakes and Playwright passing, before the live check
against a coworker's PR, which is SCENARIOS S39. The operator cut watching a PR, reviewed again at each new commit
until it merges, as more than MVP needs; asking again after a push reviews the new head. The operator asked that a
request name no repository, since the overseer already matches `review.query`'s PRs to one. The request needed no new
authority in code: it is the run's purpose (`request`) and one more source for `reviews_on`, and every guard of
`canopy review run` holds unchanged. Ending a request in the transaction that closes its `done` review keeps a crashed
`_review` from leaving it ended unreviewed.
Next: watching is on the deferred list. The open questions stay in DESIGN §21 (Review requests). M43's publishing
applies to these reviews first.
