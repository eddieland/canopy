import { storedSetting, useStoredSetting } from '@/lib/stored-setting'

/**
 * Which kinds of page open a transcript's context chart (ui/DESIGN.md, "A transcript's context"): its bars and what
 * grew a call, under its one line. Closed until the operator opens it, since a transcript is opened to read what the
 * agent did far more often than to ask why its context grew. Each kind of page keeps its own choice, across reloads:
 * kept in localStorage as Pretty is, and synced across tabs.
 */

/**
 * The pages a transcript sits on, each keeping its own choice: a run's, a chore run's, a task run's, a tick's, and a
 * review's.
 */
export const PAGES = ['run', 'chore-run', 'task-run', 'tick', 'review'] as const

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

/** The pages with `page` opened or closed, in their own order. */
export function withOpen(pages: readonly TranscriptPage[], page: TranscriptPage, open: boolean): TranscriptPage[] {
    return PAGES.filter((p) => (p === page ? open : pages.includes(p)))
}

/** Whether a transcript on a `page` opens its context chart. Re-renders on a change from this tab or another. */
export function useContextChartOpen(page: TranscriptPage): boolean {
    return useStoredSetting(setting).includes(page)
}

/** Opens or closes the context chart on `page`, stores it, and applies it now. */
export function setContextChartOpen(page: TranscriptPage, open: boolean): void {
    setting.set(withOpen(setting.get(), page, open))
}

const setting = storedSetting({ key: STORAGE_KEY, parse: parseOpen, serialize: JSON.stringify })
