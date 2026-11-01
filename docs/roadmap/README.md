# canopy roadmap

Milestones are sequential. Each has acceptance criteria that must be met before the next begins. Acceptance criteria
that involve running against real systems are the operator's job; the agent building the repo stops and asks.

Each milestone is a file in this directory, `MNN-slug.md`, its number padded to two digits so the directory lists in
order. Read the file of the milestone you work on, and the `Learned` and `Next` of the ones before it that it builds
on. A new milestone is a new file and a line in the list below.

Each milestone ends with a `Status:` line, the only place its progress is told. The list below repeats that line's
first sentence; a PR that changes the sentence changes the list's line with it. Keep it current in the same PR that
changes it: `Status: not started.` or `Status: in progress.` while work is open, and once the acceptance criteria are
met:

```text
Status: done YYYY-MM-DD.
Learned: what surprised us or turned out different from the plan.
Next: how that changes later milestones, docs, or open questions.
```

A milestone a later one absorbs ends `Status: superseded by MN (YYYY-MM-DD).`, `MN` a milestone or a range, followed
by one sentence saying how. A milestone set aside before it is done ends `Status: deferred YYYY-MM-DD.` and keeps its
bullets and Accept, and the deferred list at the end names the trigger that would bring it back.

A milestone the operator puts off ends `Status: deferred YYYY-MM-DD.`, followed by one sentence saying why, and gets a
line on the deferred list naming the trigger that would bring it back. Later milestones do not wait for it.

A done milestone is collapsed: one line on what it delivered replaces its bullets and Accept, and `Learned` and `Next`
keep only what a later milestone needs, a sentence or two each. Leave `Next` out when nothing changes. The detail lives
where it lasts: a behavior and its rationale in the design (`docs/design/`), a choice every future developer must know
in `docs/DECISIONS.md`, live numbers in `docs/MEASUREMENTS.md`, and the story in the PR. Edit a later milestone's
bullets directly when `Next` calls for it.

The operator may close a milestone on real use before every live check in its Accept has run. Its `Learned` says so,
and each check still unrun goes to `docs/SCENARIOS.md`, the live checks worth running again.

## Milestones

