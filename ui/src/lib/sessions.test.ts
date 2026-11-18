import { describe, expect, it } from 'vitest'

import type { SessionList } from '@/api/types'

import { directoryTail, hitNote, indexBehind, sessionName } from './sessions'

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

describe('hitNote', () => {
    it.each([
        [0, false, null],
        [1, false, '1 more message holds them'],
        [3, false, '3 more messages hold them'],
        [0, true, 'indexed in part: past its bound, words are not found'],
        [2, true, '2 more messages hold them; indexed in part: past its bound, words are not found'],
    ])('of %i more and cut %s is %s', (more, cut, note) => {
        expect(hitNote({ more_messages: more, cut })).toBe(note)
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
