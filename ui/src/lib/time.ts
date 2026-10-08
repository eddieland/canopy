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
        if (seconds >= size) return `${Math.floor(seconds / size)}${suffix}`
    }
    return `${seconds}s`
}

/** An ISO time as the operator's local date and time, for a title attribute. */
export function localTime(iso: string): string {
    return new Date(iso).toLocaleString()
}

// One clock for every age on the page: it ticks every 15 seconds while something reads it.
const TICK_MS = 15_000
let now = Date.now()
const listeners = new Set<() => void>()
let timer: ReturnType<typeof setInterval> | undefined

function subscribe(listener: () => void): () => void {
    listeners.add(listener)
    if (timer === undefined) {
        now = Date.now()
        timer = setInterval(() => {
            now = Date.now()
            for (const notify of listeners) notify()
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

/** The current time, in milliseconds, updated every 15 seconds: enough for ages in minutes. */
export function useNow(): number {
    return useSyncExternalStore(
        subscribe,
        () => now,
        () => now,
    )
}
