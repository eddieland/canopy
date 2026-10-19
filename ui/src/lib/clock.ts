import { storedSetting, useStoredSetting } from '@/lib/stored-setting'

/**
 * How the UI writes a time of day (src/lib/time.ts): on a 24-hour clock (`14:05`) or a 12-hour one (`2:05 PM`), and
 * with or without the time zone after it (`14:05 EDT`). Kept in localStorage like the theme, and synced across tabs.
 */

/** Which clock a time of day is read on. */
export type Hours = '12' | '24'

/** How a time of day is written. */
export interface Clock {
    /** Which clock: `24` for `14:05`, `12` for `2:05 PM`. */
    hours: Hours
    /** Whether the time zone follows the time, as the browser abbreviates it: `EDT`, `UTC`, `GMT+2`. */
    zone: boolean
}

/** Where localStorage keeps the setting, as JSON. */
export const STORAGE_KEY = 'canopy-clock'
/** The setting until the operator changes it: a 24-hour clock, without the zone. */
export const DEFAULT_CLOCK: Clock = { hours: '24', zone: false }

/** The setting from its stored JSON, each field falling back to its default when missing or invalid. */
export function parseClock(raw: string | null): Clock {
    let stored: unknown = null
    try {
        stored = raw === null ? null : JSON.parse(raw)
    } catch {
        // Not JSON: the defaults.
    }
    if (typeof stored !== 'object' || stored === null) {
        return DEFAULT_CLOCK
    }
    const { hours, zone } = stored as Record<string, unknown>
    return {
        hours: hours === '12' || hours === '24' ? hours : DEFAULT_CLOCK.hours,
        zone: typeof zone === 'boolean' ? zone : DEFAULT_CLOCK.zone,
    }
}

/**
 * The setting as it stands, for text made once and not shown again as it changes (a toast, an action's outcome). A
 * component that shows a time reads it with `useClock` instead, so the time is written again when it changes.
 */
export function currentClock(): Clock {
    return setting.get()
}

/** How a time of day is written. Re-renders on a change from this tab or another. */
export function useClock(): Clock {
    return useStoredSetting(setting)
}

/** Stores a change to the setting and applies it now. */
export function setClock(change: Partial<Clock>): void {
    setting.set({ ...setting.get(), ...change })
}

const setting = storedSetting({ key: STORAGE_KEY, parse: parseClock, serialize: JSON.stringify })
