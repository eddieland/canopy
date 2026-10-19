import { TICKER_TOPICS } from '@/lib/headlines'
import type { TickerTopic } from '@/lib/headlines'
import { storedSetting, useStoredSetting } from '@/lib/stored-setting'

/**
 * The header ticker's settings (src/components/shell/ticker.tsx): whether it shows, how fast a headline crawls, how
 * many seconds the window stays empty before the next one, and which topics it leaves out. Kept in localStorage like
 * the theme, and synced across tabs.
 */

/** How fast a headline crawls. */
export type TickerSpeed = 'slow' | 'normal' | 'spicy'

/** The ticker's settings as stored. */
export interface TickerSettings {
    /** Whether the ticker shows. Off keeps the rest, for when it is turned back on. */
    on: boolean
    /** How fast a headline crawls. */
    speed: TickerSpeed
    /** Seconds between one headline leaving and the next arriving. */
    gap: number
    /**
     * The topics turned off, in TICKER_TOPICS order. Kept as those left out, not those shown, so a topic added later
     * shows until the operator turns it off.
     */
    hidden: TickerTopic[]
}

/** Where localStorage keeps the settings, as JSON. */
export const STORAGE_KEY = 'canopy-ticker'
/** The settings until the operator changes them: on, a normal crawl, no gap between headlines, and every topic. */
export const DEFAULTS: TickerSettings = { on: true, speed: 'normal', gap: 0, hidden: [] }
/** The longest gap, in seconds: ten minutes. */
export const MAX_GAP = 600

/** How far a headline crawls each second, in rem, so it keeps its pace as the interface grows on a large screen. */
export const SPEED_REM: Record<TickerSpeed, number> = { slow: 2.5, normal: 4.5, spicy: 9 }

const SPEEDS = new Set<string>(['slow', 'normal', 'spicy'])

function isSpeed(value: unknown): value is TickerSpeed {
    return typeof value === 'string' && SPEEDS.has(value)
}

/** A gap as stored: whole seconds from 0 to MAX_GAP, or undefined for anything that is not a number. */
export function clampGap(value: unknown): number | undefined {
    if (typeof value !== 'number' || !Number.isFinite(value)) {
        return undefined
    }
    return Math.min(MAX_GAP, Math.max(0, Math.round(value)))
}

/** Topics as stored: the known ones among `value`, once each, in TICKER_TOPICS order; none for a non-list. */
export function parseTopics(value: unknown): TickerTopic[] {
    if (!Array.isArray(value)) {
        return []
    }
    return TICKER_TOPICS.filter((topic) => value.includes(topic))
}

/** The hidden topics once `topic` is shown, or hidden when `shown` is false. */
export function withTopic(hidden: readonly TickerTopic[], topic: TickerTopic, shown: boolean): TickerTopic[] {
    return TICKER_TOPICS.filter((t) => (t === topic ? !shown : hidden.includes(t)))
}

/** Settings from their stored JSON, each field falling back to its default when missing or invalid. */
export function parseSettings(raw: string | null): TickerSettings {
    let stored: unknown = null
    try {
        stored = raw === null ? null : JSON.parse(raw)
    } catch {
        // Not JSON: the defaults.
    }
    if (typeof stored !== 'object' || stored === null) {
        return DEFAULTS
    }
    const { on, speed, gap, hidden } = stored as Record<string, unknown>
    return {
        // Off was once a speed: a ticker stored at that speed is off, at the default speed for when it comes back.
        on: typeof on === 'boolean' ? on && speed !== 'off' : speed !== 'off',
        speed: isSpeed(speed) ? speed : DEFAULTS.speed,
        gap: clampGap(gap) ?? DEFAULTS.gap,
        hidden: parseTopics(hidden),
    }
}

const setting = storedSetting({ key: STORAGE_KEY, parse: parseSettings, serialize: JSON.stringify })

/** The ticker's settings. Re-renders on a change from this tab or another. */
export function useTickerSettings(): TickerSettings {
    return useStoredSetting(setting)
}

/** Stores a change to any of the settings and applies it now. */
export function setTickerSettings(change: Partial<TickerSettings>): void {
    setting.set({ ...setting.get(), ...change })
}
