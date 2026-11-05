import type { ConfigKey, ConfigSaved, ConfigValue } from '@/api/types'

/**
 * What the Loop settings form holds before a save, by key: a count's or a pace's text as typed,
 * `capacity.repo_slots`'s text by repository, a switch or choice as picked, and a list's entries kept. A key the
 * operator has not touched is absent.
 */
export type ConfigDrafts = Record<string, string | boolean | string[] | Record<string, string>>

/** The key whose value is a count per repository, which the form shows a field for each. */
export const REPO_SLOTS = 'capacity.repo_slots'

/** Every place a key's value can come from, nearest first. */
const SOURCES: ConfigKey['source'][] = ['private', 'user', 'workspace', 'default']

/** Where a key's value comes from, as each row's chip names it: short, since every row has one. */
export const SOURCE_WORD: Record<ConfigKey['source'], string> = {
    private: 'this workspace',
    user: 'user',
    workspace: 'workspace',
    default: 'default',
}

/**
 * What each source's chip means, for its tip and the page's help. One from the user config is saved to this
 * workspace's own file, where it overrides the user config here alone, so the chip's tip says so before the save.
 */
export const SOURCE_MEANING: Record<ConfigKey['source'], string> = {
    private: "set in this workspace's own config, the file a save writes",
    user: 'from your user config, which serves every workspace; a change here is saved for this workspace only',
    workspace: 'set in the shared workspace file, which the page never writes',
    default: "set in no file: canopy's default",
}

/** What each row's chip means, said once, for the page's help: each source's word and its meaning. */
export const SOURCES_HELP = `Each row's chip says where its value comes from: ${SOURCES.map(
    (source) => `${SOURCE_WORD[source]}, ${SOURCE_MEANING[source]}`,
).join('; ')}.`

/**
 * What Loop settings shows the same on every visit, for its title's help: where a save goes and what it keeps, how far
 * each kind of key moves, and what each row's chip means.
 */
export const LIMITS_HELP =
    "What the loop runs, spends, polls, and keeps, and whose words it acts on. A save writes this workspace's own " +
    'config, keeping its comments, with the old file beside it as config.toml.bak, then reloads the loop; your user ' +
    'config is never changed. Limits and retentions move within their bounds; trust settings only get stricter; ' +
    `anything else is an edit to the file. ${SOURCES_HELP}`

/**
 * Loop settings' description, one line of its state: how many settings it shows, how many this workspace sets, and how
 * many come from the user config, each left out at none.
 */
export function settingsLine(keys: ConfigKey[]): string {
    const set = keys.filter((k) => k.source === 'private').length
    const user = keys.filter((k) => k.source === 'user').length
    return [
        `${keys.length} ${keys.length === 1 ? 'setting' : 'settings'}`,
        set > 0 ? `${set} set in this workspace` : null,
        user > 0 ? `${user} from your user config` : null,
    ]
        .filter(Boolean)
        .join(' · ')
}

/** The trust switches, and the side the page may move each to: the stricter one (TRUST_MODEL T8). */
export const STRICTER_ON: Record<string, boolean> = { 'trust.rebase': false, 'trust.commit_trailer': true }

/** What each trust switch turns on, named for its checkbox: the behavior, never `on`. */
export const SWITCH_NAME: Record<string, string> = { 'trust.rebase': 'rebase', 'trust.commit_trailer': 'add trailer' }

/**
 * Whether a key that only gets stricter is at its strictest already, so the page can take it no further: a choice at
 * its last, a switch on its stricter side, a list with no entry left, or a count at 0.
 */
export function strictest(key: ConfigKey): boolean {
    if (key.kind !== 'stricter') {
        return false
    }
    const { value } = key
    if (key.choices.length > 0) {
        return value === key.choices.at(-1)
    }
    if (typeof value === 'boolean') {
        return value === STRICTER_ON[key.name]
    }
    if (Array.isArray(value)) {
        return value.length === 0
    }
    return value === 0
}

