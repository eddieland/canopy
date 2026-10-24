import { QueryClient } from '@tanstack/react-query'
import { act, cleanup, fireEvent, screen } from '@testing-library/react'
import { afterEach, describe, expect, it } from 'vitest'

import { mockAttention, mockCapacity, mockReviews } from '@/api/mocks'
import { keys } from '@/api/queries'
import type { AttentionItem, LoopState, MemoryState, ReviewSummary } from '@/api/types'
import { renderRouted } from '@/test-utils'

import { Nav } from './nav'

afterEach(cleanup)

const WAITING = mockAttention[0] as AttentionItem
// One run that failed, one question waiting on the operator, and a finding: one of each part of the count.
const ITEMS: AttentionItem[] = [
    { ...WAITING, id: 'a2', reason: 'worker_failed', detail: 'run 40 failed' },
    WAITING,
    { ...WAITING, id: 'a3', reason: 'finding', finding: true, chore: 'deps', ticket_key: null },
]

// A review run that ended with `fields`: a result to read, not seen, unless they say otherwise.
function ended(id: number, fields: Partial<ReviewSummary>): ReviewSummary {
    const running = mockReviews[0] as ReviewSummary
    const done = { status: 'ok', state: 'done', ended_at: '2026-10-08T12:05:00Z', news: true, seen: false } as const
    return { ...running, id, ...done, ...fields }
}

const TIER: MemoryState['lessons'] = { mode: 'record', words: 'recording', band: 'Recording only.' }

function renderNav({ at = '/attention', items, compact = false, waiting, reviews }: Partial<NavSetup> = {}) {
    const client = new QueryClient()
    // Nothing is fetched: the attention list, the loop's state, and the reviews are what the test seeds, as the stream
    // would send.
    client.setQueryDefaults(keys.attention, { enabled: false })
    client.setQueryDefaults(keys.loop, { enabled: false })
    client.setQueryDefaults(keys.reviews, { enabled: false })
    if (items !== undefined) {
        client.setQueryData(keys.attention, items)
    }
    if (reviews !== undefined) {
        client.setQueryData(keys.reviews, reviews)
    }
    if (waiting !== undefined) {
        const memory: MemoryState = {
            readout: 'memory: recording',
            tiers: 'ticket notes: recording, lessons: recording',
            ticket_notes: TIER,
            lessons: TIER,
            proposals_waiting: waiting,
        }
        client.setQueryData<LoopState>(keys.loop, { capacity: mockCapacity, paused: null, notice: null, memory })
    }
    return renderRouted(<Nav compact={compact} />, { at, client })
}

interface NavSetup {
    at: string
    items: AttentionItem[] | undefined
    compact: boolean
    // How many proposals the loop's state says wait; no memory state when undefined.
    waiting: number | undefined
    // The reviews list; not arrived when undefined.
    reviews: ReviewSummary[] | undefined
}

// The links the nav marks as the page shown.
function current(): string[] {
    return screen
        .getAllByRole('link')
        .filter((link) => link.getAttribute('aria-current') === 'page')
        .map((link) => link.textContent)
}

