// The all-clear's digest (ui/DESIGN.md, "An empty attention list"): what the journal says of today, whenever the page
// is opened. It covers the local day because that is a window the journal can answer for: what a tab saw clear is held
// by the tab and gone on a reload, so items cleared are not counted here (the note on coming back, `lib/away.ts`, does
// count them, over its one absence).
import type { RunsSince } from '@/api/types'
import { counted } from '@/lib/descriptions'

/** The start of `now`'s local day, ISO: the moment the digest counts from, moving on by itself at midnight. */
export function startOfDay(now: number): string {
    const day = new Date(now)
    day.setHours(0, 0, 0, 0)
    return day.toISOString()
}

/**
 * The digest's line, every count of none left out: `Today: 2 PRs opened · 5 runs ended`. Null when the day holds
 * neither, so the line goes rather than pad the page.
 */
export function todayLine(runs: RunsSince): string | null {
    const parts = [
        runs.prs_opened > 0 && `${counted(runs.prs_opened, 'PR')} opened`,
        runs.ended > 0 && `${counted(runs.ended, 'run')} ended`,
    ].filter((part) => part !== false)
    return parts.length === 0 ? null : `Today: ${parts.join(' · ')}`
}
