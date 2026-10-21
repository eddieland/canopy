import type { PersonaList } from '@/api/types'
import { storedSetting, useStoredSetting } from '@/lib/stored-setting'

/**
 * The personas the operator prefers for a review they request on the reviews page (`ReviewRequestForm`): the form
 * starts from them, and a request names them as `--persona NAME` does. None leaves it to `[personas] reviewer` in the
 * config. This is the operator's own, apart from the config: kept in localStorage like the theme, and synced across
 * tabs.
 */

/** Where localStorage keeps the setting, as a JSON list of names. */
export const STORAGE_KEY = 'canopy-review-personas'
/** The most personas one request names, as the server bounds them: a review in each is a run in each. */
export const MAX_PERSONAS = 10

/** The setting from its stored JSON: each name once, in order, at most `MAX_PERSONAS`; none for anything else. */
export function parseReviewPersonas(raw: string | null): readonly string[] {
    let stored: unknown = null
    try {
        stored = raw === null ? null : JSON.parse(raw)
    } catch {
        // Not JSON: none.
    }
    if (!Array.isArray(stored)) {
        return []
    }
    const names = stored.filter((name): name is string => typeof name === 'string' && name !== '')
    return [...new Set(names)].slice(0, MAX_PERSONAS)
}

/**
 * The preferred personas a request may name now: those `personas` lists that canopy would run, in the order
 * preferred. A persona since removed, or one canopy would refuse, is left out rather than refused. All of them while
 * the list is still being read.
 */
export function usablePersonas(preferred: readonly string[], personas: PersonaList | undefined): readonly string[] {
    if (personas === undefined) {
        return preferred
    }
    const runnable = new Set(personas.personas.filter((p) => p.error === null).map((p) => p.name))
    return preferred.filter((name) => runnable.has(name))
}

/** The preferred personas. Re-renders on a change from this tab or another. */
export function useReviewPersonas(): readonly string[] {
    return useStoredSetting(setting)
}

/** Stores the preferred personas and applies them now; none goes back to the config's reviewer. */
export function setReviewPersonas(next: readonly string[]): void {
    setting.set(next)
}

const setting = storedSetting({ key: STORAGE_KEY, parse: parseReviewPersonas, serialize: JSON.stringify })
