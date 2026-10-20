import { useSyncExternalStore } from 'react'

import type { Clock } from '@/lib/clock'

const UNITS: [suffix: string, seconds: number][] = [
    ['d', 86_400],
    ['h', 3_600],
    ['m', 60],
]

/** How long before `now` an ISO time was, in its largest whole unit, as the CLI says it: `3d`, `2h`, `5m`, `40s`. */
export function age(iso: string, now: number): string {
    const seconds = Math.max(0, Math.floor((now - Date.parse(iso)) / 1000))
    for (const [suffix, size] of UNITS) {
        if (seconds >= size) {
            return `${Math.floor(seconds / size)}${suffix}`
        }
    }
    return `${seconds}s`
}

/** An ISO time as the operator's local date and time to the second, on their clock, for a title attribute. */
export function localTime(iso: string, clock: Clock): string {
    return formatter('whole', clock).format(new Date(iso))
}

/**
 * An ISO time as a short local stamp, its month in the operator's language, on their clock: `Oct 8 10:30`,
 * `Oct 8 10:30 AM`, or with the zone, `Oct 8 10:30 EDT`.
 */
export function stamp(iso: string, clock: Clock): string {
    const parts = stampParts(iso, clock)
    return `${parts.month ?? ''} ${parts.day ?? ''} ${timeOfDay(parts)}`
}

/** An ISO time as its local time of day alone, on the operator's clock: `14:05`, `2:05 PM`, or `14:05 EDT`. */
export function clockTime(iso: string, clock: Clock): string {
    return timeOfDay(stampParts(iso, clock))
}

/**
 * When something that ran ended, set after when it started: the local time alone when it ended the day it started
 * (`06:59`), else the whole stamp (`Oct 9 01:10`).
 */
export function endStamp(started: string, ended: string, clock: Clock): string {
    const sameDay = new Date(started).toDateString() === new Date(ended).toDateString()
    return sameDay ? clockTime(ended, clock) : stamp(ended, clock)
}

/** How long something ran, from its start to its end, in the CLI's largest whole unit, as an age is: `29m`. */
export function lasted(started: string, ended: string): string {
    return age(started, Date.parse(ended))
}

type StampParts = Partial<Record<Intl.DateTimeFormatPartTypes, string>>

// What each format shows. The hour is two digits on a 24-hour clock, so `09:05` lines up under `14:05`, and bare on a
// 12-hour one, which reads `9:05 AM` as people say it.
const SHAPES = {
    stamp: { month: 'short', day: 'numeric', minute: '2-digit' },
    whole: { year: 'numeric', month: 'numeric', day: 'numeric', minute: '2-digit', second: '2-digit' },
} satisfies Record<string, Intl.DateTimeFormatOptions>

// A formatter is slow to make and every stamp on a page uses one, so each shape and clock gets one, made once.
const formatters = new Map<string, Intl.DateTimeFormat>()

function formatter(shape: keyof typeof SHAPES, clock: Clock): Intl.DateTimeFormat {
    const key = `${shape} ${clock.hours} ${String(clock.zone)}`
    let made = formatters.get(key)
    if (made === undefined) {
        made = new Intl.DateTimeFormat(undefined, {
            ...SHAPES[shape],
            hour: clock.hours === '24' ? '2-digit' : 'numeric',
            hourCycle: clock.hours === '24' ? 'h23' : 'h12',
            ...(clock.zone ? { timeZoneName: 'short' } : {}),
        })
        formatters.set(key, made)
    }
    return made
}

function stampParts(iso: string, clock: Clock): StampParts {
    return Object.fromEntries(
        formatter('stamp', clock)
            .formatToParts(new Date(iso))
            .map((p) => [p.type, p.value]),
    )
}

// The time of day from a stamp's parts, then AM or PM on a 12-hour clock, then the zone when it is shown.
function timeOfDay(parts: StampParts): string {
    return [`${parts.hour ?? ''}:${parts.minute ?? ''}`, parts.dayPeriod, parts.timeZoneName]
        .filter((part) => part !== undefined)
        .join(' ')
}

// One clock for every age on the page: it ticks every second while something reads it, so an age in seconds counts.
const TICK_MS = 1_000
let now = Date.now()
const listeners = new Set<() => void>()
let timer: ReturnType<typeof setInterval> | undefined

function subscribe(listener: () => void): () => void {
    listeners.add(listener)
    if (timer === undefined) {
        now = Date.now()
        timer = setInterval(() => {
            now = Date.now()
            for (const notify of listeners) {
                notify()
            }
        }, TICK_MS)
    }
    return () => {
        listeners.delete(listener)
        if (listeners.size === 0 && timer !== undefined) {
            clearInterval(timer)
            timer = undefined
        }
    }
}

/** The current time, in milliseconds, updated every second. */
export function useNow(): number {
    return useSyncExternalStore(
        subscribe,
        () => now,
        () => now,
    )
}
