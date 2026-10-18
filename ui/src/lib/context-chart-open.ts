import { useSyncExternalStore } from 'react'

/**
 * Which kinds of page open a transcript's context chart (ui/DESIGN.md, "A transcript's context"): its bars and what
 * grew a call, under its one line. Closed until the operator opens it, since a transcript is opened to read what the
 * agent did far more often than to ask why its context grew. Each kind of page keeps its own choice, across reloads:
 * kept in localStorage as Pretty is, and synced across tabs.
 */

/** The pages a transcript sits on, each keeping its own choice: a run's, a chore run's, and a tick's. */
export const PAGES = ['run', 'chore-run', 'tick'] as const

/** A kind of page a transcript sits on. */
export type TranscriptPage = (typeof PAGES)[number]

/** Where localStorage keeps the pages whose chart is open, as a JSON array of their kinds. */
export const STORAGE_KEY = 'canopy-context-chart'

/** The pages as stored, keeping only kinds it knows, in its own order: none for anything else. */
export function parseOpen(raw: string | null): TranscriptPage[] {
    let value: unknown
    try {
        value = JSON.parse(raw ?? '[]')
    } catch {
        return []
    }
    if (!Array.isArray(value)) {
        return []
    }
    return PAGES.filter((page) => value.includes(page))
}

/** The pages with `page` opened or closed, as stored. */
export function withOpen(pages: readonly TranscriptPage[], page: TranscriptPage, open: boolean): string {
    return JSON.stringify(PAGES.filter((p) => (p === page ? open : pages.includes(p))))
}

/** Whether a transcript on a `page` opens its context chart. Re-renders on a change from this tab or another. */
export function useContextChartOpen(page: TranscriptPage): boolean {
    return useSyncExternalStore(subscribe, getSnapshot).includes(page)
}

/** Opens or closes the context chart on every `page`, stores it, and applies it now. */
export function setContextChartOpen(page: TranscriptPage, open: boolean): void {
    const raw = withOpen(snapshot, page, open)
    try {
        globalThis.localStorage.setItem(STORAGE_KEY, raw)
    } catch {
        // Not persisted, but still applied for this page.
    }
    announce(raw)
}

function readRaw(): string | null {
    try {
        return globalThis.localStorage.getItem(STORAGE_KEY)
    } catch {
        // Storage can be unavailable (privacy modes).
        return null
    }
}

let stored = readRaw()
let snapshot = parseOpen(stored)
const listeners = new Set<() => void>()

function announce(raw: string | null): void {
    if (raw === stored) {
        return
    }
    stored = raw
    snapshot = parseOpen(raw)
    for (const listener of listeners) {
        listener()
    }
}

function onStorage(event: StorageEvent): void {
    if (event.key === STORAGE_KEY || event.key === null) {
        announce(readRaw())
    }
}

function subscribe(listener: () => void): () => void {
    listeners.add(listener)
    if (listeners.size === 1) {
        globalThis.addEventListener('storage', onStorage)
        announce(readRaw())
    }
    return () => {
        listeners.delete(listener)
        if (listeners.size === 0) {
            globalThis.removeEventListener('storage', onStorage)
        }
    }
}

function getSnapshot(): readonly TranscriptPage[] {
    return snapshot
}
