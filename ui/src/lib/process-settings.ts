import type { ProcessOrder } from '@/lib/processes'
import { storedSetting, useStoredSetting } from '@/lib/stored-setting'

/**
 * How the system resources page's process tree was left: every process or the busy ones, which column orders it, and
 * which processes are folded. Kept in localStorage like a list's order, so leaving the page and coming back finds the
 * tree as it was, and synced across tabs. Only the latest `MAX_FOLDED` folds are kept: a process's id outlives the
 * process only as a number some later process may take, so an old fold is let go rather than kept for ever.
 */

/** Where localStorage keeps it, as JSON. */
export const STORAGE_KEY = 'canopy-processes'

/** How many folded processes are kept: folding one more lets go of the one folded longest ago. */
export const MAX_FOLDED = 50

/** The tree as the operator left it. */
export interface ProcessSettings {
    /** Whether every process shows, not only the busy ones under the loop and elsewhere. */
    all: boolean
    /** Which column orders each list of siblings. */
    order: ProcessOrder
    /** The processes folded, by pid, the latest last. */
    folded: number[]
}

const DEFAULTS: ProcessSettings = { all: false, order: 'cpu', folded: [] }

/** The settings as stored, each one read alone: one stored otherwise is its default. */
export function parseProcessSettings(raw: string | null): ProcessSettings {
    let value: unknown
    try {
        value = JSON.parse(raw ?? '{}')
    } catch {
        return DEFAULTS
    }
    if (typeof value !== 'object' || value === null) {
        return DEFAULTS
    }
    const { all, order, folded } = value as Record<string, unknown>
    return {
        all: all === true,
        order: order === 'memory' ? 'memory' : 'cpu',
        folded: Array.isArray(folded)
            ? folded.filter((pid): pid is number => Number.isSafeInteger(pid) && pid > 0).slice(-MAX_FOLDED)
            : [],
    }
}

/** `folded` with `pid` folded or unfolded: folding moves it to the end, and the oldest past `MAX_FOLDED` go. */
export function withFold(folded: readonly number[], pid: number, fold: boolean): number[] {
    const rest = folded.filter((p) => p !== pid)
    return fold ? [...rest, pid].slice(-MAX_FOLDED) : rest
}

/** The tree as the operator left it. Re-renders on a change from this tab or another. */
export function useProcessSettings(): ProcessSettings {
    return useStoredSetting(setting)
}

/** Changes what `change` names, stores it, and applies it now. */
export function setProcessSettings(change: Partial<ProcessSettings>): void {
    setting.set({ ...setting.get(), ...change })
}

const setting = storedSetting({ key: STORAGE_KEY, parse: parseProcessSettings, serialize: JSON.stringify })