/** A key at its strictest, in words for its locked readout: a switch by what it does, `rebase off`. */
export function lockedText(key: ConfigKey): string {
    const { name, value } = key
    if (typeof value === 'boolean') {
        return `${SWITCH_NAME[name] ?? name} ${value ? 'on' : 'off'}`
    }
    return valueText(value, name)
}

/**
 * Whether dropping `entry` from stricter list `key`, which keeps `kept` now, asks first: any authorized replier, since
 * the page does not know which login is the operator's and losing it ends the reply path, and a list's last entry.
 * Only an edit to the file adds either back.
 */
export function dropAsks(key: ConfigKey, entry: string, kept: readonly string[]): boolean {
    return key.name === 'trust.authorized_repliers' || (kept.length === 1 && kept[0] === entry)
}

/** A key's default in words for its row, `default 2`, once its value is not the default; null while it is. */
export function defaultText(key: ConfigKey): string | null {
    return sameValue(key.value, key.default) ? null : `default ${valueText(key.default, key.name)}`
}

/**
 * What a reset types into key's field, its default as the form holds it, for a key whose value is not its default;
 * null when the page cannot take it there: a default that unsets the key (an unmanaged pool, no budget) or removes a
 * repository's own count, a limit's default past its bound from the value now, a stricter key's default looser than
 * its value now, which only the file may set, or a list's default that drops an entry the page asks about first. A
 * reset is an ordinary change, saved as any other.
 */
export function resetDraft(key: ConfigKey): ConfigDrafts[string] | null {
    const { value, default: to } = key
    if (sameValue(value, to) || to === null || (typeof to === 'object' && !Array.isArray(to))) {
        return null
    }
    if (Array.isArray(to)) {
        const entries = to.map(String)
        if (key.kind === 'free') {
            return entries.join(', ')
        }
        // A stricter list only loses entries: back to its default only if every default entry is still there, and
        // never by dropping one the page asks about first (`dropAsks`), which stays the operator's own uncheck.
        const now = Array.isArray(value) ? value.map(String) : []
        const dropped = now.filter((e) => !entries.includes(e))
        const asks = entries.length === 0 || dropped.some((e) => dropAsks(key, e, now))
        return entries.every((e) => now.includes(e)) && !asks ? entries : null
    }
    if (typeof to === 'boolean') {
        return key.kind !== 'stricter' || to === STRICTER_ON[key.name] ? to : null
    }
    if (typeof to === 'string') {
        // A choice moves only later, toward stricter.
        const now = typeof value === 'string' ? key.choices.indexOf(value) : -1
        return key.choices.indexOf(to) >= now ? to : null
    }
    const was = typeof value === 'number' ? value : null
    if (key.kind === 'stricter') {
        return was === null || to <= was ? String(to) : null
    }
    return pastText(key, was, to) === null ? String(to) : null
}

/** Whether the form's `changes` already take key back to its default, so its reset has nothing left to do. */
export function resetDone(key: ConfigKey, changes: Record<string, ConfigValue>): boolean {
    const now = changes[key.name]
    return now !== undefined && sameValue(now, key.default)
}

/** Whether two values are the same, entry for entry. */
function sameValue(a: ConfigValue, b: ConfigValue): boolean {
    return JSON.stringify(a) === JSON.stringify(b)
}

/** How far the page may take a limit, or that a trust setting only gets stricter. */
export function boundText(key: ConfigKey): string {
    if (key.kind === 'stricter') {
        return typeof key.value === 'number' ? 'only fewer from here' : 'stricter only'
    }
    if (key.kind === 'free') {
        return 'percentages, comma separated; 100% is always sent'
    }
    if (key.bound === null) {
        return ''
    }
    if (key.forever_at_zero) {
        return `at least ${key.bound}, or 0 for forever, from here`
    }
    if (key.looser === 'lower') {
        // A floor of 0 bounds nothing the loader does not.
        return key.bound === 0 ? '' : `at least ${key.bound} from here`
    }
    return `at most ${key.bound} from here`
}

