/**
 * What a worker's or a task's run changed (DESIGN §45): each repository's range, as its page's Diff panel and its
 * ticket's runs list name it, and what the panel says of a diff it cannot show.
 */

import type { RunChange, RunRange } from '@/api/types'
import { goneText } from '@/lib/retention'
import { shortSha } from '@/lib/reviews'

/** Which of a run's two kept diffs its Diff panel shows: the run's own change, or the branch against its base. */
export type ChangeView = 'run' | 'branch'

/**
 * The kinds of worker run that record what they changed, as canopy's `runs.changes.RECORDED` names them: those that
 * work on the ticket's branch. A plan, or a feedback plan, pushes none. A task's run always records.
 */
const RECORDING_KINDS: ReadonlySet<string> = new Set(['implement', 'fix-ci', 'resume'])

/** Whether a worker run of `kind` records what it changed as it ends, so a page says so when it recorded nothing. */
export function recordsChanges(kind: string): boolean {
    return RECORDING_KINDS.has(kind)
}

/**
 * A range's commits, short, as `git log` names a range: from the one the run started from to the one its diff is of,
 * the commit it left unpushed in its slot when it left one, else the one it left on origin. Empty when canopy read
 * nothing of the slot, as for a run that crashed.
 */
export function rangeSpan(range: RunRange): string {
    const to = range.unpushed_sha ?? range.end_sha
    if (range.start_sha === null || to === null) {
        return range.start_sha === null ? '' : `${shortSha(range.start_sha)}..`
    }
    return `${shortSha(range.start_sha)}..${shortSha(to)}`
}

/** A range as a Diff panel's readout names it: the repository, then its commits, `web · 5b1e0c4..c9d24f8`. */
export function rangeText(range: RunRange): string {
    const span = rangeSpan(range)
    return span === '' ? `${range.repo} · nothing read` : `${range.repo} · ${span}`
}

/**
 * What a Diff panel says of the diff it shows, above it: what the run's own change runs from and to, or what the
 * branch's is against.
 */
export function viewText(change: RunChange, view: ChangeView): string {
    if (view === 'branch') {
        return (
            "The whole branch against its base, from where it leaves the base to the same commit: every run's work " +
            "on it, not only this one's."
        )
    }
    const from = change.range.start_on_base
        ? "the base's commit it started from, origin having no branch yet,"
        : "the commit origin's branch was at when it started"
    const to = change.range.unpushed_sha === null ? 'the one it left on origin' : 'the last commit it made in its slot'
    return `What this run changed, from ${from} to ${to}.`
}

/** What a Diff panel says of a diff that is not there to show: never kept, and why, or removed since. */
export function missingText(change: RunChange, view: ChangeView): string {
    const kept = view === 'run' ? change.diff : change.branch_diff
    if (kept !== null) {
        return ''
    }
    if (change.range.start_sha === null || change.missing !== null) {
        return `no diff kept: ${change.missing ?? "canopy read nothing of the run's slot"}`
    }
    return goneText(change.removed_after_days, 'no diff kept: its file is missing, or not a regular file')
}

/** What a Diff panel says of a kept diff with no files in it. */
export function noChangeText(view: ChangeView): string {
    return view === 'run'
        ? 'no change: the run left the branch where it started'
        : 'no change: the branch holds nothing its base does not'
}

/** What a run's page says when the run recorded nothing of what it changed, though a run of its kind would have. */
export const NOTHING_RECORDED =
    "canopy recorded nothing of what this run changed: it ended before canopy kept a run's diffs, or was closed " +
    'without reaching its end, as reconcile closes one'

/** What a Diff panel says of a run that left its work unpushed. */
export const NOT_ON_ORIGIN =
    'Work not on origin: the run left this commit unpushed in its slot, and it went with the slot. The diff is ' +
    'what is left of it.'

/** A range's hover in a runs list: what its commits are, and where the diff between them is read. */
export function rangeTitle(range: RunRange): string {
    const to = range.unpushed_sha === null ? 'the one it left on origin' : 'the commit it left unpushed in its slot'
    return `what the run changed in ${range.repo}: from the commit it started from to ${to}; its page shows the diff`
}
