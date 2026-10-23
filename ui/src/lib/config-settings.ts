import type { ConfigKey, ConfigSaved, ConfigValue } from '@/api/types'

/**
 * What the settings page's limits and trust form holds before a save, by key: a count's or a pace's text as typed,
 * `capacity.repo_slots`'s text by repository, a switch or choice as picked, and a list's entries kept. A key the
 * operator has not touched is absent.
 */
export type ConfigDrafts = Record<string, string | boolean | string[] | Record<string, string>>

/** The key whose value is a count per repository, which the form shows a field for each. */
export const REPO_SLOTS = 'capacity.repo_slots'

/**
 * Where a key's value comes from, in the page's words. One from the user config is saved to this workspace's own file,
 * where it overrides the user config here alone, so the page says so before the save.
 */
export function sourceText(key: ConfigKey): string {
    switch (key.source) {
        case 'private': {
            return "set in this workspace's config"
        }
        case 'user': {
            return 'from your user config; a change here is for this workspace only'
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
    const parts = [`Saved ${names} to this workspace's config.`]
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

/** One of the limits page's panels: what its keys are about, and each key's name in words. */
export interface ConfigGroup {
    /** The panel's label. */
    title: string
    /** One line under the label on what the keys in it govern. */
    blurb: string
    /** The keys it shows, in order, by name, each with its label in words. */
    keys: { name: string; label: string }[]
}

/**
 * The limits page's panels, in order. A key the server lists that no panel names lands in `Other`, so a key added to
 * the server's allowlist shows before a label is written for it.
 */
export const CONFIG_GROUPS: ConfigGroup[] = [
    {
        title: 'Capacity',
        blurb: 'How much runs at once on this machine, and how many reviews a day.',
        keys: [
            { name: 'capacity.max_workers', label: 'Workers at once' },
            { name: 'capacity.max_chores', label: 'Chore runs at once' },
            { name: 'capacity.max_reviews', label: 'Review runs at once' },
            { name: 'capacity.max_reviews_per_day', label: 'Reviews a day' },
        ],
    },
    {
        title: 'Pools',
        blurb: "Each repository's worktree slots. canopy workspace sync makes or removes them; leases follow at once.",
        keys: [
            { name: 'capacity.slots_per_repo', label: 'Slots per repository' },
            { name: REPO_SLOTS, label: 'Repositories with a count of their own' },
        ],
    },
    {
        title: 'Attempts',
        blurb: 'How many runs a ticket or PR gets before it waits for you, and the pause before a resume for red CI.',
        keys: [
            { name: 'policy.max_implement_attempts', label: 'Implement runs per unit' },
            { name: 'policy.max_resume_attempts', label: 'Resume runs per unit' },
            { name: 'policy.max_reviews_per_pr', label: 'Review runs per PR' },
            { name: 'policy.ci_cooldown_minutes', label: 'Minutes before a resume for red CI' },
        ],
    },
    {
        title: 'Attachments',
        blurb: 'How much text you may attach to one ticket or task. Each of its runs gets every file.',
        keys: [
            { name: 'policy.max_attachments', label: 'Files per ticket or task' },
            { name: 'policy.max_attachment_kib', label: 'KiB per file' },
            { name: 'policy.max_attachments_total_kib', label: 'KiB per ticket or task' },
        ],
    },
    {
        title: 'Pace',
        blurb: "How often the loop ticks, which is most of the overseer's spend.",
        keys: [
            { name: 'loop.interval_minutes', label: 'Minutes between ticks' },
            { name: 'loop.idle_max_minutes', label: 'Longest wait when idle, in minutes' },
        ],
    },
    {
        title: 'Budget',
        blurb:
            'What a month of agent runs should cost. Nothing stops at it: the spend page tracks it, and a sink ' +
            'that takes loop events hears once the month reaches it.',
        keys: [{ name: 'spend.monthly_budget_usd', label: 'Monthly budget, in US dollars' }],
    },
    {
        title: 'Trust',
        blurb: 'Only stricter from here: loosening one, or adding a name, is an edit to the file.',
        keys: [
            { name: 'policy.stacking', label: 'Never stack a branch on another' },
            { name: 'trust.authorized_repliers', label: 'Who may answer a worker' },
            { name: 'trust.trusted_reviewers', label: 'Whose review a worker acts on unasked' },
            { name: 'trust.rebase', label: 'Workers rebase and push with a lease' },
            { name: 'trust.commit_trailer', label: 'Workers add a Co-authored-by trailer' },
        ],
    },
]

/** A key the server listed, with its label from `CONFIG_GROUPS`, or its name when no panel names it. */
export interface LabelledKey {
    /** The key as the server sent it. */
    setting: ConfigKey
    /** Its name in words. */
    label: string
}

/**
 * The server's keys, by `CONFIG_GROUPS`'s panels: each panel with the keys it names that the server sent, then
 * `Other` with any it sent that no panel names. A panel left with no key is dropped.
 */
export function groupedKeys(keys: ConfigKey[]): { group: ConfigGroup; keys: LabelledKey[] }[] {
    const byName = new Map(keys.map((k) => [k.name, k]))
    const placed = new Set<string>()
    const found: { group: ConfigGroup; keys: LabelledKey[] }[] = []
    for (const group of CONFIG_GROUPS) {
        const shown: LabelledKey[] = []
        for (const { name, label } of group.keys) {
            const setting = byName.get(name)
            if (setting !== undefined) {
                shown.push({ setting, label })
                placed.add(name)
            }
        }
        if (shown.length > 0) {
            found.push({ group, keys: shown })
        }
    }
    const rest = keys.filter((k) => !placed.has(k.name)).map((setting) => ({ setting, label: setting.name }))
    if (rest.length > 0) {
        found.push({ group: { title: 'Other', blurb: 'Keys this page has no words for yet.', keys: [] }, keys: rest })
    }
    return found
}

/** How many keys a save would change, in words for the save bar. */
export function pendingText(count: number): string {
    if (count === 0) {
        return 'No unsaved changes'
    }
    return count === 1 ? '1 unsaved change' : `${count} unsaved changes`
}