/** What a save would send, and the fields whose text the page would not send, which keep it from being sent. */
export interface ConfigForm {
    /** Each touched key whose value differs from the one read. */
    changes: Record<string, ConfigValue>
    /**
     * Each field the page would not send, by its name (a key, or `capacity.repo_slots.<repo>`), with why: not a whole
     * number, or past how far the page may take it.
     */
    errors: Record<string, string>
}

/**
 * The changes a save sends: each touched key whose value differs from the one read. `capacity.repo_slots` sends only
 * the repositories whose count changed, and a list the entries kept. A count left empty changes nothing when the file
 * sets none, and is named in `errors` when it does, as is a repository picked and left empty. A count that is not a
 * whole number, or that the server would refuse as past its bound, is named in `errors` with why, as the server checks
 * it: a limit past its bound and looser than the value read, or a stricter count raised. The server checks again on
 * save, and checks what the loader refuses.
 */
export function configForm(keys: ConfigKey[], drafts: ConfigDrafts): ConfigForm {
    const changes: Record<string, ConfigValue> = {}
    const errors: Record<string, string> = {}
    const perRepo = keys.find((k) => k.name === 'capacity.slots_per_repo')?.value
    for (const key of keys) {
        const draft = drafts[key.name]
        if (draft === undefined) {
            continue
        }
        if (key.kind === 'free' && typeof draft === 'string') {
            // The budget's alerts, typed as a list: sent whole, the loader checking each.
            const percents = wholeNumbers(draft)
            if (percents === 'invalid') {
                errors[key.name] = 'whole percentages, comma separated'
            } else if (!sameNumbers(percents, key.value)) {
                changes[key.name] = percents
            }
            continue
        }
        if (key.kind === 'stricter' && (typeof draft === 'boolean' || key.choices.length > 0)) {
            // A switch, or a choice such as `policy.stacking`'s: sent as picked.
            if (draft !== key.value) {
                changes[key.name] = draft as ConfigValue
            }
        } else if (typeof draft === 'object' && !Array.isArray(draft)) {
            const was =
                typeof key.value === 'object' && key.value !== null && !Array.isArray(key.value) ? key.value : {}
            const slots: Record<string, number> = {}
            for (const [repo, text] of Object.entries(draft)) {
                // A repository with no count of its own has the slots per repository, as the server reads it.
                const before = was[repo] ?? (typeof perRepo === 'number' ? perRepo : null)
                const count = wholeNumber(text, was[repo] ?? null)
                // A repository just picked has no count of its own yet: empty, it is a draft to type or discard.
                const error = countError(key, text, was[repo] ?? null, before, count, true)
                if (error !== null) {
                    errors[`${key.name}.${repo}`] = error
                } else if (typeof count === 'number') {
                    slots[repo] = count
                }
            }
            if (Object.keys(slots).length > 0) {
                changes[key.name] = slots
            }
        } else if (typeof draft === 'string') {
            const was = typeof key.value === 'number' ? key.value : null
            const count = wholeNumber(draft, was)
            const error = countError(key, draft, was, was, count, false)
            if (error !== null) {
                errors[key.name] = error
            } else if (typeof count === 'number') {
                changes[key.name] = count
            }
        } else if (Array.isArray(draft)) {
            const was = Array.isArray(key.value) ? key.value : []
            if (draft.length !== was.length) {
                changes[key.name] = draft
            }
        }
    }
    return { changes, errors }
}

/**
 * Why a count's field, typed as `text` and read as `count`, holds what the page would not send: not a whole number,
 * empty where the field was added to be typed in (`added`, a repository just picked) or emptied of a value the file
 * sets (which the page cannot unset), either of which would otherwise leave a blank field with nothing to save or
 * discard, or past how far the page may take it from `before`, the value the server checks from. Null when the
 * server would take it, or when nothing changed.
 */
function countError(
    key: ConfigKey,
    text: string,
    was: number | null,
    before: number | null,
    count: number | 'invalid' | null,
    added: boolean,
): string | null {
    if (count === 'invalid') {
        return 'not a whole number'
    }
    if (count === null) {
        if (text.trim() !== '') {
            return null
        }
        if (was !== null) {
            return `empty: type a count, or Discard to keep ${was}`
        }
        return added ? 'empty: type a count, or Discard' : null
    }
    return pastText(key, before, count)
}

