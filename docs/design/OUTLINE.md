# A code outline for agents

Part of the canopy design, normative like all of it: the outline of a repository's code a run's prompt starts with, so
an agent need not search for where its work is. Sections are numbered across the whole design; the
[README](README.md) has the map. Previous: [What a run changed](RUN_CHANGES.md).

## 46. A code outline for agents

An agent starts a run knowing nothing of its repository but its working directory. The workspace map (§18) says what
each repository owns; nothing says what is inside one, and an agent skips a lookup tool it must think to call (§28).
So the harness renders, into the prompt, an outline of the code the run's work is about. It is called an outline
throughout, never a map, which is the workspace's.

Off by default: with the private `index.outline` at `off`, every prompt is the bytes it is without one. At `tree`, a
dispatch (§8 step 3) gives an `implement`'s and a `resume`'s worker a directory tree of each repository the run works
in, a joint run's (§18) one per repository. The planner, the reviewer, and a task's agent get none yet.

### The tree

The tree is what git holds, read from its objects in the slot the run leased and never from a working tree, which a
run writes (§24): an `implement`'s is its base branch's, and a `resume`'s its own branch's, each as the lease last
fetched it, and the outline names the ref. Directories the work is about are opened to their files; the rest are a
name and a count of the files under them, outermost first, until the private `index.outline_chars` is reached, a bound
a joint run's repositories share. The outline says how many files it does not name. Files the private `index.exclude`
covers, compared as `high_impact_paths` are (§21), are left out and not counted.

What the work is about is found by words and used only to rank, rendered nowhere: for an `implement`, the words of the
ticket's title and body as the tracker connector last observed it (§30), split as identifiers are and matched against
the words of each path's components; for a `resume`, the paths its branch already changed, and the ticket's words
while it has changed none. A ticket with no observation, or whose words name no path, gets the tree opened by size
alone.

The outline is rendered once, at dispatch, so a run's prompt stays the one record the journal can show. It is best
effort: a tree git cannot list, or does not list in time, is left out and logged, and the run starts without it.

### Data, not instructions

Paths are the repository's text, which any contributor writes (TRUST_MODEL T1). The outline is framed as data, every
line of a tree quoted as a ticket note's is (§28); a path is bounded, and one holding a character that can hide text is
dropped and counted, never rendered. The ticket's text chooses what is opened and appears nowhere in the outline. A
run's outline is of its own repositories' trees alone, never a path an agent or a ticket names (T6).

### Rejected

- A third-party index server: per slot, blind through a reviewer's links and a joint run's desk, and a reach over
  every project indexed on the machine.
- Indexing the working tree: it reads what a run writes, and a checkout resets what it would be keyed by.
- An outline rebuilt as the run goes: a run's prompt is one record (§8).
- Symbols before the tree is measured: a parser of untrusted code is the expensive half, and the tree may be enough.

### Open

- The planner's, the reviewer's, and a task's outline, a plan's from its ticket's words, a review's from the PR's
  diff and of the PR's own tree, and a task's from its own text.
- Definitions inside the tree, from a symbol index, and lookups over it, each only if the measurement before it says
  the tree is not enough (`docs/roadmap/`, M70).
