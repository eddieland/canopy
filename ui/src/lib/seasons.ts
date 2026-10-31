import { useEffect, useState } from 'react'

import { storedSetting, useStoredSetting } from '@/lib/stored-setting'

/**
 * The seasons canopy decorates for: a few days of the year each, when a little scene stands at the foot of the rail
 * (drawn in src/components/season.tsx), beside Sprig or the Ghost when one is there, and some hang something over the
 * header's logo (src/components/season-logo.tsx). Read from the browser's own clock and calendar, so the decoration
 * comes and goes on the operator's local dates. Settings turns the seasons off, on their own, whoever sits in the rail.
 * Winter starts the day after the latest Thanksgiving can fall, so the lights go up once the pie is put away.
 */

/** A season canopy decorates for. */
export type SeasonId = 'newyear' | 'valentines' | 'shamrock' | 'spring' | 'halloween' | 'harvest' | 'winter'

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
    { id: 'newyear', from: [1, 1], to: [1, 6] },
    { id: 'valentines', from: [2, 7], to: [2, 14] },
    { id: 'shamrock', from: [3, 10], to: [3, 17] },
    { id: 'spring', from: [3, 25], to: [4, 15] },
    { id: 'halloween', from: [10, 15], to: [10, 31] },
    { id: 'harvest', from: [11, 20], to: [11, 28] },
    { id: 'winter', from: [11, 29], to: [12, 31] },
]

/** How often a page left open looks at the calendar again, so a season comes and goes without a reload. */
const RECHECK_MS = 60 * 60 * 1000

/** The season on `date`'s local day, or null on a day with none. */
export function seasonOn(date: Date): SeasonId | null {
    const today = order([date.getMonth() + 1, date.getDate()])
    return SEASONS.find((season) => order(season.from) <= today && today <= order(season.to))?.id ?? null
}

/** Whether canopy decorates for the seasons. */
export type SeasonsSetting = 'on' | 'off'

/** Where localStorage keeps the setting. */
export const STORAGE_KEY = 'canopy-seasons'
/** The setting until the operator turns the seasons off: on. */
export const DEFAULT: SeasonsSetting = 'on'

/** The setting as stored, or the default for anything it does not recognize. */
export function parseSeasons(raw: string | null): SeasonsSetting {
    return raw === 'on' || raw === 'off' ? raw : DEFAULT
}

const setting = storedSetting({ key: STORAGE_KEY, parse: parseSeasons, serialize: (value: SeasonsSetting) => value })

/**
 * The season to decorate for today, looked at again every hour while the page is open: null on a day with none, or
 * while Settings has the seasons off.
 */
export function useSeason(): SeasonId | null {
    const on = useSeasons() === 'on'
    const [season, setSeason] = useState(() => seasonOn(new Date()))
    useEffect(() => {
        const timer = globalThis.setInterval(() => setSeason(seasonOn(new Date())), RECHECK_MS)
        return () => globalThis.clearInterval(timer)
    }, [])
    return on ? season : null
}

/** Whether the seasons are decorated for. Re-renders on a change from this tab or another. */
export function useSeasons(): SeasonsSetting {
    return useStoredSetting(setting)
}

/** Stores the setting and applies it now. */
export function setSeasons(next: SeasonsSetting): void {
    setting.set(next)
}

/** A day as one number that sorts as the days of the year do. */
function order([month, day]: Day): number {
    return month * 100 + day
}
