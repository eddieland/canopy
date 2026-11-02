import { storedSetting, useStoredSetting } from '@/lib/stored-setting'

/**
 * How large a plan's text is set (`.plan-doc` in src/index.css): two steps down from a document's type, one step down,
 * the document's own (`document-text`), or a step up, its headings moving with it. A plan in its editor and a task's
 * report follow it; the guide keeps the document's size. Kept in localStorage like the theme, and synced across tabs.
 */

/** A plan's text size: two steps down from a document's, one step down, a document's own, or a step up. */
export type PlanText = 'tiny' | 'small' | 'normal' | 'large'

/** Where localStorage keeps the setting. */
export const STORAGE_KEY = 'canopy-plan-text'
/** The setting until the operator picks one: a document's own size, as the guide reads. */
export const DEFAULT: PlanText = 'normal'

const SIZES = new Set<string>(['tiny', 'small', 'normal', 'large'])

/** The setting as stored, or the default for anything it does not recognize. */
export function parsePlanText(raw: string | null): PlanText {
    return raw !== null && SIZES.has(raw) ? (raw as PlanText) : DEFAULT
}

const setting = storedSetting({ key: STORAGE_KEY, parse: parsePlanText, serialize: (value: PlanText) => value })

/** A plan's text size. Re-renders on a change from this tab or another. */
export function usePlanText(): PlanText {
    return useStoredSetting(setting)
}

/** Stores the setting and applies it now. */
export function setPlanText(next: PlanText): void {
    setting.set(next)
}