/**
 * Why the page would not send `now` for `key`, whose value read was `was`, as the server's own check (`_past` and
 * `_stricter` in `canopy/serve/config_edit.py`) refuses it; null when the server would take it. A limit is refused
 * only past its bound and looser than `was`, so a value the file set past the bound stays as it is.
 */
function pastText(key: ConfigKey, was: number | null, now: number): string | null {
    if (key.kind === 'stricter') {
        return was !== null && now > was ? `only fewer from here: at most ${was}; set more in the file` : null
    }
    if (key.kind !== 'limit' || key.bound === null) {
        return null
    }
    const { bound } = key
    if (key.looser === 'higher') {
        return now > bound && (was === null || now > was) ? `at most ${bound} from here; set more in the file` : null
    }
    if (key.forever_at_zero) {
        // Forever is the strictest: always allowed, and any count of days looser than it.
        return now !== 0 && now < bound && (was === null || was === 0 || now < was)
            ? `at least ${bound}, or 0 for forever, from here; set less in the file`
            : null
    }
    return now < bound && (was === null || now < was) ? `at least ${bound} from here; set less in the file` : null
}

/** The whole numbers `text` lists, split on commas and spaces; none when empty; `invalid` when one is not a number. */
function wholeNumbers(text: string): number[] | 'invalid' {
    const parts = text.split(/[\s,]+/u).filter((part) => part !== '')
    return parts.every((part) => /^\d+$/u.test(part)) ? parts.map(Number) : 'invalid'
}

