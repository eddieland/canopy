# M43. Publishing a review on someone else's PR

REQUIREMENTS R17, DESIGN §21, §29, and §34, TRUST_MODEL T1, T3, T5, T6, T8, and §6, D114. Needs M32 and M53, and M42
for the PRs it applies to most. Asked for by the operator (2026-10-15): on a review of a PR the loop does not own,
where M32's `send to a worker` does not apply, iterate on the review in canopy, by hand or with an agent, and then send
it to GitHub as a review on the PR. This is D114's revisit trigger, "the operator wants the web UI's shadow review
published": D114 changes, with the operator's approval, from "posts nothing" to "posts nothing the operator has not
approved, word for word". The design is DESIGN §34.

- Only for reviews of PRs that are not the loop's own (`review.query` matches, M42's requests): the loop's own PRs
  keep M32's send to a worker, and their reviews stay in the journal. A review that names a ticket, or of a PR a
  ticket's unit holds, has no draft, checked in code.
- A draft is a journal fact, versioned, made from a review run: its summary and findings, each finding's text the
  operator may edit, drop (M32's dismissal), or add to. These are M53's drafts, with a review run as their source, on
  M53's diff with cards on its lines. A version is exactly what would post, a body and comments on lines of the kept
  diff; a finding off those lines goes in the body as the version is made, so canopy composes nothing when it
  publishes. Iterating with an agent is a review run of its own at the same commit, started by a tick when the
  operator's note is newer than the newest version, that reads the PR and the draft, writes nothing anywhere, and
  reports a new version as a result line, as the reviewer does. The draft's text is untrusted until the operator
  publishes a version, since the reviewer and the reviser wrote it from the PR's text (T1).
- Publishing is the operator's act on one version, from the review's page or the CLI, refused `inside_run` as `send`
  is, and at most once: a draft publishes one version, and a later commit's review is a new draft. What reaches GitHub
  is that version verbatim, unmarked, on the commit the review read: comments as inline comments at their `path:line`,
  the rest in the review's body. A comment review only: canopy never approves or requests changes (TRUST_MODEL §6).
  The journal records what was posted, when, and where. A post of unknown outcome waits for a whole read, and the
  operator may stage the version as a pending review instead, as M53's drafts are.
- canopy imports no GitHub client: the post goes through M53's `canopy-post-github`, which gains a review on a named
  commit whose comments start new threads, posts the approved text verbatim, and returns what it made, so no agent
  writes the review.
- TRUST_MODEL, in the PR that builds it, which the operator approves by merging: §6, T1, T3, T5 (a published review
  speaks in the operator's name, unmarked, with no bot identity), T6, and T8 (publishing from the web channel), and
  D114, as DESIGN §34 lists them.
- Tests with the fakes: a `done` review of a requested PR makes a draft whose first version is its findings, one off
  the diff in the body; an own review makes none; an edit, a drop, and a dismissal each make a new version; a note
  starts a revision on the next tick, under the review guards and its own limit; publishing posts the version verbatim
  as one `COMMENT` review on the reviewed commit, with inline comments, and records the ids; a second publish, a stale
  version, and `inside_run` refused; a post of unknown outcome posts nothing more until a read settles it; a stage
  leaves a pending review, settled by a read; Playwright for editing and publishing from the review's page.

Accept: written with the design, before work starts. Live, once built: on a coworker's PR the operator asked canopy to
review, the review ends `done`; the operator edits one comment, dismisses one finding, adds one comment on a line, and
asks for a revision with a note, whose version follows the note; they publish it, and GitHub shows exactly that
version under their name, as one comment review at the reviewed commit, its comments on their lines, approving
nothing; publishing it again is refused; on a second PR, a staged review waits on GitHub until the operator submits it
there, and the next read records it as published.

Status: in progress. Designed 2026-10-20 (DESIGN §34, Publishing a review, beside §21's reviews and §29's drafts).
Built in part 2026-10-20: a `done` review of a PR the loop does not own makes a draft whose first version is its summary
and findings, one off the kept diff in the body, and an own review makes none; `canopy review draft`, `edit` (body,
comment, drop, add on a line of the diff), and dismissals each make a new version; `canopy review publish RUN HASH`
stages the version as a pending review by default and with `--submit` posts it verbatim as one `COMMENT` review on the
reviewed commit through `canopy-post-github`, which gains a review on a named commit whose comments start threads;
refused `inside_run`, stale, a second time, past its kept diff, or on a PR a ticket holds; an unknown outcome and a
stage wait for a whole read. D114 and TRUST_MODEL §6, T1, T5, and T6 changed with it. The operator's choices taken:
staging is the default and only `--submit` submits; a version carries at most 30 comments, as one run's drafts, and
more are refused; a published review is not followed onto the next commit; the loop's own PRs publish none; a draft is
publishable while its diff is kept. Built 2026-10-21: the review's page shows the draft as it would post, each
comment on its line of the diff, and edits it (body, comment, drop, add on a line) and publishes or stages it through
the same functions as the CLI, from the web channel behind T8's guards, with Playwright; TRUST_MODEL T8 changed with
it. Left: revisions on the operator's note (a review run at the same commit, its limit per draft, TRUST_MODEL T3), and
the live Accept.