- [M0. Skeleton](M00-skeleton.md): done 2026-09-23.
- [M1. Read-only tick](M01-read-only-tick.md): done 2026-09-24.
- [M2. Dispatch implement](M02-dispatch-implement.md): done 2026-10-07.
- [M3. Fix-CI and resume](M03-fix-ci-and-resume.md): done 2026-10-13.
- [M4. Dependencies and stacking](M04-dependencies-and-stacking.md): done 2026-10-07.
- [M5. Shareable](M05-shareable.md): done 2026-10-13.
- [M6. Workspace](M06-workspace.md): done 2026-10-13.
- [M7. Joint multi-repo runs](M07-joint-multi-repo-runs.md): done 2026-10-13.
- [M8. Split tickets](M08-split-tickets.md): done 2026-10-13.
- [M9. Chores](M09-chores.md): done 2026-10-13.
- [M10. Notification sinks](M10-notification-sinks.md): done 2026-10-13.
- [M11. Reviews](M11-reviews.md): done 2026-10-13.
- [M12. The loop](M12-the-loop.md): done 2026-10-13.
- [M13. Spend-paced loop](M13-spend-paced-loop.md): done 2026-10-18.
- [M14. PR-scoped work](M14-pr-scoped-work.md): done 2026-10-22.
- [M15. Sessions and recent runs](M15-sessions-and-recent-runs.md): done 2026-10-17.
- [M16. Worktree setup for large monorepos](M16-worktree-setup-for-monorepos.md): done 2026-10-13.
- [M17. Declared repositories and pools](M17-declared-repositories-and-pools.md): done 2026-10-13.
- [M18. Private tickets](M18-private-tickets.md): done 2026-10-13.
- [M19. Tracker comments in the journal](M19-tracker-comments-in-the-journal.md): done 2026-10-13.
- [M20. Web UI](M20-web-ui.md): done 2026-10-13.
- [M21. Idle-paced loop](M21-idle-paced-loop.md): done 2026-10-13.
- [M22. Trusted reviewers](M22-trusted-reviewers.md): done 2026-10-13.
- [M23. Chores in the web UI](M23-chores-in-the-web-ui.md): done 2026-10-13.
- [M24. Ticks in the web UI](M24-ticks-in-the-web-ui.md): done 2026-10-13.
- [M25. Workers report flaky CI](M25-workers-report-flaky-ci.md): done 2026-10-30.
- [M26. Sandboxed workers, opt-in](M26-sandboxed-workers-opt-in.md): in progress.
- [M27. Session transcripts in the web UI](M27-session-transcripts-in-the-web-ui.md): done 2026-10-13.
- [M28. Overseer reliability from the first live session](M28-overseer-reliability.md): done 2026-10-14.
- [M29. Probe-gated overseer](M29-probe-gated-overseer.md): superseded by M36 to M39 (2026-10-15).
- [M30. Fewer re-reads per tick](M30-fewer-re-reads-per-tick.md): superseded by M37 (2026-10-15).
- [M31. Search in the web UI](M31-search-in-the-web-ui.md): done 2026-10-13.
- [M32. Shadow PR reviews in the web UI](M32-shadow-pr-reviews-in-the-web-ui.md): done 2026-10-15.
- [M33. Spend by what it bought](M33-spend-by-what-it-bought.md): done 2026-10-14.
- [M34. A cacheable overseer prompt](M34-a-cacheable-overseer-prompt.md): done 2026-10-15.
- [M35. Temporary notices to workers](M35-temporary-notices-to-workers.md): done 2026-10-15.
- [M36. Connectors: the world observed into the journal, in shadow](M36-connectors-in-shadow.md): done 2026-10-29.
- [M37. The overseer reads the journal](M37-the-overseer-reads-the-journal.md): done 2026-10-30.
- [M38. The harness decides what needs no judgment](M38-the-harness-decides.md): in progress.
- [M39. A tick without the overseer](M39-a-tick-without-the-overseer.md): in progress.
- [M40. The overseer per decision](M40-the-overseer-per-decision.md): in progress.
- [M41. Limits and trust settings from the web UI](M41-limits-and-trust-settings-from-the-web-ui.md): done 2026-10-16.
- [M42. Other people's PRs, reviewed on request](M42-other-peoples-prs-reviewed.md): done 2026-10-16.
- [M43. Publishing a review on someone else's PR](M43-publishing-a-review.md): done 2026-10-22.
- [M44. Plans before implementing](M44-plans-before-implementing.md): done 2026-10-17.
- [M45. canopy's own worktree pools, replacing treehouse in stages](M45-canopys-own-worktree-pools.md): in progress.
- [M46. Workers file follow-up tickets](M46-workers-file-follow-up-tickets.md): done 2026-10-29.
- [M47. Garbage collection](M47-garbage-collection.md): done 2026-10-30.
- [M48. The overseer's tools over MCP](M48-the-overseers-tools-over-mcp.md): done 2026-10-31.
- [M49. Config per workspace](M49-config-per-workspace.md): done 2026-10-17.
- [M50. Agent memory, opt-in](M50-agent-memory-opt-in.md): done 2026-10-30.
- [M51. The loop, detached](M51-the-loop-detached.md): done 2026-10-17.
- [M52. Memory's verbs from the web UI](M52-memorys-verbs-from-the-web-ui.md): done 2026-10-20.
- [M53. Review replies the operator sends](M53-review-replies-the-operator-sends.md): done 2026-10-29.
- [M54. Plans before feedback runs](M54-plans-before-feedback-runs.md): in progress.
- [M55. Trivial work skips its plan](M55-trivial-work-skips-its-plan.md): done 2026-10-30.
- [M56. Fixing CI is part of resume](M56-fixing-ci-is-part-of-resume.md): done 2026-10-29.
- [M57. A clock for running agents](M57-a-clock-for-running-agents.md): done 2026-10-30.
- [M58. canopy chooses each agent's model](M58-canopy-chooses-the-workers-model.md): done 2026-10-29.
- [M59. Lessons edited, with their history](M59-lessons-edited-with-their-history.md): done 2026-10-29.
- [M60. Personas](M60-personas.md): done 2026-10-29.
- [M61. One-off tasks](M61-one-off-tasks.md): in progress.
- [M62. Artifacts, and comments on them back to the ticket](M62-artifacts.md): in progress.
- [M63. Attachments on tickets and tasks](M63-attachments.md): in progress.
- [M64. Slack replies](M64-slack-replies.md): deferred 2026-11-01.
- [M65. Running agents say where they stand](M65-running-agents-say-where-they-stand.md): in progress.
- [M66. The checklist, asked before the push](M66-the-checklist.md): in progress.

## Deferred, with the trigger that would unblock each

- Spend-paced loop (left out of M13): when, with M39 built, overseer spend per day still runs past what the operator
  will pay (`canopy spend` shows it). M13's cost recording is in, and a monthly budget the spend page tracks and a
  sink hears of (`spend.monthly_budget_usd`); a pacing rule that acts on it is what remains.
- PR-scoped work (M14): when the operator keeps fixing CI or answering review on their own hand-written PRs by hand,
  often enough to want canopy to do it.
- Webhooks: when tick latency is measured as a real cost.
- Bot identity: when audit requirements demand it, or when a repository wants to trust review verdicts.
- Second runtime (Copilot CLI, Claude Code): when a coworker asks. More than a config change: canopy's definitions,
  their permissions, and the D044 guard are written for OpenCode, so a runtime needs its own (REQUIREMENTS N4), all of
  it in `canopy.runtime` (D009).
- Watching a PR (M42's watch mode): when the operator asks canopy to review the same coworker's PR again after each
  push often enough to want it to follow the PR until it merges. DESIGN §21 (Review requests) says what it needs.
- Workers against OpenCode's server (M15's last bullets): when the operator wants to prompt a running worker rather than
  read its transcript and answer it after. The listener follows TRUST_MODEL T8, and OpenCode's server authentication on
  the pinned version is checked first.
- Slack replies (M64): when the operator's Slack app can be granted read access to its channel's threads, so
  Accept's live check can run. The sink's notifications (M10) do not need it.
