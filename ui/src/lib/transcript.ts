import type { TranscriptEntry } from '@/api/types'

/** How long after `start` an ISO time was, as a readout: `+0:42`, `+12:05`, `+1:02:09`. Empty without both times. */
export function elapsed(at: string | null, start: string | null): string {
    if (at === null || start === null) return ''
    const seconds = Math.max(0, Math.floor((Date.parse(at) - Date.parse(start)) / 1000))
    const h = Math.floor(seconds / 3600)
    const m = Math.floor((seconds % 3600) / 60)
    const s = String(seconds % 60).padStart(2, '0')
    return h > 0 ? `+${h}:${String(m).padStart(2, '0')}:${s}` : `+${m}:${s}`
}

/** A duration in milliseconds as a readout: `840ms`, `14s`, `3m 05s`. */
export function duration(ms: number): string {
    if (ms < 1000) return `${ms}ms`
    const seconds = Math.round(ms / 1000)
    if (seconds < 60) return `${seconds}s`
    return `${Math.floor(seconds / 60)}m ${String(seconds % 60).padStart(2, '0')}s`
}

/** A token count as the CLI says it (`agent_output.Usage.describe`): `950`, `12.3k`, `1.2M`. */
export function tokenCount(n: number): string {
    if (n >= 1_000_000) return `${(n / 1_000_000).toFixed(1)}M`
    if (n >= 1_000) return `${(n / 1_000).toFixed(1)}k`
    return String(n)
}

export interface Tally {
    tools: number
    failed: number
    calls: number
    errors: number
}

/** How many tool calls, failed tool calls, model calls, and runtime errors a transcript holds. */
export function tally(entries: TranscriptEntry[]): Tally {
    const found: Tally = { tools: 0, failed: 0, calls: 0, errors: 0 }
    for (const entry of entries) {
        if (entry.kind === 'tool') {
            found.tools += 1
            if (entry.status === 'error') found.failed += 1
        } else if (entry.kind === 'step') {
            found.calls += 1
        } else if (entry.kind === 'error') {
            found.errors += 1
        }
    }
    return found
}

/** The first time a transcript names, which every entry's `elapsed` counts from. */
export function startOf(entries: TranscriptEntry[]): string | null {
    return entries.find((e) => e.at !== null)?.at ?? null
}

/**
 * What a tool call was about, from its input when the runtime gave it no title: its first string value on one line,
 * as `{"filePath": "/x"}` reads `/x`. Empty when the input has none, or was cut and no longer parses.
 */
export function hint(input: string): string {
    let parsed: unknown
    try {
        parsed = JSON.parse(input)
    } catch {
        return ''
    }
    if (typeof parsed !== 'object' || parsed === null) return ''
    const first = Object.values(parsed).find((v): v is string => typeof v === 'string')
    return first === undefined ? '' : first.replace(/\s+/g, ' ').trim().slice(0, 200)
}
