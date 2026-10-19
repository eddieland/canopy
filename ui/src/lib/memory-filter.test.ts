import { describe, expect, it } from 'vitest'

import {
    foundCount,
    memoryQueryOf,
    memoryRepoOf,
    memoryShowOf,
    memoryShown,
    shownCount,
    ticketNotesShown,
} from './memory-filter'

const NOW = Date.parse('2026-10-08T12:00:00Z')
const USE = { ticket_notes: 'use', lessons: 'use' } as const
const LESSON = {
    key: 'billing-client',
    text: 'Billing goes through src/billing/client.ts alone.',
    ticket_key: null,
    repo: 'web',
    status: 'active' as const,
    wrong_run_id: null,
    review_at: '2027-01-06T12:00:00Z',
}
const NONE = { q: undefined, repo: undefined, show: undefined }

describe('memoryShown', () => {
    it('keeps a memory whose key, text, ticket, or repository holds every word, in any case', () => {
        expect(memoryShown(LESSON, { ...NONE, q: 'BILLING client.ts' }, NOW, USE)).toBe(true)
        expect(memoryShown(LESSON, { ...NONE, q: 'web billing' }, NOW, USE)).toBe(true)
        expect(memoryShown(LESSON, { ...NONE, q: 'billing mobile' }, NOW, USE)).toBe(false)
    })

    it('keeps a memory for the repository, and one for every repository too', () => {
        expect(memoryShown(LESSON, { ...NONE, repo: 'web' }, NOW, USE)).toBe(true)
        expect(memoryShown(LESSON, { ...NONE, repo: 'api' }, NOW, USE)).toBe(false)
        expect(memoryShown({ ...LESSON, repo: null }, { ...NONE, repo: 'api' }, NOW, USE)).toBe(true)
    })

    it('keeps a lesson by its standing, under the tier’s mode', () => {
        const wrong = { ...LESSON, wrong_run_id: 44 }
        expect(memoryShown(wrong, { ...NONE, show: 'wrong' }, NOW, USE)).toBe(true)
        expect(memoryShown(LESSON, { ...NONE, show: 'wrong' }, NOW, USE)).toBe(false)
        expect(memoryShown({ ...LESSON, review_at: '2026-10-01T00:00:00Z' }, { ...NONE, show: 'due' }, NOW, USE)).toBe(
            true,
        )
        // Recording, nothing is wrong or due: no run read it.
        expect(memoryShown(wrong, { ...NONE, show: 'wrong' }, NOW, { ...USE, lessons: 'record' })).toBe(false)
    })
})

describe('ticketNotesShown', () => {
    it('keeps a ticket whose key or title holds every word', () => {
        const ticket = { ticket_key: 'ABC-100', title: 'Fix the flaky checkout test' }
        expect(ticketNotesShown(ticket, 'abc-1 flaky')).toBe(true)
        expect(ticketNotesShown(ticket, 'export')).toBe(false)
        expect(ticketNotesShown({ ...ticket, title: null }, 'abc')).toBe(true)
    })
})

describe('the search params', () => {
    it('keeps only what the page offers', () => {
        expect(memoryShowOf('due')).toBe('due')
        expect(memoryShowOf('pending')).toBeUndefined()
        expect(memoryQueryOf('  ')).toBeUndefined()
        expect(memoryQueryOf('x'.repeat(300))).toHaveLength(200)
        expect(memoryRepoOf('web')).toBe('web')
        expect(memoryRepoOf('Web')).toBeUndefined()
        expect(memoryRepoOf(3)).toBeUndefined()
    })
})

describe('foundCount', () => {
    it('counts the notes found, and says more may hold the words at the cap', () => {
        expect(foundCount(1)).toBe('1 note found')
        expect(foundCount(3)).toBe('3 notes found')
        expect(foundCount(50)).toBe('50+ notes found')
    })
})

describe('shownCount', () => {
    it('says of how many only while a filter left some out', () => {
        expect(shownCount(2, 7, true)).toBe('2 of 7')
        expect(shownCount(7, 7, true)).toBe('7')
        expect(shownCount(7, 7, false)).toBe('7')
    })
})
