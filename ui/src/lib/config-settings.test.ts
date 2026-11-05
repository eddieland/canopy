import { describe, expect, it } from 'vitest'

import type { ConfigKey, ConfigSaved } from '@/api/types'

import {
    boundText,
    byPart,
    changeList,
    CONFIG_GROUPS,
    configForm,
    groupedKeys,
    groupSlug,
    oneWay,
    oneWayText,
    pendingText,
    savedText,
    SOURCE_MEANING,
    SOURCE_WORD,
    valueText,
} from './config-settings'

const WORKERS: ConfigKey = {
    name: 'capacity.max_workers',
    value: 2,
    source: 'user',
    kind: 'limit',
    bound: 8,
    looser: 'higher',
    forever_at_zero: false,
    choices: [],
}
const SLOTS: ConfigKey = {
    name: 'capacity.repo_slots',
    value: { web: 4 },
    source: 'user',
    kind: 'limit',
    bound: 8,
    looser: 'higher',
    forever_at_zero: false,
    choices: [],
}
const PER_REPO: ConfigKey = { ...WORKERS, name: 'capacity.slots_per_repo', value: null }
const PACE: ConfigKey = { ...WORKERS, name: 'loop.interval_minutes', value: 15, bound: 5, looser: 'lower' }
const QUERY: ConfigKey = { ...PACE, name: 'tracker.query_every_minutes', value: 0, bound: 0 }
const RUN_FILES: ConfigKey = { ...PACE, name: 'retention.run_files_days', value: 30, bound: 7, forever_at_zero: true }
const REVIEWERS: ConfigKey = {
    name: 'trust.trusted_reviewers',
    value: ['alice', 'lint-bot'],
    source: 'user',
    kind: 'stricter',
    bound: null,
    looser: null,
    forever_at_zero: false,
    choices: [],
}
const REBASE: ConfigKey = { ...REVIEWERS, name: 'trust.rebase', value: true, source: 'default' }
const STACKING: ConfigKey = {
    ...REVIEWERS,
    name: 'policy.stacking',
    value: 'auto',
    source: 'default',
    choices: ['auto', 'never'],
}
const KICKS: ConfigKey = { ...REVIEWERS, name: 'trust.max_flaky_kicks', value: 2 }
const ALERTS: ConfigKey = {
    ...REVIEWERS,
    name: 'spend.budget_alerts',
    value: [50, 80],
    source: 'private',
    kind: 'free',
}
const KEYS = [WORKERS, SLOTS, PER_REPO, PACE, REVIEWERS, REBASE]

const SAVED: ConfigSaved = {
    changed: [{ name: 'loop.interval_minutes', old: 15, new: 30 }],
    hash: 'h',
    reload: { changed: ['loop.interval_minutes'], restart: [], after_tick: false },
    reload_refused: null,
    every: null,
}

function changes(drafts: Parameters<typeof configForm>[1]): ReturnType<typeof configForm>['changes'] {
    const form = configForm(KEYS, drafts)
    expect(form.errors).toEqual({})
    return form.changes
}

