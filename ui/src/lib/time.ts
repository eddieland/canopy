import { useSyncExternalStore } from 'react'

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

/** An ISO time as the operator's local date and time, for a title attribute. */
export function localTime(iso: string): string {
    return new Date(iso).toLocaleString()
}

const STAMP = new Intl.DateTimeFormat(undefined, {
    month: 'short',
    day: 'numeric',
    hour: '2-digit',
    minute: '2-digit',
    hourCycle: 'h23',
})

/** An ISO time as a short local stamp, its month in the operator's language: `Oct 8 10:30`. */
export function stamp(iso: string): string {
    const parts = stampParts(iso)
    return `${parts.month ?? ''} ${parts.day ?? ''} ${clock(parts)}`
}

/**
 * When something that ran ended, set after when it started: the local time alone when it ended the day it started
 * (`06:59`), else the whole stamp (`Oct 9 01:10`).
 */
export function endStamp(started: string, ended: string): string {
    const sameDay = new Date(started).toDateString() === new Date(ended).toDateString()
    return sameDay ? clock(stampParts(ended)) : stamp(ended)
}

/** How long something ran, from its start to its end, in the CLI's largest whole unit, as an age is: `29m`. */
export function lasted(started: string, ended: string): string {
    return age(started, Date.parse(ended))
}

type StampParts = Partial<Record<Intl.DateTimeFormatPartTypes, string>>

function stampParts(iso: string): StampParts {
    return Object.fromEntries(STAMP.formatToParts(new Date(iso)).map((p) => [p.type, p.value]))
}

function clock(parts: StampParts): string {
    return `${parts.hour ?? ''}:${parts.minute ?? ''}`
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