/** Whether `numbers` is the value read, entry for entry, in order. */
function sameNumbers(numbers: number[], was: ConfigValue): boolean {
    return Array.isArray(was) && was.length === numbers.length && numbers.every((n, i) => was[i] === n)
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

/** One change a save would make, for the save bar: a key, or one repository's own count, from the value read. */
export interface ConfigChange {
    /** The key, or `capacity.repo_slots.<repo>`. */
    name: string
    /** Its value read, in words. */
    old: string
    /** The value a save would write, in words. */
    new: string
}

/**
 * Each change a save would make, in the order the server lists the keys, for the save bar to list as `key: old → new`
 * and count. `capacity.repo_slots` lists each repository whose count changed on its own, from the count it has now: its
 * own, else the slots per repository.
 */
export function changeList(keys: ConfigKey[], changes: Record<string, ConfigValue>): ConfigChange[] {
    const found: ConfigChange[] = []
    // A repository with no count of its own has the slots per repository, as the server reads it.
    const perRepo = keys.find((k) => k.name === 'capacity.slots_per_repo')?.value
    for (const key of keys) {
        const now = changes[key.name]
        if (now === undefined) {
            continue
        }
        if (typeof now === 'object' && now !== null && !Array.isArray(now)) {
            const was =
                typeof key.value === 'object' && key.value !== null && !Array.isArray(key.value) ? key.value : {}
            for (const [repo, count] of Object.entries(now)) {
                found.push({
                    name: `${key.name}.${repo}`,
                    old: valueText(was[repo] ?? (typeof perRepo === 'number' ? perRepo : null), key.name),
                    new: String(count),
                })
            }
        } else {
            found.push({ name: key.name, old: valueText(key.value, key.name), new: valueText(now, key.name) })
        }
    }
    return found
}

/**
 * The keys a save would change that only get stricter from the page: ones only an edit to the file undoes, so the save
 * bar says so before the save.
 */
export function oneWay(keys: ConfigKey[], changes: Record<string, ConfigValue>): string[] {
    return keys.filter((k) => k.kind === 'stricter' && k.name in changes).map((k) => k.name)
}

/** What the save bar says of the stricter keys a save would change, `names`: that only the file undoes them. */
export function oneWayText(names: string[]): string {
    return `${names.join(', ')}: only an edit to config.toml undoes ${names.length === 1 ? 'this' : 'these'}`
}

/** What an unset key is, in words: an unmanaged pool for the pools' counts, no budget for the budget. */
export function unsetText(name: string): string {
    return name === 'spend.monthly_budget_usd' ? 'none' : 'unmanaged'
}

/** Key `name`'s value in words: a count or a choice as it is, a switch on or off, a list's entries, or unset. */
export function valueText(value: ConfigValue, name: string): string {
    if (value === null) {
        return unsetText(name)
    }
    if (typeof value === 'boolean') {
        return value ? 'on' : 'off'
    }
    if (Array.isArray(value)) {
        return value.length === 0 ? 'none' : value.join(', ')
    }
    if (typeof value === 'object') {
        const counts = Object.entries(value)
        return counts.length === 0 ? 'none' : counts.map(([repo, n]) => `${repo} ${n}`).join(', ')
    }
    return String(value)
}

/** One of the Loop settings page's bands: what its keys are about, and each key's name in words. */
export interface ConfigGroup {
    /** The band's label. */
    title: string
    /** One line under the label on what the keys in it govern. */
    blurb: string
    /**
     * Whether its keys only get stricter from the page: the band's header says so once, with a lock, instead of each
     * row.
     */
    oneWay?: boolean
    /**
     * The keys it shows, in order, by name, each with its label in words, the unit its field is in, and the part of the
     * band it heads, if the band is in labelled parts: a key with a `part` starts that part, and the keys after it are
     * in it.
     */
    keys: { name: string; label: string; unit?: string; part?: string }[]
}

/**
 * The Loop settings page's bands, in order. A key the server lists that no band names lands in `Other`, so a key
 * added to the server's allowlist shows before a label is written for it.
 */
export const CONFIG_GROUPS: ConfigGroup[] = [
    {
        title: 'Capacity',
        blurb: "What runs at once on this machine, each pool's worktree slots, and what one ticket may attach.",
        keys: [
            { name: 'capacity.max_workers', label: 'Workers at once' },
            { name: 'capacity.max_chores', label: 'Chore runs at once' },
            { name: 'capacity.max_reviews', label: 'Review runs at once' },
            { name: 'capacity.max_tasks', label: 'Task runs at once' },
            { name: 'capacity.max_reviews_per_day', label: 'Reviews a day' },
            { name: 'loop.min_free_disk_mib', label: 'Free disk a tick needs to dispatch', unit: 'MiB' },
            { name: 'capacity.slots_per_repo', label: 'Slots per repository' },
            { name: REPO_SLOTS, label: 'Repositories with a count of their own' },
            { name: 'policy.max_attachments', label: 'Files attached per ticket or task' },
            { name: 'policy.max_attachment_kib', label: 'Size of one attached file', unit: 'KiB' },
            { name: 'policy.max_attachments_total_kib', label: 'Attached to one ticket or task in all', unit: 'KiB' },
        ],
    },
    {
        title: 'Attempts',
        blurb: 'How many runs a ticket, PR, or draft gets before it waits for you, and what one run or epic may hold.',
        keys: [
            { name: 'policy.max_implement_attempts', label: 'Implement runs per unit' },
            { name: 'policy.max_resume_attempts', label: 'Resume runs per unit' },
            { name: 'policy.max_plan_attempts', label: 'Plan runs per ticket' },
            { name: 'policy.max_feedback_plan_attempts', label: 'Feedback plan runs per unit' },
            { name: 'policy.max_reviews_per_pr', label: 'Review runs per PR' },
            { name: 'policy.max_revisions_per_draft', label: "Revisions of a review's draft" },
            { name: 'policy.max_follow_ups', label: 'Follow-up tickets from one run' },
            { name: 'policy.max_epic_tickets', label: 'Tickets in one epic' },
        ],
    },
    {
        title: 'Timing',
        blurb: 'How often the loop ticks and looks around, how long it holds off, and how long a run may take.',
        keys: [
            { name: 'loop.interval_minutes', label: 'Time between ticks', unit: 'min', part: 'Pace' },
            { name: 'loop.idle_max_minutes', label: 'Longest wait when idle', unit: 'min' },
            { name: 'loop.min_gap_minutes', label: 'Shortest gap between two ticks', unit: 'min' },
            { name: 'tracker.query_every_minutes', label: 'Shortest gap between tracker queries', unit: 'min' },
            { name: 'connect.every_minutes', label: 'Time between connector polls', unit: 'min' },
            { name: 'connect.max_age_minutes', label: 'Age at which an observation is stale', unit: 'min' },
            {
                name: 'policy.ci_cooldown_minutes',
                label: 'Wait after red CI before a resume',
                unit: 'min',
                part: 'Waits',
            },
            { name: 'policy.feedback_quiet_minutes', label: 'Wait for quiet before a feedback plan', unit: 'min' },
            { name: 'policy.feedback_ci_wait_minutes', label: 'Wait on pending checks before feedback', unit: 'min' },
            { name: 'review.settle_minutes', label: "Wait for a PR's head to settle before its review", unit: 'min' },
            { name: 'runtime.worker_timeout_minutes', label: 'Worker run', unit: 'min', part: 'Timeouts' },
            { name: 'runtime.review_timeout_minutes', label: 'Review run', unit: 'min' },
            { name: 'runtime.overseer_timeout_minutes', label: 'Overseer tick', unit: 'min' },
            { name: 'runtime.setup_timeout_minutes', label: "A slot's setup command", unit: 'min' },
        ],
    },
    {
        title: 'Retention & budget',
        blurb: 'How long canopy keeps its own history, 0 for forever, and what a month of agent runs should cost.',
        keys: [
            { name: 'retention.run_files_days', label: "Keep a run's log, prompt, and diff", unit: 'days' },
            { name: 'retention.tick_files_days', label: "Keep a tick's log and prompt", unit: 'days' },
            { name: 'retention.journal_days', label: "Keep the journal's old rows", unit: 'days' },
            { name: 'retention.memory_days', label: 'Keep a retired note or proposal', unit: 'days' },
            { name: 'spend.monthly_budget_usd', label: 'Monthly budget', unit: '$' },
            { name: 'spend.budget_alerts', label: 'Also alert at these shares of the budget', unit: '%' },
        ],
    },
    {
        title: 'Guardrails',
        blurb: 'Which work waits on a plan you approve, and whose words workers act on.',
        oneWay: true,
        keys: [
            { name: 'policy.plan', label: 'Before a ticket is implemented' },
            { name: 'policy.feedback_plan', label: 'Before a resume acts on review feedback' },
            { name: 'policy.planner_may_approve', label: 'How readily a planner may approve its own plan' },
            { name: 'policy.stacking', label: 'Stack a branch on its blocker' },
            { name: 'trust.authorized_repliers', label: 'Who may answer a worker' },
            { name: 'trust.trusted_reviewers', label: 'Whose review a worker acts on unasked' },
            { name: 'trust.review_replies', label: 'Workers post their replies, or draft them for you' },
            { name: 'trust.rebase', label: 'Workers rebase and push with a lease' },
            { name: 'trust.max_flaky_kicks', label: 'Reruns of checks judged flaky, per pushed head' },
            { name: 'trust.commit_trailer', label: 'Workers add a Co-authored-by trailer' },
        ],
    },
]

/** A key the server listed, with its label from `CONFIG_GROUPS`, or its name when no band names it. */
export interface LabelledKey {
    /** The key as the server sent it. */
    setting: ConfigKey
    /** Its name in words. */
    label: string
    /** The unit its field is in, shown after the field (`min`, `days`), if it has one. */
    unit?: string
    /** The labelled part of its band it is in, if its band is in parts. */
    part?: string
}

/**
 * The server's keys, by `CONFIG_GROUPS`'s bands: each band with the keys it names that the server sent, each in its
 * part, then `Other` with any it sent that no band names. A band left with no key is dropped.
 */
export function groupedKeys(keys: ConfigKey[]): { group: ConfigGroup; keys: LabelledKey[] }[] {
    const byName = new Map(keys.map((k) => [k.name, k]))
    const placed = new Set<string>()
    const found: { group: ConfigGroup; keys: LabelledKey[] }[] = []
    for (const group of CONFIG_GROUPS) {
        const shown: LabelledKey[] = []
        // A part runs from the key that names it to the next that names one, so it survives its first key going.
        let part: string | undefined
        for (const key of group.keys) {
            part = key.part ?? part
            const setting = byName.get(key.name)
            if (setting !== undefined) {
                shown.push({
                    setting,
                    label: key.label,
                    ...(key.unit === undefined ? {} : { unit: key.unit }),
                    ...(part === undefined ? {} : { part }),
                })
                placed.add(key.name)
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

/** A band's keys, cut into its labelled parts in order: one run with no `part` for a band in no parts. */
export function byPart(keys: LabelledKey[]): { part: string | undefined; keys: LabelledKey[] }[] {
    const parts: { part: string | undefined; keys: LabelledKey[] }[] = []
    for (const key of keys) {
        const last = parts.at(-1)
        if (last !== undefined && last.part === key.part) {
            last.keys.push(key)
        } else {
            parts.push({ part: key.part, keys: [key] })
        }
    }
    return parts
}

/** The longest `?q=` Loop settings keeps. */
export const CONFIG_QUERY_MAX = 100

/** A `?q=` as Loop settings filters by it: a string cut to `CONFIG_QUERY_MAX`, or undefined when it holds no word. */
export function configQueryOf(raw: unknown): string | undefined {
    if (typeof raw !== 'string') {
        return undefined
    }
    const text = raw.slice(0, CONFIG_QUERY_MAX)
    return text.trim() === '' ? undefined : text
}

/**
 * The bands as `q` filters them, ignoring case: each band with the rows whose label, key, or band's blurb holds it, and
 * every row `changed` says holds an unsaved change, whatever `q` says, so a change is never hidden. A band left with no
 * row stays, empty, so the index can say so. Every row when `q` is undefined.
 */
export function bandsMatching(
    bands: { group: ConfigGroup; keys: LabelledKey[] }[],
    q: string | undefined,
    changed: (name: string) => boolean,
): { group: ConfigGroup; keys: LabelledKey[] }[] {
    if (q === undefined) {
        return bands
    }
    const needle = q.trim().toLowerCase()
    return bands.map(({ group, keys }) => {
        const blurb = group.blurb.toLowerCase().includes(needle)
        return {
            group,
            keys: keys.filter(
                (k) =>
                    blurb ||
                    changed(k.setting.name) ||
                    k.label.toLowerCase().includes(needle) ||
                    k.setting.name.toLowerCase().includes(needle),
            ),
        }
    })
}

/** What a band's entry in the page's index counts: its keys set in this workspace, and its rows changed and unsaved. */
export interface BandCounts {
    /** Keys whose value this workspace's own config sets (source `private`). */
    set: number
    /** Rows the operator changed and has not saved, a field in error among them. */
    changed: number
}

/** How many of a band's keys this workspace sets, and how many `changed` says hold an unsaved change. */
export function bandCounts(keys: LabelledKey[], changed: (name: string) => boolean): BandCounts {
    return {
        set: keys.filter((k) => k.setting.source === 'private').length,
        changed: keys.filter((k) => changed(k.setting.name)).length,
    }
}

/** A band's title as a page's id and test id: `Retention & budget` is `retention-budget`. */
export function groupSlug(title: string): string {
    return title.toLowerCase().replaceAll(/[^a-z0-9]+/gu, '-')
}

/**
 * How many keys a save would change, and how many fields need fixing before it can, in words for the save bar. A field
 * in error counts as a change, since it is one the operator made.
 */
export function pendingText(changes: number, errors = 0): string {
    const count = changes + errors
    if (count === 0) {
        return 'No unsaved changes'
    }
    const changed = count === 1 ? '1 unsaved change' : `${count} unsaved changes`
    return errors === 0 ? changed : `${changed}, ${errors} to fix before saving`
}
