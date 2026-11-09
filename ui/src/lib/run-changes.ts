/**
 * What a worker's or a task's run changed (DESIGN §45): each repository's range and size, as its page's Diff panel and
 * its ticket's and its PR's runs lists name them, and what the panel, or a PR's page, says where it has no diff.
 */

import type { ChangedFile, MissingDiff, RunChange, RunRange } from '@/api/types'
import { goneText } from '@/lib/retention'
import { shortSha } from '@/lib/reviews'

/** The id of a repository's Diff panel on a run's page, which a runs list's range links to: `diff-web`. */
export function diffAnchor(repo: string): string {
    return `diff-${repo}`
}

/**
 * A range's commits, short, as `git log` names a range: from the one the run started from to the one its diff is of,
 * the commit it left unpushed in its slot when it left one, else the one it left on origin. One with no end says
 * nothing was pushed rather than trailing off; empty when canopy read nothing of the slot, as for a run that crashed.
 */
export function rangeSpan(range: RunRange): string {
    if (range.start_sha === null) {
        return ''
    }
    const to = range.unpushed_sha ?? range.end_sha
    return to === null
        ? `${shortSha(range.start_sha)} → nothing pushed`
        : `${shortSha(range.start_sha)}..${shortSha(to)}`
}

/** A range as a Diff panel's readout names it: the repository, then its commits, `web · 5b1e0c4..c9d24f8`. */
export function rangeText(range: RunRange): string {
    const span = rangeSpan(range)
    return span === '' ? `${range.repo} · nothing read` : `${range.repo} · ${span}`
}

/** What a range runs from and to, in words, for its hover: what the short commits do not say. */
export function rangeTitle(range: RunRange): string {
    if (range.start_sha === null) {
        return 'canopy read nothing of the run’s slot'
    }
    const from = range.start_on_base
        ? 'the base’s commit, origin having no branch when the run started'
        : 'where origin’s branch was when the run started'
    if (range.unpushed_sha === null) {
        const to =
            range.end_sha === null ? 'nothing: the run left no branch on origin' : 'where the run left it on origin'
        return `From ${from}, to ${to}.`
    }
    return `From ${from}, to the last commit the run made in its slot, never pushed.`
}

/** How many files a range's change touched, `2 files`; empty when canopy counted nothing. */
export function filesText(range: RunRange): string {
    const n = range.files_changed
    return n === null ? '' : `${n} ${n === 1 ? 'file' : 'files'}`
}

/** A count of lines added and removed, git's `+21 −3`. */
export function linesText(added: number, removed: number): [string, string] {
    return [`+${added}`, `−${removed}`]
}

/** A file's path as a changed file's row names it: `old → new` when git found it renamed. */
export function changedPath(file: ChangedFile): string {
    return file.old_path === null ? file.path : `${file.old_path} → ${file.path}`
}

/** How many files a change's summary leaves out, past the bound the journal keeps: `and 12 more files`. */
export function filesLeftOutText(change: RunChange): string {
    const more = (change.range.files_changed ?? 0) - change.files.length
    return more > 0 ? `and ${more} more ${more === 1 ? 'file' : 'files'}` : ''
}

/** What a Diff panel says where it has no diff to open: never kept and why, or removed since; empty if it has one. */
export function missingText(change: RunChange): string {
    if (change.diff_kept) {
        return ''
    }
    if (change.range.start_sha === null || change.missing !== null) {
        return `no diff kept: ${change.missing ?? 'canopy read nothing of the run’s slot'}`
    }
    return goneText(change.removed_after_days, 'no diff kept: its file is missing, or not a regular file')
}

/**
 * What a PR's page says of the latest run that left its work on origin, when no run kept a diff its threads could sit
 * on: why its end kept none, or that retention removed it, in the words its own Diff panel uses.
 */
export function missingDiffText(missing: MissingDiff): string {
    return missing.missing === null
        ? goneText(missing.removed_after_days, 'no diff kept: its file is missing, or not a regular file')
        : `no diff kept: ${missing.missing}`
}

/** What a Diff panel says of a change git counted no file in. */
export const NO_CHANGE = 'no change: the run left the branch where it started'

/** What a Diff panel says of a change canopy did not count, as one from before it counted them. */
export const NOT_COUNTED = 'canopy counted no files for this run: it ended before canopy counted them'

/** What a run's page says when the run recorded nothing of what it changed, though a run of its kind would have. */
export const NOTHING_RECORDED =
    "canopy recorded nothing of what this run changed: it ended before canopy kept a run's diffs, or was closed " +
    'without reaching its end, as reconcile closes one'

/** What a Diff panel's `not on origin` chip says on its hover. */
export const NOT_ON_ORIGIN =
    'The run left this commit unpushed in its slot, and it went with the slot: this is what is left of the work.'

/** What a Diff panel says when the diff it opened could not be read. */
export const DIFF_UNREAD = 'the diff could not be read: its file is gone, or not a regular file'
