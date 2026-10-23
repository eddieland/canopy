import { useEffect } from 'react'

import { storedSetting, useStoredSetting } from '@/lib/stored-setting'

/**
 * The tickets the operator viewed most recently in this browser, newest first, for the jump palette (ui/DESIGN.md,
 * The jump palette). Kept in localStorage and synced across tabs, never in the journal: what the operator looked at
 * is this browser's business alone. A ticket's page and its plan's record a view (`useViewedTicket`).
 */

/** A ticket viewed: its key, its title as it was then, and when. */
export interface RecentTicket {
    /** The ticket's key, as the tracker names it. */
    key: string
    /** Its title when it was viewed, null while it had none; the palette shows the tickets list's when it has one. */
    title: string | null
    /** When it was viewed, ISO. */
    viewedAt: string
}

/** Where localStorage keeps the list. */
export const STORAGE_KEY = 'canopy-recent-tickets'
/** How many tickets the list keeps; the palette shows fewer. */
export const RECENT_MAX = 20

/** The list as stored, or empty for anything that is not one: each entry that is not a ticket viewed is dropped. */
export function parseRecent(raw: string | null): RecentTicket[] {
    if (raw === null) {
        return []
    }
    let value: unknown
    try {
        value = JSON.parse(raw)
    } catch {
        return []
    }
    return Array.isArray(value) ? value.filter((entry) => isRecent(entry)).slice(0, RECENT_MAX) : []
}

/** `list` with `key` viewed at `at`: moved to the top if it was there, and the oldest past `RECENT_MAX` dropped. */
export function viewed(list: readonly RecentTicket[], key: string, title: string | null, at: string): RecentTicket[] {
    return [{ key, title, viewedAt: at }, ...list.filter((t) => t.key !== key)].slice(0, RECENT_MAX)
}

/** `list` without the tickets `keys` does not hold, such as one forgotten since it was viewed. */
export function known(list: readonly RecentTicket[], keys: ReadonlySet<string>): RecentTicket[] {
    return list.filter((t) => keys.has(t.key))
}

const setting = storedSetting({ key: STORAGE_KEY, parse: parseRecent, serialize: (value) => JSON.stringify(value) })

/** The tickets viewed, newest first. Re-renders on a change from this tab or another. */
export function useRecentTickets(): RecentTicket[] {
    return useStoredSetting(setting)
}

/** Stores the list without the tickets `keys` does not hold. */
export function keepKnown(keys: ReadonlySet<string>): void {
    setting.set(known(setting.get(), keys))
}

/**
 * Records that the operator is viewing ticket `key`, once its title has loaded (`undefined` until it has), and again
 * when it opens another ticket or the title changes.
 */
export function useViewedTicket(key: string, title: string | null | undefined): void {
    useEffect(() => {
        if (title !== undefined) {
            setting.set(viewed(setting.get(), key, title, new Date().toISOString()))
        }
    }, [key, title])
}

function isRecent(entry: unknown): entry is RecentTicket {
    if (typeof entry !== 'object' || entry === null) {
        return false
    }
    const { key, title, viewedAt } = entry as Record<string, unknown>
    return (
        typeof key === 'string' &&
        (typeof title === 'string' || title === null) &&
        typeof viewedAt === 'string' &&
        !Number.isNaN(Date.parse(viewedAt))
    )
}
