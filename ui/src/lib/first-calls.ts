// The spend page's first calls by week (DESIGN §13): each kind's first model calls, how much of them the cache served,
// and the weeks a runtime version or a definitions snapshot first showed up. The numbers are `canopy spend --json`'s
// `first_call_weeks`; this picks a series out of them and says it.

import { SPEND_KINDS } from '@/api/types'
import type { SpendFirstCallWeek, SpendKind } from '@/api/types'
import { shareText } from '@/lib/spend'
import { tokenCount } from '@/lib/transcript'

/** One series of a kind's weeks: every run of the kind, one chore's, or one model's, as its chip names it. */
export interface FirstCallSeries {
    /** Its key in the page's search, `kind`, `chore:deps`, or `model:anthropic/claude-sonnet-4-5`. */
    id: string
    /** Its chip's words: `all runs`, the chore's name, or the model's id. */
    label: string
    /** Whether its name is a model's id, which the page sets in mono. */
    model: boolean
}

/** The kind's own series, which every kind with a week has, and which the page shows unless another is picked. */
export const KIND_SERIES = 'kind'

/** The kind the panel draws: the one picked, else the first, in `canopy spend`'s order, with a week in the window. */
export function firstKind(weeks: readonly SpendFirstCallWeek[], chosen: SpendKind | undefined): SpendKind | undefined {
    return chosen ?? SPEND_KINDS.find((k) => weeks.some((week) => week.kind === k))
}

/**
 * The series a kind's weeks offer, in the server's order: the kind's own, then each chore's, then each model's. The
 * runs no one model served are in the kind's own and have no series of their own here: they are no model's trend.
 */
export function seriesOf(weeks: readonly SpendFirstCallWeek[], kind: SpendKind): FirstCallSeries[] {
    const found = new Map<string, FirstCallSeries>()
    for (const week of weeks) {
        const id = seriesId(week)
        if (week.kind === kind && id !== undefined && !found.has(id)) {
            found.set(id, { id, label: week.name ?? 'all runs', model: week.by === 'model' })
        }
    }
    return [...found.values()]
}

/** One series' weeks, oldest first, as the server sent them; none when the kind has no such series. */
export function seriesWeeks(
    weeks: readonly SpendFirstCallWeek[],
    kind: SpendKind,
    series: string,
): SpendFirstCallWeek[] {
    return weeks.filter((week) => week.kind === kind && seriesId(week) === series)
}

// A week's series as the search names it; undefined for the runs no one model served.
function seriesId(week: SpendFirstCallWeek): string | undefined {
    if (week.by === 'kind') {
        return KIND_SERIES
    }
    return week.name === null ? undefined : `${week.by}:${week.name}`
}

/**
 * An ISO week, `2026-W41`, as the day it starts on, `Oct 5`: the Monday, as the operator's calendar has it. A week the
 * page cannot read is said as the server named it.
 */
export function weekLabel(week: string): string {
    const monday = weekStart(week)
    return monday === undefined
        ? week
        : monday.toLocaleDateString('en-US', { month: 'short', day: 'numeric', timeZone: 'UTC' })
}

/** The Monday an ISO week, `2026-W41`, starts on, at midnight UTC; undefined for a week that is not one. */
export function weekStart(week: string): Date | undefined {
    const match = /^(\d{4})-W(\d{2})$/u.exec(week)
    if (match === null) {
        return undefined
    }
    const [year, number] = [Number(match[1]), Number(match[2])]
    if (number < 1 || number > 53) {
        return undefined
    }
    // The first ISO week is the one with the year's first Thursday in it, so January 4th is always in it.
    const fourth = new Date(Date.UTC(year, 0, 4))
    const firstMonday = 4 - ((fourth.getUTCDay() + 6) % 7)
    return new Date(Date.UTC(year, 0, firstMonday + (number - 1) * 7))
}

/**
 * What a week's runs used first, in `canopy spend`'s words: each runtime version, then the definitions snapshots, that
 * none of the series' earlier weeks did, `runtime 1.0.104`, `snapshot a81d2c4e9f306b17`. A kind renders a snapshot for
 * each prompt, persona, and model its runs use, so one change to canopy or its config makes several at once: more than
 * one is a count, `7 snapshots`, which `snapshotsOf` names. Empty for a week that changed nothing.
 */
export function weekChanges(week: Pick<SpendFirstCallWeek, 'new_runtime_versions' | 'new_digests'>): string[] {
    const digests = week.new_digests
    const [only] = digests
    const snapshots =
        only === undefined ? [] : digests.length === 1 ? [`snapshot ${only}`] : [`${digests.length} snapshots`]
    return [...week.new_runtime_versions.map((v) => `runtime ${v}`), ...snapshots]
}

/** The snapshots a week's count of them stands for, one to a line; undefined when `weekChanges` names them itself. */
export function snapshotsOf(week: Pick<SpendFirstCallWeek, 'new_digests'>): string | undefined {
    return week.new_digests.length > 1 ? week.new_digests.join('\n') : undefined
}

/**
 * A week's bar on hover: when it starts, its hit rate, its median first call with its unit, its runs, and what
 * changed: `Week of Sep 28: 79% from the cache, a median 22.4k sent, 3 runs; new runtime 1.0.104`.
 */
export function weekHint(week: SpendFirstCallWeek): string {
    const runs = week.runs === 1 ? '1 run' : `${week.runs} runs`
    const hit = week.hit_rate === null ? 'no cache read recorded' : `${shareText(week.hit_rate)} from the cache`
    const changed = weekChanges(week)
    const parts = `${hit}, a median ${tokenCount(week.first_call)} sent, ${runs}`
    return `Week of ${weekLabel(week.week)}: ${parts}${changed.length === 0 ? '' : `; new ${changed.join(', ')}`}`
}
