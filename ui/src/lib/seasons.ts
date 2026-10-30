import { useEffect, useState } from 'react'

/**
 * The seasons Sprig decorates for: a few days of the year each, when a little something stands beside it at the foot
 * of the rail (drawn in src/components/season.tsx), beside the Ghost too when it sits in Sprig's place. Read from the
 * browser's own clock and calendar, so the decoration comes and goes on the operator's local dates, with no setting:
 * turning Sprig off puts it away too.
 */

/** A season Sprig decorates for. */
export type SeasonId = 'valentines' | 'shamrock' | 'halloween' | 'winter'

/** A day of the year: its month, 1 for January, and its day of the month. */
type Day = readonly [month: number, day: number]

/** One season, and the days it runs. */
export interface Season {
    /** Which season it is. */
    id: SeasonId
    /** The first day it shows. */
    from: Day
    /** The last day it shows. */
    to: Day
}

/** The seasons, in the order of the year. None runs over the new year, and none overlaps another. */
export const SEASONS: readonly Season[] = [
    { id: 'valentines', from: [2, 7], to: [2, 14] },
    { id: 'shamrock', from: [3, 10], to: [3, 17] },
    { id: 'halloween', from: [10, 15], to: [10, 31] },
    { id: 'winter', from: [12, 1], to: [12, 31] },
]

/** How often a page left open looks at the calendar again, so a season comes and goes without a reload. */
const RECHECK_MS = 60 * 60 * 1000

/** The season on `date`'s local day, or null on a day with none. */
export function seasonOn(date: Date): SeasonId | null {
    const today = order([date.getMonth() + 1, date.getDate()])
    return SEASONS.find((season) => order(season.from) <= today && today <= order(season.to))?.id ?? null
}

/** The season today, looked at again every hour while the page is open. */
export function useSeason(): SeasonId | null {
    const [season, setSeason] = useState(() => seasonOn(new Date()))
    useEffect(() => {
        const timer = globalThis.setInterval(() => setSeason(seasonOn(new Date())), RECHECK_MS)
        return () => globalThis.clearInterval(timer)
    }, [])
    return season
}

/** A day as one number that sorts as the days of the year do. */
function order([month, day]: Day): number {
    return month * 100 + day
}
