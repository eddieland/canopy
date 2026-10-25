# canopy-review-bench

Score a code review bot on PRs whose bugs you already know, without the bot knowing it is being tested.

`canopy review eval` scores canopy's own reviewer. This scores any reviewer that comments on GitHub PRs: a vendor's
bot, an in-house one, or canopy's, so their numbers can sit side by side. It opens each case's PR in a private copy of
your repository, one at a time, waits for the bot's review, reads its comments, closes the PR, deletes its branches,
and scores what the bot said against where the bug is.

It answers two questions. Does the bot find bugs, and how much noise does it make finding them? And do your custom
instructions help? The second is usually what you want to know, and once the first is set up it costs one more run.

## Install

It is a workspace member canopy does not depend on, so install it on its own, from a clone of canopy:

```sh
uv tool install ./packages/canopy-review-bench
gh auth login          # on the mirror's host; the bench never holds a token
```

It needs git and gh 2.48 or later on `PATH`.

## The mirror

Make a private repository to open the PRs in, say `acme/api-review-bench`, with one commit on its default branch, a
README, and nothing of your code. Install the bot on it as you have on the real repository. Then:

- **Nobody is notified.** The PRs are opened and closed in a repository only you watch, and nothing deploys from it.
- **Nothing of the future is there.** The bench pushes only what each case needs, and deletes it once the case is
  read, so no case's PR can find its own fix on another branch. Keep the default branch as you made it.
- **The instructions travel.** If the bot reads instructions from files in the repository, put them in a directory
  laid out as the repository is and pass it as `--overlay`: its files are written into every case's base and head, so
  the bot reads them and no PR's diff shows them.

## Cases

A bench file is TOML: a `[bench]` table and a `[[cases]]` table per case.

```toml
[bench]
source = "../api"                    # a clone holding every commit the cases name, relative to this file
mirror = "acme/api-review-bench"
reviewers = ["acme-review[bot]"]     # whose comments count
# host = "github.example.com"        # for GitHub Enterprise
# tolerance = 3                      # lines from a bug a comment may be and still find it
# wait_minutes = 30                  # how long a PR waits for a review before it scores as silent
# quiet_minutes = 3                  # how long the bot must post nothing new before its review is done
# poll_seconds = 30

[[cases]]
name = "zero-attempts"
kind = "bug"
title = "Simplify fetch"             # the PR's title and its commit's message: write it as your team would
body = "Less code in the retry loop."
undo_fix = { fix = "<the fixing commit, 40 hex characters>", paths = ["src/"] }

[[cases]]
name = "retry-delay"
kind = "bug"
split = "holdout"
title = "Wait between attempts"
replay = { base = "<where the PR left main>", head = "<its head as it merged>" }
lines = ["src/retry.py:42", "src/retry.py:57-61"]

[[cases]]
name = "batch-refactor"
kind = "clean"
title = "Batch the writes in the exporter"
replay = { base = "<...>", head = "<...>" }
```

There are two ways to get a case's PR:

- **`undo_fix`**: a commit that fixed a bug, reversed on top of itself. The bug is one that really shipped and got
  past people once, and you get dozens from `git log --grep fix`. The base has no history, since any history would
  hold the fix and its message. Where the bug is comes from the diff unless you name it: the lines the PR adds, on the
  head's side, and the lines it deletes, on the base's, so a comment beside a deleted guard finds it. A fix of several
  hunks credits a comment on any of them; name `lines` for a stricter score. Set `paths` to leave the fix's tests
  out, or the PR deletes the test that names the bug.
- **`replay`**: a PR as it was, from its base to its head, with the history up to its base. `base` is where it left
  the branch it merged into. For a PR that has merged, that is `git merge-base HEAD_SHA LANDED^`, where `LANDED` is
  its merge or squash commit. Name the bug's lines as `path:line` or `path:first-last`, numbered as the file is at the
  head, in `lines`, and lines the PR deletes, numbered as the base has them, in `base_lines`.

The head is always one commit on the base, whose message is the title, so no commit message of the original gives
anything away. Branch names look like a team's (`main-3f9c2e`, `simplify-fetch-3f9c2e`), not a test's.

A **clean** case is a PR that has run for months without a fix, and every inline comment on it is a false alarm. Pick
some that look risky and are right, a large refactor or tricky concurrency, as well as plain ones: a reviewer that
flags everything scores well on bugs alone.

## Scoring

A bug is found when one of the bot's inline comments that opens a thread is within `tolerance` lines of where the bug
is, on the same side of the diff. Each inline comment on a clean case is a false alarm. Comments on no lines, a
review's body or the conversation, are counted and not scored: a summary cannot be placed. A PR that could not be
built, pushed, or opened is not scored. One the bot said nothing on in `wait_minutes` scores as no comments and is
counted apart, because a bot that never ran looks the same.

Every rate comes with its 95% interval. With 30 bug cases, a reviewer that finds half of them is somewhere between
about 33% and 67%, so two setups 10 points apart on 30 cases cannot be told apart. Plan for 50 to 100 bug cases, or
trust only large differences.

Line distance says a comment is near the bug, not that it names it. Read the hits now and then: some are near the line
and wrong about it.

## Commands

```sh
canopy-review-bench check bench.toml                       # build each case's commits, show its diff and bug, open nothing
canopy-review-bench run bench.toml --split tune --overlay instructions/ --label "bot 2.3, rules v4"
canopy-review-bench run bench.toml --split tune --label "bot 2.3, no rules"
canopy-review-bench run bench.toml --case zero-attempts --repeat 3
canopy-review-bench score results/20261025T130000Z --tolerance 5
```

`run` prints the score as Markdown and saves the run under `results/` beside the bench file: `run.json`, with the
label and the overlay's digest, and `reviews.jsonl`, one line per review as it ends, with the bot's comments. A run
you stop halfway keeps the reviews it finished, and `score` reads them.

## Staging it

1. **Pilot, about 10 cases.** Five bugs, five clean, one PR at a time. This tests the bench, not the bot. Does the bot
   review PRs in the mirror? Do its comments come back with a path and a line? Did a case give its answer away? Read
   `check`'s output for each case before you run it: a diff that deletes a test, or is far larger than the bug,
   measures something else.
2. **Build the corpus.** Group the bugs by kind, such as concurrency, auth, error handling, migrations, and boundaries.
   Write at least one case for each claim your instructions make ("flags unguarded migrations"): an instruction with
   no case is a hope. Keep about as many clean cases as bugs.
3. **Hold some out.** Mark about a third `split = "holdout"` and tune on `--split tune` alone. Run the holdout only to
   check a change you have settled on, or you are tuning the instructions to the test.
4. **Compare.** Run the same cases with `--overlay` and without it. That says whether the instructions earn their
   upkeep. Use `--repeat 3`: an LLM reviewer does not answer the same twice, so a case's score is how often it finds
   the bug, not whether it did once.
5. **Get a baseline.** Install another reviewer on the mirror and run the same cases with its login in `reviewers`.
   For canopy's own reviewer, `canopy review eval` scores the replay cases' original PRs, as cases in canopy's config.
6. **Keep it going.** Every bug the bot misses in real use becomes a case. Run the bench again when the instructions
   change, or when the vendor changes its model.

Two checks before you scale up: how the vendor bills per PR, since a run of 100 cases three times is 300 reviews; and
that pointing the bot at a copy of your code is within your agreement with the vendor, which it usually is, since it
already reads the real repository.
