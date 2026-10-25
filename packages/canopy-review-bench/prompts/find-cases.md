# Find review bench cases

You are cataloguing candidate cases for a code review benchmark, in the repository checked out in your working
directory. A later step turns your catalogue into a bench file (`packages/canopy-review-bench/README.md` in canopy
describes it); a person reads every candidate first. Your job is to find candidates, prove each one from the history,
and say plainly how sure you are. A short list of solid candidates beats a long list of guesses.

Fill these in before you start, or ask the person who gave you this prompt:

- Repository: `OWNER/NAME` on `HOST` (default `github.com`). Main branch: `main`.
- Window: commits merged in the last `18` months.
- Aim for: `40` bug candidates and `40` clean ones.
- Areas that matter most: `<paths or systems the team least wants a bug in, or "none">`.

## Rules

- **Read only.** Do not push, open or edit PRs or issues, comment, label, or approve anything. Use `git` and `gh`
  for reading alone (`gh pr view`, `gh pr list`, `gh api` with GET). The catalogue is the only file you write.
- **Never invent a commit.** Every sha you write is one you ran `git cat-file -e SHA^{commit}` on, and every line
  number is one you read in `git show SHA:PATH`. If you cannot verify something, say so in the candidate's notes
  rather than filling it in.
- **Keep the code here.** Send the repository's code and history nowhere outside this session and its own host.

## How this team fixes bugs

Bugs here are rarely reverted. They are fixed forward: an urgent PR soon after the one that broke things, or a quick
rework of what just merged. So a bug is a pair, a **fix** and the **introducing PR** whose lines it changed.

Learn the team's conventions first, from a sample of about 50 recent merged PRs, before you mine anything:

- How PRs merge (merge commits, squash, or rebase), and how a commit names its PR (`Merge pull request #N`, `(#N)`).
- What marks an urgent fix: branch prefixes (`hotfix/`, `fix/`), labels (`bug`, `incident`, `P0`, `sev1`), title
  words (fix, hotfix, regression, broke, revert, rollback, follow-up, oops, urgent, incident numbers), fields in the
  PR template (an incident or ticket link), cherry-picks onto release branches.
- What looks like a fix but is not one here: planned follow-ups in a stack ("part 2 of 3"), feature-flag flips,
  dependency bumps, flaky-test fixes, formatting, config or data changes.

Write what you learned at the top of the catalogue. It decides how far to trust the signals below.

## Finding bug candidates

1. **List fix-shaped commits** on the main branch in the window, by the signals you learned: a fix title or label, a
   hotfix branch, an incident link, a cherry-pick, a small diff merged fast (opened to merged in hours), merged off
   hours. Score each by how many signals it has. Expect most to be noise.
2. **Trace each fix to its introducing PR.** For fix commit `F` with first parent `P`, take each hunk of
   `git diff -U0 P F`, ignoring tests, docs, and lockfiles, and blame the lines it changes or deletes as they were in
   `P`: `git blame -w -M -C --line-porcelain -L FIRST,LAST P -- PATH`. A hunk that only adds lines (a missing
   guard, a missing case) has no line to blame: blame two lines either side of where it adds, and mark the trace weak.
   Map each blamed commit to its PR through the commit message or `gh api repos/OWNER/NAME/commits/SHA/pulls`.
3. **Keep the strong pairs.** A pair is strong when most of the fix's blamed lines come from one PR, merged a short
   time before the fix (within 14 days is strong, within 60 is worth a look), and the fix changes behavior that PR
   added. Drop a pair when the blame lands on a mass reformat, a file move, or a vendored file.
4. **Read both PRs** and decide whether the fix fixes a defect: wrong behavior, a missed case, a security hole, a
   broken contract. Not a change of mind, a new requirement, or a tweak to taste. Rework counts when the second PR
   corrects what the first got wrong, not when it adds what the first left for later. Quote the line in the fix PR's
   title, description, linked ticket, or diff that shows it was a defect.
