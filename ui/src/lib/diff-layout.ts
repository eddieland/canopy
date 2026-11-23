import type { DiffLine } from '@/api/types'
import { storedSetting, useStoredSetting } from '@/lib/stored-setting'

/**
 * How a diff's lines are laid out (ui/DESIGN.md, "A review"): `unified`, one column, a removed line above the added
 * one, or `split`, the old side beside the new. Unified until the operator chooses, kept in localStorage as the theme
 * is, and synced across tabs: one choice for every diff.
 */

/** The layouts, in the order the control offers them. */
export const LAYOUTS = ['unified', 'split'] as const

/** A layout of a diff's lines. */
export type DiffLayout = (typeof LAYOUTS)[number]

/** Where localStorage keeps the setting. */
export const STORAGE_KEY = 'canopy-diff-layout'

/** The layout as stored: `unified` for anything else. */
export function parseLayout(raw: string | null): DiffLayout {
    return raw === 'split' ? 'split' : 'unified'
}

/** The layout chosen. Re-renders on a change from this tab or another. */
export function useDiffLayout(): DiffLayout {
    return useStoredSetting(setting)
}

/** Chooses a layout, stores it, and applies it now. */
export function setDiffLayout(layout: DiffLayout): void {
    setting.set(layout)
}

/** One row of a split diff: the line on each side, by its index in its hunk, or undefined where a side has none. */
export interface SplitRow {
    /** The line on the old side: a removed or unchanged one. */
    old: number | undefined
    /** The line on the new side: an added or unchanged one. */
    new: number | undefined
}

/**
 * The rows of a split diff for a hunk's `lines` from `from` up to `to`: an unchanged line on both sides, and where
 * added lines follow removed ones, each removed line beside the added line `pairs` gives it (`pairedLines`), so an
 * edit sits across from what it edited; the lines between two pairs sit side by side in order, the longer side's
 * rest alone. A pair with a line outside the range is no pair here.
 */
export function splitRows(
    lines: readonly DiffLine[],
    pairs: readonly (number | undefined)[],
    from: number,
    to: number,
): SplitRow[] {
    const rows: SplitRow[] = []
    let at = from
    while (at < to) {
        if (lines[at]?.kind === 'ctx') {
            rows.push({ old: at, new: at })
            at += 1
        } else {
            const adds = runEnd(lines, at, to, 'del')
            const end = runEnd(lines, adds, to, 'add')
            let old = at
            let now = adds
            for (let k = at; k < adds; k += 1) {
                const pair = pairs[k]
                if (pair !== undefined && pair >= now && pair < end) {
                    beside(rows, old, k, now, pair)
                    rows.push({ old: k, new: pair })
                    old = k + 1
                    now = pair + 1
                }
            }
            beside(rows, old, adds, now, end)
            at = end
        }
    }
    return rows
}

const setting = storedSetting<DiffLayout>({ key: STORAGE_KEY, parse: parseLayout, serialize: (layout) => layout })

// Where the run of `kind` lines from `from` ends, no later than `to`.
function runEnd(lines: readonly DiffLine[], from: number, to: number, kind: DiffLine['kind']): number {
    let end = from
    while (end < to && lines[end]?.kind === kind) {
        end += 1
    }
    return end
}

// The old lines from `old` to `oldEnd` beside the new ones from `now` to `nowEnd`, in order, the longer's rest alone.
function beside(rows: SplitRow[], old: number, oldEnd: number, now: number, nowEnd: number): void {
    const height = Math.max(oldEnd - old, nowEnd - now)
    for (let k = 0; k < height; k += 1) {
        rows.push({ old: old + k < oldEnd ? old + k : undefined, new: now + k < nowEnd ? now + k : undefined })
    }
}