describe('config settings', () => {
    it('send only the keys touched and changed', () => {
        expect(changes({})).toEqual({})
        expect(changes({ 'capacity.max_workers': '2', 'capacity.slots_per_repo': ' ' })).toEqual({})
        expect(changes({ 'capacity.max_workers': ' 3 ', 'trust.rebase': false })).toEqual({
            'capacity.max_workers': 3,
            'trust.rebase': false,
        })
        expect(changes({ 'trust.rebase': true })).toEqual({})
        expect(configForm([...KEYS, STACKING], { 'policy.stacking': 'never' }).changes).toEqual({
            'policy.stacking': 'never',
        })
    })

    it('send a stricter count as a whole number, and name one that is not', () => {
        expect(configForm([KICKS], { 'trust.max_flaky_kicks': '2' }).changes).toEqual({})
        expect(configForm([KICKS], { 'trust.max_flaky_kicks': '1' }).changes).toEqual({ 'trust.max_flaky_kicks': 1 })
        expect(configForm([KICKS], { 'trust.max_flaky_kicks': 'once' }).errors).toEqual({
            'trust.max_flaky_kicks': 'not a whole number',
        })
    })

    it('name a count that is not a whole number, and send nothing for it', () => {
        expect(configForm(KEYS, { 'capacity.max_workers': 'many', 'capacity.repo_slots': { web: '2.5' } })).toEqual({
            changes: {},
            errors: { 'capacity.max_workers': 'not a whole number', 'capacity.repo_slots.web': 'not a whole number' },
        })
    })

    it("check a limit's bound as the server does: refused only past it and looser than the value read", () => {
        expect(configForm(KEYS, { 'capacity.max_workers': '9' })).toEqual({
            changes: {},
            errors: { 'capacity.max_workers': 'at most 8 from here; set more in the file' },
        })
        expect(configForm(KEYS, { 'capacity.max_workers': '-3' }).errors).toEqual({
            'capacity.max_workers': 'not a whole number',
        })
        expect(configForm(KEYS, { 'capacity.max_workers': '8' })).toEqual({
            changes: { 'capacity.max_workers': 8 },
            errors: {},
        })
        // A count the file set past the bound may come down, though still past it.
        expect(configForm([{ ...WORKERS, value: 12 }], { 'capacity.max_workers': '10' }).errors).toEqual({})
        expect(configForm([PACE], { 'loop.interval_minutes': '4' }).errors).toEqual({
            'loop.interval_minutes': 'at least 5 from here; set less in the file',
        })
        expect(configForm([RUN_FILES], { 'retention.run_files_days': '3' }).errors).toEqual({
            'retention.run_files_days': 'at least 7, or 0 for forever, from here; set less in the file',
        })
        expect(configForm([RUN_FILES], { 'retention.run_files_days': '0' }).changes).toEqual({
            'retention.run_files_days': 0,
        })
    })

    it("check a repository's own count against the bound, from the slots per repository it has now", () => {
        const perRepo = { ...PER_REPO, value: 2 }
        expect(configForm([SLOTS, perRepo], { 'capacity.repo_slots': { web: '9', api: '8' } })).toEqual({
            changes: { 'capacity.repo_slots': { api: 8 } },
            errors: { 'capacity.repo_slots.web': 'at most 8 from here; set more in the file' },
        })
    })

    it('let a stricter count only fall', () => {
        expect(configForm([KICKS], { 'trust.max_flaky_kicks': '3' })).toEqual({
            changes: {},
            errors: { 'trust.max_flaky_kicks': 'only fewer from here: at most 2; set more in the file' },
        })
        expect(configForm([KICKS], { 'trust.max_flaky_kicks': 'x' }).errors).toEqual({
            'trust.max_flaky_kicks': 'not a whole number',
        })
        expect(configForm([KICKS], { 'trust.max_flaky_kicks': '0' })).toEqual({
            changes: { 'trust.max_flaky_kicks': 0 },
            errors: {},
        })
    })

    it('name a count emptied of a value the file sets, which the page cannot unset', () => {
        expect(configForm(KEYS, { 'capacity.max_workers': ' ', 'capacity.repo_slots': { web: '' } }).errors).toEqual({
            'capacity.max_workers': 'empty: type a count, or Discard to keep 2',
            'capacity.repo_slots.web': 'empty: type a count, or Discard to keep 4',
        })
        // A pool left unmanaged holds nothing to keep; a repository just picked holds a draft to type or discard.
        expect(changes({ 'capacity.slots_per_repo': '' })).toEqual({})
        expect(configForm(KEYS, { 'capacity.repo_slots': { api: '' } }).errors).toEqual({
            'capacity.repo_slots.api': 'empty: type a count, or Discard',
        })
    })

    it('give an unmanaged pool a count only when one is typed', () => {
        expect(changes({ 'capacity.slots_per_repo': '' })).toEqual({})
        expect(changes({ 'capacity.slots_per_repo': '3' })).toEqual({ 'capacity.slots_per_repo': 3 })
    })

    it('send only the repositories whose count changed', () => {
        expect(changes({ 'capacity.repo_slots': { web: '4' } })).toEqual({})
        expect(changes({ 'capacity.repo_slots': { web: '5', api: '2' } })).toEqual({
            'capacity.repo_slots': { web: 5, api: 2 },
        })
    })

    it('send a list as the entries kept, when one was dropped', () => {
        expect(changes({ 'trust.trusted_reviewers': ['alice', 'lint-bot'] })).toEqual({})
        expect(changes({ 'trust.trusted_reviewers': ['alice'] })).toEqual({ 'trust.trusted_reviewers': ['alice'] })
    })

    it('say where a value comes from and how far the page may take it', () => {
        // A chip's word is short, every row has one; what it means is its tip, and the page's help.
        expect(Object.values(SOURCE_WORD)).toEqual(['this workspace', 'user', 'workspace', 'default'])
        expect(SOURCE_MEANING.user).toContain('a change here is saved for this workspace only')
        expect(boundText(WORKERS)).toBe('at most 8 from here')
        expect(boundText(PACE)).toBe('at least 5 from here')
        expect(boundText(QUERY)).toBe('')
        expect(boundText(RUN_FILES)).toBe('at least 7, or 0 for forever, from here')
        expect(boundText(REVIEWERS)).toBe('stricter only')
        expect(boundText(KICKS)).toBe('only fewer from here')
    })

    it('say what a save wrote apart from what its reload did', () => {
        expect(savedText(SAVED)).toBe(
            "Saved loop.interval_minutes to this workspace's config. The loop runs on it from now on. A run already " +
                'running ' +
                'keeps the prompt and permissions it started with.',
        )
        expect(savedText({ ...SAVED, every: 3 })).toContain('--every 3 still sets the pace until the loop restarts.')
        expect(savedText({ ...SAVED, reload: { changed: [], restart: [], after_tick: true }, every: null })).toContain(
            'The loop reads it once the running tick ends.',
        )
        expect(savedText({ ...SAVED, reload: null, reload_refused: 'bad file' })).toContain(
            'The reload was refused (bad file); the save takes effect at the next reload.',
        )
        expect(savedText({ ...SAVED, changed: [], reload: null })).toBe(
            'Nothing changed: each setting already had that value, and nothing was written.',
        )
    })
})

