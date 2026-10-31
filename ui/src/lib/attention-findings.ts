import type { AttentionItem } from '@/api/types'
import { storedSetting, useStoredSetting } from '@/lib/stored-setting'

/**
 * Whether the attention list shows chores' findings (`useAttention`): its page, its counter, and the nav's badge.
 * Shown until the operator hides them; a chore's own page lists its findings either way. Kept in localStorage like the
 * send key, and synced across tabs. Only this browser reads it: the CLI's `canopy status` and the loop never do.
 */

/** Where localStorage keeps the setting: `hide` once the operator hides findings, absent or anything else to show. */
export const STORAGE_KEY = 'canopy-attention-findings'

/** Whether findings are hidden, from what is stored: shown for anything but `hide`. */
export function parseHidden(raw: string | null): boolean {
    return raw === 'hide'
}

/** The items without chores' findings. */
export function withoutFindings(items: AttentionItem[]): AttentionItem[] {
    return items.filter((item) => !item.finding)
}

/** Whether the attention list hides chores' findings. Re-renders on a change from this tab or another. */
export function useFindingsHidden(): boolean {
    return useStoredSetting(setting)
}

/** Hides or shows chores' findings on the attention list, stores it, and applies it now. */
export function setFindingsHidden(hidden: boolean): void {
    setting.set(hidden)
}

const setting = storedSetting({
    key: STORAGE_KEY,
    parse: parseHidden,
    serialize: (hidden: boolean) => (hidden ? 'hide' : 'show'),
})
