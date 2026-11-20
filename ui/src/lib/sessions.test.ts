import { describe, expect, it } from 'vitest'

import type { SessionList } from '@/api/types'

import {
    costAmountOf,
    costBoundOf,
    costBoundText,
    costBoundWords,
    directoryTail,
    indexBehind,
    moreMessages,
    sessionName,
    unstopped,
} from './sessions'

describe('directoryTail', () => {
    it.each([
        ['/home/op/acme/infra', '…/acme/infra'],
        ['/home/op/beta/.treehouse/api-5d1e0b2c/1/api', '…/1/api'],
        ['/home/op', '/home/op'],
        ['/srv', '/srv'],
        ['/home/op/notes/', '…/op/notes'],
    ])('keeps the last two parts of %s', (directory, tail) => {
        expect(directoryTail(directory)).toBe(tail)
    })
})

describe('sessionName', () => {
    it('is the title, or the id for a session with none', () => {
        expect(sessionName({ title: 'Fix the deploy', session_id: 'ses_1' })).toBe('Fix the deploy')
        expect(sessionName({ title: null, session_id: 'ses_1' })).toBe('session ses_1')
    })
})

describe('moreMessages', () => {
    it.each([
        [0, null],
        [1, '1 more message holds the words'],
        [3, '3 more messages hold the words'],
    ])('of %i is %s', (more, said) => {
        expect(moreMessages(more)).toBe(said)
    })
})

describe('unstopped', () => {
    it.each([
        ['the record is locked.', 'the record is locked'],
        ['the record is locked', 'the record is locked'],
        ['no such file: sessions.db. ', 'no such file: sessions.db'],
    ])('ends %s as %s', (text, ended) => {
        expect(unstopped(text)).toBe(ended)
    })
})

describe('indexBehind', () => {
    const BUILT: NonNullable<SessionList['index']> = {
        sessions: 40,
        through: '2026-10-08T12:06:00Z',
        back_to: null,
        built: true,
        read_at: '2026-10-08T12:08:00Z',
        error: null,
        current: true,
        size_bytes: 4096,
    }

    it('is false below text, and at text once the index is built, read, and current', () => {
        expect(indexBehind({ search: 'titles', index: null, why_titles: null })).toBe(false)
        expect(indexBehind({ search: 'text', index: BUILT, why_titles: null })).toBe(false)
    })

    it.each([
        ['not built yet', null],
        ['still building', { ...BUILT, built: false }],
        ['failed', { ...BUILT, error: 'the record is locked' }],
        ['built under another exclude', { ...BUILT, current: false }],
    ])('is true while the index is %s', (_why, index) => {
        expect(indexBehind({ search: 'text', index, why_titles: null })).toBe(true)
    })

    it('is true where text is asked for and the index cannot be kept', () => {
        expect(indexBehind({ search: 'titles', index: null, why_titles: 'SQLite 3.40 cannot keep it' })).toBe(true)
    })
})

describe('costAmountOf', () => {
    it.each([
        ['5', 5],
        [' 0.5 ', 0.5],
        ['.5', 0.5],
        ['5.', 5],
        ['', undefined],
        ['-1', undefined],
        ['1e3', undefined],
        ['$5', undefined],
        ['1.2.3', undefined],
        ['1234567890123', undefined],
        // Too small to write in the address without an exponent.
        ['0.0000001', undefined],
        ['0.000001', 0.000001],
    ])('reads %j as dollars, or as nothing', (text, usd) => {
        expect(costAmountOf(text)).toBe(usd)
    })
})

describe('costBoundOf', () => {
    it('reads a comparison and an amount, as costBoundText writes them', () => {
        expect(costBoundOf('gte:5')).toEqual({ op: 'gte', usd: 5 })
        expect(costBoundOf(costBoundText({ op: 'lt', usd: 0.25 }))).toEqual({ op: 'lt', usd: 0.25 })
    })

    it.each(['eq:5', 'gte', 'gte:', 'gte:-1', 'gte:5:6', 5, null, undefined])('reads no bound in %j', (raw) => {
        expect(costBoundOf(raw)).toBeUndefined()
    })
})

describe('costBoundWords', () => {
    it('says the bound as what a session did, the amount as every cost is shown', () => {
        expect(costBoundWords({ op: 'gte', usd: 5 })).toBe('cost at least $5.00')
        expect(costBoundWords({ op: 'lt', usd: 0.5 })).toBe('cost less than $0.50')
    })
})
