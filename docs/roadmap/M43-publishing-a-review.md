# M43. Publishing a review on someone else's PR

REQUIREMENTS N1, DESIGN §21, D114. Needs M32 and M53, and M42 for the PRs it applies to most. Sketch only; the design
comes first. Asked for by the operator (2026-10-15): on a review of a PR the loop does not own, where M32's `send to a
worker` does not apply, iterate on the review in canopy, by hand or with an agent, and then send it to GitHub as a
review on the PR. This is D114's revisit trigger, "the operator wants the web UI's shadow review published": D114
changes, with the operator's approval, from "posts nothing" to "posts nothing the operator has not approved, word for
word".

- Only for reviews of PRs that are not the loop's own (`review.query` matches, M42's requests): the loop's own PRs
  keep M32's send to a worker, and their reviews stay in the journal.
- A draft is a journal fact, versioned, made from a review run: its summary and findings, each finding's text the
  operator may edit, drop (M32's dismissal), or add to. These are M53's drafts, with a review run as their source, on
  M53's diff with cards on its lines. Iterating with an agent is a run of its own that reads the PR
  and the draft, writes nothing anywhere, and reports a new version as a result line, as the reviewer does; the
  operator's notes to it are a reply on the draft. The draft's text is untrusted until the operator approves a
  version, since the reviewer and the reviser wrote it from the PR's text (T1).
- Publishing is the operator's act on one version, from the review's page or the CLI, refused `inside_run` as `send`
  is, and at most once per version. What reaches GitHub is that version verbatim: findings anchored on the diff as
  inline comments at their `path:line`, the rest in the review's body. A comment review only: canopy never approves or
  requests changes (TRUST_MODEL §6). The journal records what was posted, when, and where.
- canopy imports no GitHub client: the post goes through M53's `canopy-post-github`, a separate program canopy ships,
  which posts the approved text verbatim and returns what it made, so no agent writes the review. Open: whether canopy
  should only create a pending review for the operator to submit on GitHub themselves, so that submitting stays a
  human's click.
- TRUST_MODEL §6 (a comment review of approved text only, as M53 changes it), T1, T5 (what a posted review says it is,
  with no bot identity, so it speaks in the operator's name), T6, and T8 (publishing from the web channel), and D114.
- Open: whether a published review is followed on the next commit (M32's open question of a finding's identity across
  commits); whether the loop's own PRs ever get it, for a coworker's benefit; a bound on what one review may post.

Accept: written with the design, before work starts.

Status: not started.
