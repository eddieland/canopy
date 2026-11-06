import { QueryClient } from '@tanstack/react-query'
import { cleanup, screen, within } from '@testing-library/react'
import { afterEach, describe, expect, it } from 'vitest'

import { mockEpicDetails } from '@/api/mocks'
import type { EpicDetail } from '@/api/types'
import { setListOrder } from '@/lib/list-order'
import { renderRouted } from '@/test-utils'

import { EpicStory } from './epic-story'

afterEach(() => {
    cleanup()
    setListOrder('conversation', 'oldest')
})

/** The mock epic numbered `id`, with `fields` over it. */
function detail(id: number, fields: Partial<EpicDetail> = {}): EpicDetail {
    const found = mockEpicDetails.find((d) => d.epic.id === id)
    if (found === undefined) {
        throw new Error(`no mock epic:${String(id)}`)
    }
    return { ...found, ...fields }
}

async function story(shown: EpicDetail) {
    await renderRouted(<EpicStory detail={shown} />, {
        client: new QueryClient({ defaultOptions: { queries: { enabled: false } } }),
    })
    return within(screen.getByTestId('conversation')).getAllByRole('listitem')
}

describe('EpicStory', () => {
    it("heads the story with the operator's goal, then each plan run's words and their replies, in time", async () => {
        const items = await story(detail(2))
        expect(items.map((item) => item.dataset.testid)).toEqual([
            'instruction',
            'plan-run-2',
            'message-20',
            'plan-run-3',
        ])
        expect(items[0]?.textContent).toContain('epic:2')
        expect(items[0]?.textContent).toContain("Show a customer's order history in the mobile app")
        expect(items[1]?.textContent).toContain('epic:2#2')
        expect(items[1]?.textContent).toContain('A plan of two entries, one per repository.')
        expect(items[2]?.dataset.source).toBe('operator')
        expect(items[2]?.textContent).toContain('reply via web')
    })

    it('flips to newest first, the goal at its far end', async () => {
        setListOrder('conversation', 'newest')
        const items = await story(detail(2))
        expect(items.map((item) => item.dataset.testid)).toEqual([
            'plan-run-3',
            'message-20',
            'plan-run-2',
            'instruction',
        ])
    })

    it('has nothing from a plan run still working, which has said nothing yet', async () => {
        const items = await story(detail(3))
        expect(items.map((item) => item.dataset.testid)).toEqual(['instruction'])
    })

    it('marks the question the newest plan run asked as waiting on you until a reply follows it', async () => {
        const [run] = detail(3).runs
        if (run === undefined) {
            throw new Error('a plan run')
        }
        const asked = {
            ...run,
            status: 'blocked',
            state: 'blocked' as const,
            ended_at: '2026-10-08T12:10:00Z',
            question: 'Keep the `flags` table as a fallback?',
        }
        let items = await story(detail(3, { runs: [asked] }))
        const open = screen.getByTestId('plan-run-4')
        expect(items).toContain(open)
        expect(within(open).getByText('waiting on you')).toBeTruthy()
        expect(open.textContent).toContain('question')
        cleanup()
        const reply = { ...detail(2).messages[0], id: 21, at: '2026-10-08T12:20:00Z' } as EpicDetail['messages'][number]
        items = await story(detail(3, { runs: [asked], messages: [reply] }))
        const answered = screen.getByTestId('plan-run-4')
        expect(items).toContain(answered)
        expect(within(answered).queryByText('waiting on you')).toBeNull()
    })
})