describe('budget alerts', () => {
    it('send the percentages typed whole, commas or spaces between, when they differ from the ones read', () => {
        expect(configForm([ALERTS], { [ALERTS.name]: '50, 80' }).changes).toEqual({})
        expect(configForm([ALERTS], { [ALERTS.name]: '25 50,80' }).changes).toEqual({ [ALERTS.name]: [25, 50, 80] })
        expect(configForm([ALERTS], { [ALERTS.name]: '80, 50' }).changes).toEqual({ [ALERTS.name]: [80, 50] })
        expect(configForm([ALERTS], { [ALERTS.name]: ' ' }).changes).toEqual({ [ALERTS.name]: [] })
    })

    it('name a list with something other than a whole number in it, and send nothing for it', () => {
        expect(configForm([ALERTS], { [ALERTS.name]: '50, most' })).toEqual({
            changes: {},
            errors: { [ALERTS.name]: 'whole percentages, comma separated' },
        })
        expect(boundText(ALERTS)).toBe('percentages, comma separated; 100% is always sent')
    })
})

describe('config groups', () => {
    it('put each key in its band with its words, and a key no band names in Other', () => {
        const odd: ConfigKey = { ...WORKERS, name: 'capacity.max_something_new' }
        const found = groupedKeys([REVIEWERS, WORKERS, odd, PACE])
        expect(found.map((g) => g.group.title)).toEqual(['Capacity', 'Timing', 'Guardrails', 'Other'])
        expect(found[0]?.keys).toEqual([{ setting: WORKERS, label: 'Workers at once' }])
        expect(found[1]?.keys).toEqual([{ setting: PACE, label: 'Time between ticks', unit: 'min', part: 'Pace' }])
        expect(found[3]?.keys).toEqual([{ setting: odd, label: 'capacity.max_something_new' }])
    })

    it('keep a part when the key that names it is not sent, and cut a band into its parts in order', () => {
        const idle: ConfigKey = { ...PACE, name: 'loop.idle_max_minutes' }
        const cooldown: ConfigKey = { ...PACE, name: 'policy.ci_cooldown_minutes' }
        const settle: ConfigKey = { ...PACE, name: 'review.settle_minutes' }
        const [timing] = groupedKeys([settle, idle, cooldown])
        expect(timing?.keys.map((k) => [k.setting.name, k.part])).toEqual([
            ['loop.idle_max_minutes', 'Pace'],
            ['policy.ci_cooldown_minutes', 'Waits'],
            ['review.settle_minutes', 'Waits'],
        ])
        expect(byPart(timing?.keys ?? []).map((p) => [p.part, p.keys.length])).toEqual([
            ['Pace', 1],
            ['Waits', 2],
        ])
        const [capacity] = groupedKeys([WORKERS, PER_REPO])
        expect(byPart(capacity?.keys ?? []).map((p) => p.part)).toEqual([undefined])
    })

    it('hold five bands, the minutes in one', () => {
        expect(CONFIG_GROUPS.map((g) => g.title)).toEqual([
            'Capacity',
            'Attempts',
            'Timing',
            'Retention & budget',
            'Guardrails',
        ])
        expect(groupSlug('Retention & budget')).toBe('retention-budget')
    })

    it('name every key the server edits in some band', () => {
        const named = CONFIG_GROUPS.flatMap((g) => g.keys.map((k) => k.name))
        expect(new Set(named).size).toBe(named.length)
        expect(named).toHaveLength(49)
    })

    it('count the unsaved changes', () => {
        expect(pendingText(0)).toBe('No unsaved changes')
        expect(pendingText(1)).toBe('1 unsaved change')
        expect(pendingText(3)).toBe('3 unsaved changes')
        // A field in error is a change too, so the bar never says there is none beside an enabled Discard.
        expect(pendingText(0, 1)).toBe('1 unsaved change, 1 to fix before saving')
        expect(pendingText(2, 1)).toBe('3 unsaved changes, 1 to fix before saving')
    })
})

