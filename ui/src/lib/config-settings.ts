import type { ConfigKey, ConfigSaved, ConfigValue } from '@/api/types'

/**
 * What the settings page's limits and trust form holds before a save, by key: a count's or a pace's text as typed,
 * `capacity.repo_slots`'s text by repository, a switch or choice as picked, and a list's entries kept. A key the
 * operator has not touched is absent.
 */
export type ConfigDrafts = Record<string, string | boolean | string[] | Record<string, string>>

/** The key whose value is a count per repository, which the form shows a field for each. */
export const REPO_SLOTS = 'capacity.repo_slots'

/** Where a key's value comes from, in the page's words. */
export function sourceText(key: ConfigKey): string {
    switch (key.source) {
        case 'user': {
            return 'set in your config'
        }
        case 'workspace': {
            return 'set in the workspace file'
        }
        case 'default': {
            return 'default'
        }
    }
}

/** How far the page may take a limit, or that a trust setting only gets stricter. */
export function boundText(key: ConfigKey): string {
    if (key.kind === 'stricter') {
        return 'stricter only'
    }
    if (key.bound === null) {
        return ''
    }
    return key.looser === 'lower' ? `at least ${key.bound} from here` : `at most ${key.bound} from here`
}

/** What a save would send, and the fields whose text is not a whole number, which keep it from being sent. */
export interface ConfigForm {
    /** Each touched key whose value differs from the one read. */
    changes: Record<string, ConfigValue>
    /** The keys, and `capacity.repo_slots.<repo>` entries, typed as something other than a whole number. */
    invalid: string[]
}

/**
 * The changes a save sends: each touched key whose value differs from the one read. `capacity.repo_slots` sends only
 * the repositories whose count changed, and a list the entries kept. A count left empty changes nothing; one that is
 * not a whole number is named in `invalid`. The server checks the rest: bounds, and what the loader refuses.
 */
export function configForm(keys: ConfigKey[], drafts: ConfigDrafts): ConfigForm {
    const changes: Record<string, ConfigValue> = {}
    const invalid: string[] = []
    for (const key of keys) {
        const draft = drafts[key.name]
        if (draft === undefined) {
            continue
        }
        if (key.kind === 'stricter' && !Array.isArray(draft)) {
            // A switch, or `policy.stacking`'s choice: sent as picked.
            if (draft !== key.value) {
                changes[key.name] = draft as ConfigValue
            }
        } else if (typeof draft === 'object' && !Array.isArray(draft)) {
            const was =
                typeof key.value === 'object' && key.value !== null && !Array.isArray(key.value) ? key.value : {}
            const slots: Record<string, number> = {}
            for (const [repo, text] of Object.entries(draft)) {
                const count = wholeNumber(text, was[repo] ?? null)
                if (count === 'invalid') {
                    invalid.push(`${key.name}.${repo}`)
                } else if (count !== null) {
                    slots[repo] = count
                }
            }
            if (Object.keys(slots).length > 0) {
                changes[key.name] = slots
            }
        } else if (typeof draft === 'string') {
            const count = wholeNumber(draft, typeof key.value === 'number' ? key.value : null)
            if (count === 'invalid') {
                invalid.push(key.name)
            } else if (count !== null) {
                changes[key.name] = count
            }
        } else if (Array.isArray(draft)) {
            const was = Array.isArray(key.value) ? key.value : []
            if (draft.length !== was.length) {
                changes[key.name] = draft
            }
        }
    }
    return { changes, invalid }
}

/** The count `text` holds when it differs from `was`; null when empty or the same; `invalid` when not a number. */
function wholeNumber(text: string, was: number | null): number | 'invalid' | null {
    const typed = text.trim()
    if (typed === '') {
        return null
    }
    if (!/^\d+$/u.test(typed)) {
        return 'invalid'
    }
    const count = Number(typed)
    return count === was ? null : count
}

/**
 * What a save did, apart from what its reload found: the keys written, when the loop runs on them, that a run already
 * running keeps what it started with, and that `--every` still sets the pace.
 */
export function savedText(saved: ConfigSaved): string {
    if (saved.changed.length === 0) {
        return 'Nothing changed: each setting already had that value, and nothing was written.'
    }
    const names = saved.changed.map((c) => c.name).join(', ')
    const parts = [`Saved ${names} to your config.`]
    if (saved.reload !== null) {
        parts.push(
            saved.reload.after_tick
                ? 'The loop reads it once the running tick ends.'
                : 'The loop runs on it from now on.',
        )
    } else if (saved.reload_refused !== null) {
        parts.push(`The reload was refused (${saved.reload_refused}); the save takes effect at the next reload.`)
    }
    parts.push('A run already running keeps the prompt and permissions it started with.')
    if (saved.every !== null && saved.changed.some((c) => c.name === 'loop.interval_minutes')) {
        parts.push(`--every ${saved.every} still sets the pace until the loop restarts.`)
    }
    return parts.join(' ')
}