describe('Nav', () => {
    it.each([
        ['a ticket', '/tickets/ABC-102', 'Tickets'],
        ['a PR', '/pull-requests/pr?url=x', 'Pull requests'],
        ['a review', '/pull-requests/reviews/4', 'Pull requests'],
        ['a chore', '/chores/deps', 'Chores'],
        ['a tick', '/runs/ticks/12', 'Runs'],
        ['the runs list', '/runs', 'Runs'],
        ['the memory page', '/memory', 'Memory'],
    ] as const)("keeps its section current on %s's page", async (_, at, section) => {
        await renderNav({ at, items: [] })
        expect(current()).toEqual([section])
    })

    it('marks no section on a page in none', async () => {
        await renderNav({ at: '/no-such-page', items: [] })
        expect(current()).toEqual([])
    })

    it("lists no Settings, which the rail's foot opens, so marks nothing on its page", async () => {
        await renderNav({ at: '/settings', items: [] })
        expect(screen.queryByRole('link', { name: 'Settings' })).toBeNull()
        expect(current()).toEqual([])
    })

    it('opens the page of the section followed', async () => {
        const { router } = await renderNav({ items: [] })
        await act(async () => {
            fireEvent.click(screen.getByRole('link', { name: 'Reports' }))
            await Promise.resolve()
        })
        expect(router.state.location.pathname).toBe('/reports')
    })

    it("splits Attention's count as its counter does, in words for a screen reader and on hover", async () => {
        await renderNav({ at: '/runs', items: [...ITEMS, WAITING] })
        expect(screen.getByRole('link', { name: 'Attention 1 broken, 2 waiting on you, 1 other' })).toBeDefined()
        expect(screen.getByTitle('1 broken, 2 waiting on you, 1 other')).toBeDefined()
        // The eye reads the three numbers, each in its part's color.
        expect(screen.getAllByText(/^\d$/u).map((count) => count.textContent)).toEqual(['1', '2', '1'])
    })

    it.each<[string, AttentionItem[] | undefined]>([
        ['the list is empty', []],
        ['the list has not arrived', undefined],
    ])('shows no count beside Attention when %s', async (_, items) => {
        await renderNav({ items })
        expect(screen.getByRole('link', { name: 'Attention' }).textContent).toBe('Attention')
    })

    it.each([
        [1, '1 proposal waiting on you'],
        [3, '3 proposals waiting on you'],
    ])('counts %i proposal(s) waiting beside Memory, in words for a screen reader and on hover', async (n, said) => {
        await renderNav({ at: '/runs', items: [], waiting: n })
        expect(screen.getByRole('link', { name: `Memory ${said}` })).toBeDefined()
        expect(screen.getByTitle(said).textContent).toBe(`${n}${said}`)
    })

    it.each<[string, number | undefined]>([
        ['none waits', 0],
        ['memory is off', undefined],
    ])('shows no count beside Memory when %s', async (_, waiting) => {
        await renderNav({ items: [], waiting })
        expect(screen.getByRole('link', { name: 'Memory' }).textContent).toBe('Memory')
    })

    it("counts the reviews new to the operator beside Pull requests, in their worst finding's color", async () => {
        // Review 3 was seen; 6 and 7, which the operator asked for, ended since, and 8 still runs. Review 5 was clean
        // and the loop started it on its own: it has nothing to read, so it is not counted.
        const reviews = [
            ended(8, { state: 'running', status: 'running', ended_at: null, verdict: null, news: false }),
            ended(7, { verdict: 'clean' }),
            ended(6, { verdict: 'findings', findings: 2, worst: 'major', worst_count: 1 }),
            ended(5, { verdict: 'clean', news: false }),
            ended(3, { verdict: 'findings', findings: 1, worst: 'blocking', worst_count: 1, seen: true }),
        ]
        await renderNav({ at: '/runs', items: [], reviews })
        expect(screen.getByRole('link', { name: 'Pull requests 2 new reviews to read' })).toBeDefined()
        expect(screen.getByTitle('2 new reviews to read').textContent).toBe('22 new reviews to read')
        expect(screen.getByTestId('nav-reviews-count').className).toContain('text-status-blocked')
    })

    it('shows no count beside Pull requests when every result is seen', async () => {
        await renderNav({ items: [], reviews: [ended(6, { verdict: 'clean', seen: true })] })
        expect(screen.getByRole('link', { name: 'Pull requests' }).textContent).toBe('Pull requests')
    })

    it('names each icon in a compact nav, and gives Attention its total, said in words', async () => {
        await renderNav({ at: '/tickets/ABC-102', items: ITEMS, compact: true, waiting: 2 })
        expect(current()).toEqual(['Tickets'])
        expect(screen.getByRole('link', { name: 'Attention 1 broken, 1 waiting on you, 1 other' })).toBeDefined()
        expect(screen.getAllByText(/^\d$/u).map((count) => count.textContent)).toEqual(['3', '2'])
        expect(screen.getByRole('link', { name: 'Memory 2 proposals waiting on you' }).title).toBe(
            'Memory: What workers remember: the ticket notes and lessons, and which runs read them',
        )
    })
})