5. **Judge whether a reviewer could have caught it** from the introducing PR's diff and the repository at its
   commit: `yes` (the diff shows it), `partly` (it needs reading code the diff calls), or `no` (it needs production
   data, config, or traffic the repository does not hold). Keep the `no` ones, marked: they measure something else.

Each strong pair can give two cases about the same bug: an `undo_fix` of the fix, and a `replay` of the introducing
PR. Give both the same bug id; the person puts them in the same split, or the holdout leaks.

For a `replay`, find the PR's commits:

- `head`: the PR's last head, `gh pr view N --json headRefOid`. Fetch it with `git fetch origin pull/N/head` if it is
  not local.
- `base`: where it left the main branch, `git merge-base HEAD_SHA LANDED^`, where `LANDED` is the commit the PR merged
  as (its merge commit or squash commit; for a rebase merge, the first of its rebased commits).
- Check `git diff --stat BASE HEAD_SHA` lists the PR's files and nothing else. If it does not, say so and skip the
  replay.
- `lines`: where the bug is, numbered as the file is at `HEAD_SHA`. Find the blamed lines there by their text with
  `git show HEAD_SHA:PATH | grep -n`, and check each number.

For an `undo_fix`: `fix` is the fix commit, and `paths` the directories of its non-test changes, so the PR does not
delete the test that names the bug. If the fix's diff mixes the fix with unrelated changes, say so: the undone diff
would carry them too.

## Finding clean candidates

A clean case is a PR known to be sound. Take PRs merged at least 90 days ago, of at least 50 changed lines outside
tests, preferring the areas that matter most and changes that look risky: concurrency, auth, money, migrations, large
refactors. Keep one only when no fix-shaped commit since has changed its lines: blame its changed lines at the main
branch's tip, and check that every later change to them is not a fix. Give its `base` and `head` as for a replay.

## Neutral titles and descriptions

The bench opens each case as a new PR, with a title and description you propose. Write them as the original author
might have, from the original PR, with nothing that hints at the bug: no "fix", "careful", "might break", ticket or
incident numbers, or names of the people involved. For an `undo_fix`, describe what the reversed diff does as if it
were a change someone meant ("Simplify the retry loop"). If the original description names the bug, write a new one.

## The catalogue

Write `review-bench-candidates.md` in the working directory, and nothing else:

1. **Conventions**: what you learned about how this team merges and fixes, and which signals you trusted.
2. **Summary**: how many fix-shaped commits you looked at, how many pairs you traced, and how many candidates you
   kept, by kind, by `yes`/`partly`/`no`, and by confidence.
3. **A table**, one row per candidate: id, kind (`bug` or `clean`), source (`undo_fix` or `replay`), bug id, the fix
   PR and the introducing PR, days between them, category (such as concurrency, error handling, boundary, auth, data
   handling, API contract), size in changed lines, could a reviewer catch it, and confidence (`high`, `medium`,
   `low`).
4. **One section per candidate**: the evidence (the quoted line that shows a defect, the blame that ties it to the
   PR, what the bug does), anything that might give the answer away, and the case as TOML, for a bench file:

```toml
# bug id B07 · confidence high · reviewer could catch it: yes · fix #4821, introduced in #4790, 3 days apart
[[cases]]
name = "b07-retry-zero"
kind = "bug"
title = "Wait between retries in the fetcher"
body = "Adds a delay between attempts so a slow upstream is not hammered."
replay = { base = "<40 hex>", head = "<40 hex>" }
lines = ["src/fetch/retry.py:42-44"]
```

Names are lowercase letters, digits, and dashes, at most 40 characters. A clean case has `kind = "clean"` and no
`lines`. Put anything that is not a key of the case in TOML comments: a bench file refuses keys it does not know.

When you have fewer strong candidates than asked for, stop and say so. Do not lower the bar to reach the number.
