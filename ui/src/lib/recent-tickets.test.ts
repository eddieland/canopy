import { act, cleanup, renderHook } from '@testing-library/react'
import { afterEach, beforeEach, describe, expect, it } from 'vitest'

import { otherTab } from '@/test-utils'

import {
    known,
    parseRecent,
    RECENT_MAX,
    STORAGE_KEY,
    useRecentTickets,
    useViewedTicket,
    viewed,
} from './recent-tickets'

const AT = '2026-10-08T12:00:00Z'

beforeEach(() => localStorage.clear())
afterEach(cleanup)

describe('parseRecent', () => {
    it('reads the list stored, and nothing from what is not one', () => {
        const list = [{ key: 'ABC-1', title: 'One', viewedAt: AT }]
        expect(parseRecent(JSON.stringify(list))).toEqual(list)
        expect(parseRecent(null)).toEqual([])
        expect(parseRecent('not json')).toEqual([])
        expect(parseRecent('{"key":"ABC-1"}')).toEqual([])
    })

    it('drops each entry that is not a ticket viewed, and keeps at most RECENT_MAX', () => {
        const good = { key: 'ABC-1', title: null, viewedAt: AT }
        const raw = JSON.stringify([good, { key: 2, title: null, viewedAt: AT }, { key: 'ABC-3', viewedAt: 'soon' }])
        expect(parseRecent(raw)).toEqual([good])

        const many = Array.from({ length: RECENT_MAX + 5 }, (_, i) => ({ key: `ABC-${i}`, title: null, viewedAt: AT }))
        expect(parseRecent(JSON.stringify(many))).toHaveLength(RECENT_MAX)
    })
})

describe('viewed', () => {
    it('puts the ticket viewed first, once, with its title then', () => {
        const list = [
            { key: 'ABC-1', title: 'One', viewedAt: AT },
            { key: 'ABC-2', title: 'Two', viewedAt: AT },
        ]
        expect(viewed(list, 'ABC-2', 'Two, renamed', '2026-10-08T12:05:00Z').map((t) => [t.key, t.title])).toEqual([
            ['ABC-2', 'Two, renamed'],
            ['ABC-1', 'One'],
        ])
    })

    it('drops the oldest past RECENT_MAX', () => {
        let list = viewed([], 'ABC-0', null, AT)
        for (let i = 1; i <= RECENT_MAX; i += 1) {
            list = viewed(list, `ABC-${i}`, null, AT)
        }
        expect(list).toHaveLength(RECENT_MAX)
        expect(list[0]?.key).toBe(`ABC-${RECENT_MAX}`)
        expect(list.some((t) => t.key === 'ABC-0')).toBe(false)
    })
})

describe('known', () => {
    it('keeps only the tickets the journal still holds, by a list read after they were viewed', () => {
        const list = [
            { key: 'ABC-1', title: null, viewedAt: AT },
            { key: 'ABC-2', title: null, viewedAt: AT },
        ]
        expect(known(list, new Set(['ABC-2']), Date.parse(AT) + 1000).map((t) => t.key)).toEqual(['ABC-2'])
    })

    it('keeps a ticket viewed after the list was read, which that list cannot know', () => {
        const list = [{ key: 'ABC-1', title: null, viewedAt: AT }]
        expect(known(list, new Set(), Date.parse(AT) - 1000).map((t) => t.key)).toEqual(['ABC-1'])
    })
})

describe('useViewedTicket', () => {
    it('records a ticket once its title has loaded, and again for the next ticket', () => {
        const { rerender } = renderHook(
            ({ ticketKey, title }: { ticketKey: string; title: string | null | undefined }) => {
                useViewedTicket(ticketKey, title)
            },
            { initialProps: { ticketKey: 'ABC-1', title: undefined as string | null | undefined } },
        )
        expect(parseRecent(localStorage.getItem(STORAGE_KEY))).toEqual([])

        rerender({ ticketKey: 'ABC-1', title: 'One' })
        rerender({ ticketKey: 'ABC-2', title: null })
        expect(parseRecent(localStorage.getItem(STORAGE_KEY)).map((t) => [t.key, t.title])).toEqual([
            ['ABC-2', null],
            ['ABC-1', 'One'],
        ])
    })

    it('records nothing when the title changes on the page, as the overseer renaming it', () => {
        const { rerender } = renderHook(
            ({ ticketKey, title }: { ticketKey: string; title: string | null | undefined }) => {
                useViewedTicket(ticketKey, title)
            },
            { initialProps: { ticketKey: 'ABC-1', title: 'One' } },
        )
        rerender({ ticketKey: 'ABC-2', title: 'Two' })
        rerender({ ticketKey: 'ABC-2', title: 'Two, renamed' })
        expect(parseRecent(localStorage.getItem(STORAGE_KEY)).map((t) => [t.key, t.title])).toEqual([
            ['ABC-2', 'Two'],
            ['ABC-1', 'One'],
        ])
    })

    it('shows a ticket another tab viewed', () => {
        const { result } = renderHook(() => useRecentTickets())
        act(() => {
            otherTab(STORAGE_KEY, JSON.stringify([{ key: 'ABC-9', title: 'Nine', viewedAt: AT }]))
        })
        expect(result.current.map((t) => t.key)).toEqual(['ABC-9'])
    })
})
