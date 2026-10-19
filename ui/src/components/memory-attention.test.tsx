import { QueryClient } from '@tanstack/react-query'
import { cleanup, screen, within } from '@testing-library/react'
import { afterEach, describe, expect, it } from 'vitest'

import { keys } from '@/api/queries'
import type { MemoryEntry, MemoryOverview, MemoryProposal } from '@/api/types'
import { renderRouted } from '@/test-utils'

import { LessonsDue, LessonsWrong, ProposalsWaiting } from './memory-attention'

afterEach(() => {
    cleanup()
})

const ENTRY: MemoryEntry = {
    id: 5,
    scope: 'proposal',
    ticket_key: 'ABC-1',
    repo: null,
    key: 'api-tests',
    text: 'Run the API tests with make test-api.',
    status: 'pending',
    why: null,
    run_id: 39,
    head: null,
    created_at: '2026-10-08T10:00:00Z',
    use_count: 0,
    used_by: [],
    last_used_at: null,
    review_at: null,
    wrong_at: null,
    wrong_run_id: null,
    promoted_from: null,
    origin: null,
    version: 1,
    edited: false,
    private: false,
}

function proposal(entry: Partial<MemoryEntry>): MemoryProposal {
    return {
        entry: { ...ENTRY, ...entry },
        run_kind: 'implement',
        run_status: 'done',
        private: false,
        ticket_done: true,
        expires_at: '2026-10-22T10:00:00Z',
    }
}

function lesson(id: number, reviewAt: string): MemoryEntry {
    return { ...ENTRY, id, scope: 'lesson', ticket_key: null, status: 'active', run_id: null, review_at: reviewAt }
}

// Renders `ui` over a journal whose memory is `overview`, read already and never read again.
function renderOver(ui: React.JSX.Element, overview: Partial<MemoryOverview>) {
    const client = new QueryClient({ defaultOptions: { queries: { staleTime: Infinity, retry: false } } })
    client.setQueryData(keys.memory, {
        state: null,
        tickets: [],
        proposals: [],
        lessons: [],
        lessons_digest: null,
        repos: ['api'],
        past_proposals: [],
        past_lessons: [],
        ...overview,
    } satisfies MemoryOverview)
    return renderRouted(ui, { client })
}

describe('ProposalsWaiting', () => {
    it("lists the ticket's proposals still waiting, each promoted as written or rejected", async () => {
        await renderOver(<ProposalsWaiting ticketKey="ABC-1" />, {
            proposals: [proposal({}), proposal({ id: 6, ticket_key: 'ABC-2', key: 'other' })],
        })
        const section = screen.getByRole('region', { name: 'Proposals' })
        expect(within(section).getByTestId('memory-5')).toBeTruthy()
        expect(within(section).queryByTestId('memory-6')).toBeNull()
        expect(
            within(section)
                .getAllByRole('button')
                .map((b) => b.textContent),
        ).toEqual(['Promote as written', 'Reject'])
        expect(within(section).getByRole('link', { name: 'memory page' }).getAttribute('href')).toBe('/memory')
    })

    it('says none waits once each is promoted or rejected, until the next tick', async () => {
        await renderOver(<ProposalsWaiting ticketKey="ABC-1" />, {})
        expect(screen.getByText('none of its proposals waits now: the item leaves at the next tick')).toBeTruthy()
    })
})

describe('LessonsDue', () => {
    it('lists the lessons whose review date has come, each with Renew', async () => {
        await renderOver(<LessonsDue />, {
            lessons: [lesson(8, '2020-01-01T00:00:00Z'), lesson(9, '2999-01-01T00:00:00Z')],
        })
        const section = screen.getByRole('region', { name: 'Lessons due' })
        expect(within(section).getByTestId('memory-8')).toBeTruthy()
        expect(within(section).queryByTestId('memory-9')).toBeNull()
        expect(
            within(section)
                .getAllByRole('button')
                .map((b) => b.textContent),
        ).toEqual(['Renew'])
    })
})

describe('LessonsWrong', () => {
    it('leads to the lessons, where the one reported wrong comes first', async () => {
        await renderOver(<LessonsWrong />, {})
        expect(screen.getByRole('link', { name: 'memory page' }).getAttribute('href')).toBe('/memory')
    })
})