describe('the save bar', () => {
    it('list each change as its key, its value read, and the one a save writes, in the order the keys come', () => {
        const keys = [...KEYS, STACKING]
        const { changes: changed } = configForm(keys, {
            'trust.rebase': false,
            'capacity.max_workers': '5',
            'capacity.repo_slots': { web: '6', api: '2' },
            'trust.trusted_reviewers': ['alice'],
            'policy.stacking': 'never',
            'capacity.slots_per_repo': '3',
        })
        expect(changeList(keys, changed)).toEqual([
            { name: 'capacity.max_workers', old: '2', new: '5' },
            { name: 'capacity.repo_slots.web', old: '4', new: '6' },
            { name: 'capacity.repo_slots.api', old: 'unmanaged', new: '2' },
            { name: 'capacity.slots_per_repo', old: 'unmanaged', new: '3' },
            { name: 'trust.trusted_reviewers', old: 'alice, lint-bot', new: 'alice' },
            { name: 'trust.rebase', old: 'on', new: 'off' },
            { name: 'policy.stacking', old: 'auto', new: 'never' },
        ])
    })

    it('name the stricter keys a save changes, which only the file undoes, and nothing else', () => {
        expect(oneWay(KEYS, { 'capacity.max_workers': 5 })).toEqual([])
        expect(oneWay(KEYS, { 'capacity.max_workers': 5, 'trust.rebase': false })).toEqual(['trust.rebase'])
        expect(oneWayText(['trust.rebase'])).toBe('trust.rebase: only an edit to config.toml undoes this')
        expect(oneWayText(['trust.rebase', 'policy.plan'])).toBe(
            'trust.rebase, policy.plan: only an edit to config.toml undoes these',
        )
    })

    it('say a value in words', () => {
        expect(valueText(null, 'spend.monthly_budget_usd')).toBe('none')
        expect(valueText(null, 'capacity.slots_per_repo')).toBe('unmanaged')
        expect(valueText([], 'trust.trusted_reviewers')).toBe('none')
        expect(valueText({ web: 4, api: 2 }, 'capacity.repo_slots')).toBe('web 4, api 2')
        expect(valueText(true, 'trust.rebase')).toBe('on')
    })
})
