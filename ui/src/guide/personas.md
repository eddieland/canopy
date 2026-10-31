# Personas

A persona is the voice your planners, reviewers, and workers write in. This page covers what one can and can't change,
the ones canopy ships, how to choose one, and how to write your own.

## What a persona is

A persona is a short Markdown file of voice and emphasis: how an agent words its plan, its PR, its commits, its
findings, and its replies, and what it weighs most while it works. It's how you get a reviewer that presses harder on
failure paths, or a worker that keeps every diff as small as the ticket allows, without copying a prompt to get it.

It reaches three agents, one persona per run: the **worker** (every implement and resume, public and private), the
**planner**, and the **reviewer**, whose persona a revision of its draft keeps, so the rewording sounds like the review
it rewords. The overseer, chores, feedback plans, and tasks get none: the overseer's prompt is policy, and a chore
writes verdicts, not prose for you to read.

## What it can't do

The prompt comes first, and says so: where a persona conflicts with anything the prompt requires, the prompt wins. A
persona changes how an agent writes and where it looks hardest. It never changes the authorization check, the result
an agent must report, commit attribution, the tools an agent may use, or what makes a review's verdict, and every
guard holds whatever it says. A persona can make your reviewer blunt or your worker chatty. It can't give either a
tool its definition doesn't allow, and no amount of persuasive prose gets a PR merged.

Nor does a persona fall back. If its file is gone, or one canopy won't put in a prompt, by the time a run starts, that
run is refused with an item on your [attention list](attention), spending no attempt and holding no slot. It never runs
in `canopy` instead, since a run in a voice nobody chose would read as the chosen one's.

## The ones canopy ships

- `canopy`: canopy's own voice, and every agent's unless you choose another. Plans as long as the work needs, reviews
  that read the change as an adversary, and PR text left alone unless it's wrong.
- `skeptic`: plans and reviews by naming the input that would break each claim, and accepts only the claims that
  held. A good reviewer, and a good planner for the ticket that scares you.
- `minimalist`: the lazy senior developer. The smallest diff the ticket allows, what already exists before new code,
  and few words. Written for workers and planners.
- `explainer`: writes for a coworker new to the code, so PRs, commits, replies, and plans say why as well as what.
  Best on a worker whose PRs someone else will review.
- `eddie`: works like Eddie: asks whether the code needs to exist at all, keeps the diff and the words small, and
  blocks only on what would break. Reviews in short comments labeled in Conventional Comments.

A persona speaks to each job in a paragraph of its own (`When you plan,`, `When you review,`), so one file can serve
more than one agent; most of the above do. `canopy personas` lists them, with yours.

## Choosing one

A run's persona is, first to last: the one you chose for that agent's next run alone, else the ticket's override for
that agent, else that agent's in `[personas]`, else `canopy`. It's fixed when the run starts, so changing it never
reaches a run already going.

- **For every ticket**, in `[personas]` in your config. `worker`, `planner`, and `reviewer` each name one;
  `reviewers` names several, and each commit of the loop's own PRs then gets one review in each, every one counting
  against the review limit ([When canopy reviews](pull-requests#when-canopy-reviews)).
- **For one ticket**, on its page, or with `canopy persona KEY NAME --agent AGENT`, which holds until you clear it.
  [Choosing a persona](tickets#choosing-a-persona) has the panel.
- **For one run** of a worker or a planner, `canopy persona KEY NAME --next`, or `--persona` on `canopy start KEY`
  or `canopy plan KEY`. The runs after it go back to the ticket's or your config's.
- **For a review you ask for**, the **Persona** menu on the request, or `--persona` on `canopy start URL --review`,
  given once per persona for a review in each ([Asking for a review](pull-requests#asking-for-a-review)). The ones
  you prefer go in [Settings](settings#reviews), and each request starts from them.

```toml
[personas]
worker = "minimalist"
planner = "skeptic"
reviewers = ["canopy", "skeptic"]
```

Only you choose. `[personas]` and `paths.personas` are keys of your own files, never the workspace's, and choosing one
is refused inside an agent's run. The overseer, a ticket's text, and its labels choose none: otherwise a ticket could
ask for a reviewer that likes it. Setting a persona with no file is refused as `unknown_persona` there and then, rather
than when a run starts.

## Writing your own

Point `paths.personas` at a directory of yours, given as an absolute path or one starting with `~`, and put a file in
it per persona, `NAME.md`. A name is lowercase letters and digits, joined by single hyphens, 40 characters at most; a
file named otherwise is never read. A new name adds a persona; a name canopy ships replaces canopy's everywhere, and
`canopy personas` says it stands `in place of canopy's`. That includes `canopy` itself, the voice every agent gets by
default, so shadow that one on purpose.

```markdown
---
description: Plans and PRs for the on-call engineer who reads them at 3am.
---

When you plan, put the rollback first. ...

When you open a PR, ...
```

The front matter is optional, and holds `description` alone, for the menus: no agent reads it.
[Choosing a persona](tickets#choosing-a-persona) has its rules. Everything after it is what the prompt carries.

canopy reads the file afresh as each run starts, and refuses it as `bad_persona` when it is:

- over 4096 bytes, front matter included, since it goes in every prompt it reaches and shouldn't crowd out the task;
- not UTF-8, or not readable;
- holding a character that hides text from you but not from a model, such as a zero-width space or a bidirectional
  override: the ones a [memory](memory#how-it-protects-you) may not hold, though a newline and a tab are fine;
- opening a front matter it never closes, or one with a key other than `description`.

Each run records its persona's name and a digest of the text, so editing a file splits its runs into before and after.

If you've overridden a prompt and your copy has no `{{PERSONA}}`, runs in `canopy` keep working, since your copy
already holds the voice you wanted; a run in any other persona is refused as `bad_prompt` rather than run without it.

## The commands

`canopy personas` lists every persona a run could get: canopy's, yours, which of yours stand in place of canopy's, the
agents each is the default for, and why canopy would refuse one. With the config above and two files of your own:

```text
Personas (6):
  canopy  canopy's; the default for reviewer
  eddie  canopy's
  explainer  canopy's
  minimalist  canopy's; the default for worker
  on-call  yours, /home/you/.config/canopy/personas/on-call.md
  skeptic  yours, /home/you/.config/canopy/personas/skeptic.md, in place of canopy's; the default for planner, reviewer
```

It exits 1 when any agent's persona in `[personas]` has no file or would be refused, which makes it a cheap check
after you edit one.

`canopy persona KEY`, with no name, prints the persona each of the ticket's agents writes in next and where that comes
from. `canopy persona URL NAME` sets the persona of a review you've asked for of that PR.

## Where it shows

- **A ticket's page**: each agent's next persona and where it comes from, under **Work**
  ([Choosing a persona](tickets#choosing-a-persona)).
- **A run's page**: **persona**, with the start of its text's digest ([A run's page](runs#a-runs-page)).
- **A review's page and the reviews list**: the persona it wrote in, as `as skeptic` in the list
  ([A review's page](pull-requests#a-reviews-page)).
- **A plan's page**: the planner's persona, with **Show instructions** for the exact text it read, kept in the journal
  after you edit the file ([Reading a plan](plans#reading-a-plan)).
- **`canopy review noise`**: findings counted by persona, the honest answer to which reviewer earns its keep
  ([Measure the noise](code-review#measure-the-noise)).
