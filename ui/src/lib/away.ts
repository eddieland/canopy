// The note on coming back to a tab left hidden (ui/DESIGN.md, "A toast"): what changed while the operator was away,
// in one line. Every count is a fact read after the return, never a guess: the attention list as the stream sends it
// again, compared with the list the tab held as it was hidden, and the runs counted by the server over the journal.
import type { AttentionItem, RunsSince } from '@/api/types'
import { blocking } from '@/lib/attention'
import { currentClock } from '@/lib/clock'
import { endStamp } from '@/lib/time'

/** How long the tab stays hidden before showing it again brings the note: a coffee is not an absence. */
export const AWAY_MS = 10 * 60_000

/** What changed while the tab was hidden. */
export interface AwayChanges {
    /** Items listed now that block work (`blocking`) and were not listed as the tab was hidden. */
    needsYou: number
    /** Items listed as the tab was hidden that are gone from the list now. */
    cleared: number
    /** PRs the runs that ended since opened, as the server counts them. */
    prsOpened: number
    /** Runs that ended since, whatever their status. */
    runsEnded: number
}

/** What changed between the attention items listed as the tab was hidden, by id, and the list and runs now. */
export function awayChanges(left: readonly string[], items: readonly AttentionItem[], runs: RunsSince): AwayChanges {
    const before = new Set(left)
    const after = new Set(items.map((item) => item.id))
    return {
        needsYou: items.filter((item) => blocking(item) && !before.has(item.id)).length,
        cleared: [...before].filter((id) => !after.has(id)).length,
        prsOpened: runs.prs_opened,
        runsEnded: runs.ended,
    }
}

/**
 * The note's line, what needs the operator first and every count of none left out, from when the tab was hidden:
 * `Since 14:05: 1 new item needs you, 3 items cleared, 2 PRs opened`. Null when nothing changed, so the note says
 * nothing rather than that nothing happened.
 */
export function awayLine(since: string, now: string, changes: AwayChanges): string | null {
    const need = changes.needsYou === 1 ? 'needs' : 'need'
    const parts = [
        changes.needsYou > 0 && `${counted(changes.needsYou, 'new item')} ${need} you`,
        changes.cleared > 0 && `${counted(changes.cleared, 'item')} cleared`,
        changes.prsOpened > 0 && `${counted(changes.prsOpened, 'PR')} opened`,
        changes.runsEnded > 0 && `${counted(changes.runsEnded, 'run')} ended`,
    ].filter((part) => part !== false)
    return parts.length === 0 ? null : `Since ${endStamp(since, now, currentClock())}: ${parts.join(', ')}`
}

function counted(n: number, noun: string): string {
    return `${n} ${noun}${n === 1 ? '' : 's'}`
}
