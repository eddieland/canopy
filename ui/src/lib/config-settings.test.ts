import { describe, expect, it } from 'vitest'

import type { ConfigKey, ConfigSaved } from '@/api/types'

import {
    boundText,
    CONFIG_GROUPS,
    configForm,
    groupedKeys,
    pendingText,
    savedText,
    sourceText,
} from './config-settings'

const WORKERS: ConfigKey = {
    name: 'capacity.max_workers',
    value: 2,
    source: 'user',
    kind: 'limit',
    bound: 8,
    looser: 'higher',
}
const SLOTS: ConfigKey = {
    name: 'capacity.repo_slots',
    value: { web: 4 },
    source: 'user',
    kind: 'limit',
    bound: 8,
    looser: 'higher',
}
const PER_REPO: ConfigKey = { ...WORKERS, name: 'capacity.slots_per_repo', value: null }
const PACE: ConfigKey = { ...WORKERS, name: 'loop.interval_minutes', value: 15, bound: 5, looser: 'lower' }
const REVIEWERS: ConfigKey = {
    name: 'trust.trusted_reviewers',
    value: ['alice', 'lint-bot'],
    source: 'user',
    kind: 'stricter',
    bound: null,
    looser: null,
}
const REBASE: ConfigKey = { ...REVIEWERS, name: 'trust.rebase', value: true, source: 'default' }
const STACKING: ConfigKey = { ...REVIEWERS, name: 'policy.stacking', value: 'auto', source: 'default' }
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
    expect(form.invalid).toEqual([])
    return form.changes
}

describe('config settings', () => {
    it('send only the keys touched and changed', () => {
        expect(changes({})).toEqual({})
        expect(changes({ 'capacity.max_workers': '2', 'loop.interval_minutes': ' ' })).toEqual({})
        expect(changes({ 'capacity.max_workers': ' 3 ', 'trust.rebase': false })).toEqual({
            'capacity.max_workers': 3,
            'trust.rebase': false,
        })
        expect(changes({ 'trust.rebase': true })).toEqual({})
        expect(configForm([...KEYS, STACKING], { 'policy.stacking': 'never' }).changes).toEqual({
            'policy.stacking': 'never',
        })
    })

    it('name a count that is not a whole number, and send nothing for it', () => {
        expect(configForm(KEYS, { 'capacity.max_workers': 'many', 'capacity.repo_slots': { web: '2.5' } })).toEqual({
            changes: {},
            invalid: ['capacity.max_workers', 'capacity.repo_slots.web'],
        })
    })

    it('give an unmanaged pool a count only when one is typed', () => {
        expect(changes({ 'capacity.slots_per_repo': '' })).toEqual({})
        expect(changes({ 'capacity.slots_per_repo': '3' })).toEqual({ 'capacity.slots_per_repo': 3 })
    })

    it('send only the repositories whose count changed', () => {
        expect(changes({ 'capacity.repo_slots': { web: '4', api: '' } })).toEqual({})
        expect(changes({ 'capacity.repo_slots': { web: '5', api: '2' } })).toEqual({
            'capacity.repo_slots': { web: 5, api: 2 },
        })
    })

    it('send a list as the entries kept, when one was dropped', () => {
        expect(changes({ 'trust.trusted_reviewers': ['alice', 'lint-bot'] })).toEqual({})
        expect(changes({ 'trust.trusted_reviewers': ['alice'] })).toEqual({ 'trust.trusted_reviewers': ['alice'] })
    })

    it('say where a value comes from and how far the page may take it', () => {
        expect(sourceText(WORKERS)).toBe('from your user config; a change here is for this workspace only')
        expect(sourceText({ ...WORKERS, source: 'private' })).toBe("set in this workspace's config")
        expect(sourceText({ ...WORKERS, source: 'workspace' })).toBe('set in the workspace file')
        expect(sourceText(REBASE)).toBe('default')
        expect(boundText(WORKERS)).toBe('at most 8 from here')
        expect(boundText(PACE)).toBe('at least 5 from here')
        expect(boundText(REVIEWERS)).toBe('stricter only')
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

describe('config groups', () => {
    it('put each key in its panel with its words, and a key no panel names in Other', () => {
        const odd: ConfigKey = { ...WORKERS, name: 'capacity.max_something_new' }
        const found = groupedKeys([REVIEWERS, WORKERS, odd, PACE])
        expect(found.map((g) => g.group.title)).toEqual(['Capacity', 'Pace', 'Trust', 'Other'])
        expect(found[0]?.keys).toEqual([{ setting: WORKERS, label: 'Workers at once' }])
        expect(found[3]?.keys).toEqual([{ setting: odd, label: 'capacity.max_something_new' }])
    })

    it('name every key the server edits in some panel', () => {
        const named = CONFIG_GROUPS.flatMap((g) => g.keys.map((k) => k.name))
        expect(new Set(named).size).toBe(named.length)
        expect(named).toHaveLength(19)
    })

    it('count the unsaved changes', () => {
        expect(pendingText(0)).toBe('No unsaved changes')
        expect(pendingText(1)).toBe('1 unsaved change')
        expect(pendingText(3)).toBe('3 unsaved changes')
    })
})
