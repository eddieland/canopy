# M59. Lessons edited, with their history

DESIGN §22 and §28, TRUST_MODEL T1 and T8. Needs M50 and M52. Asked for by the operator (2026-10-19): version memories
and lessons, so an edit keeps a history. Today a lesson's words change only by promoting another proposal over it, or
by forgetting it, and the journal links each version to the one before it (`supersedes`) without any surface reading
that chain.

- `canopy memory edit ID [--text TEXT] [--repo REPO | --every-repo]`, in `canopy.core.memory_manage`: a new version of a
  lesson in force, the old one superseded and kept with its words, never edited in place. Held to the bounds a promote
  is; refused `inside_run`, `off`, `unknown` for any id but a lesson in force, `unknown_repo`, `bad_text`, and
  `unchanged`. The new version is due for review 90 days on, with a run's report that the lesson is wrong cleared. Notes
  stay worker-written: the operator edits lessons only.
- `canopy memory history ID`: every version of a lesson or a note, newest first, each with how it was made. A version
  made by an edit names the lesson it was edited from, and every version still names the proposal or note the lesson
  was first promoted from. `forget` of a lesson names the versions that keep their words.
- The web UI: `POST /api/memory/{id}/edit` and `GET /api/memory/{id}/history`, through the same functions; Edit under
  each lesson on the memory page, its form the promote form's fields; and under any row with more than one version, the
  versions, read only once opened, with Forget on each out of force that keeps its text where the row has verbs.
- TRUST_MODEL T1 and T8 name `edit` beside `promote`; DESIGN §22 and §28, `ui/DESIGN.md`, the guide, and the operator's
  skill follow.
- Tests with the fakes: edit through the CLI and the API, each refusal, and in a run; a lesson's and a note's history; a
  promote over an edited lesson as its next version; a forgotten lesson ending its history; Vitest for the form and the
  versions; Playwright for editing a lesson and forgetting its old version from the memory page.

Accept: the tests above pass. Live: with proposals at `use`, the operator edits a lesson's words from the memory page;
the next run's prompt carries the new words under the new id, `canopy memory history` lists both versions, and no run's
`canopy memory search` finds the old words.

Status: in progress. Built 2026-10-19, its tests passing. The live check is the operator's.
