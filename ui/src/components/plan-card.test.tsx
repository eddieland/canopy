import { cleanup, screen } from '@testing-library/react'
import { afterEach, describe, expect, it } from 'vitest'

import type { PlanSummary, TicketPlans } from '@/api/types'
import { renderRouted } from '@/test-utils'

import { PlanCard } from './plan-card'

const PLAN: PlanSummary = {
    id: 2,
    run_id: 41,
    status: 'proposed',
    created_at: '2026-10-08T11:00:00Z',
    approved_at: null,
    approved_channel: null,
}

const PLANS: TicketPlans = {
    needed: true,
    setting: null,
    policy: 'approve',
    planning: null,
    changes_asked: null,
    plans: [PLAN],
    newest: {
        plan: PLAN,
        path: '/state/plans/ABC-1/41.md',
        text: '# Plan\n',
        problem: null,
        sha256: 'abc',
        edited: false,
        changed_since_approval: false,
    },
    threads: [
        {
            id: 1,
            quote: 'a',
            prefix: '',
            suffix: '',
            body: 'Why?',
            at: '2026-10-08T11:10:00Z',
            resolved: false,
            replies: [],
        },
        {
            id: 2,
            quote: 'b',
            prefix: '',
            suffix: '',
            body: 'Done.',
            at: '2026-10-08T11:20:00Z',
            resolved: true,
            replies: [],
        },
    ],
}

afterEach(cleanup)

async function renderCard(plans: Partial<TicketPlans> = {}) {
    await renderRouted(<PlanCard ticketKey="ABC-1" plans={{ ...PLANS, ...plans }} />, { at: '/tickets/ABC-1' })
}

describe('PlanCard', () => {
    it('says where the plan stands, which it is, who wrote it, and how many comments are open', async () => {
        await renderCard()
        const card = await screen.findByTestId('plan-card')
        expect(card.textContent).toContain('proposed')
        expect(card.textContent).toContain('plan:2')
        expect(screen.getByRole('link', { name: 'run:41' })).toBeTruthy()
        expect(card.textContent).toMatch(/open comments1/u)
        expect(card.textContent).toContain('It waits on you')
    })

    it("opens the plan's own page, and edits and decides nothing itself", async () => {
        await renderCard()
        const open = await screen.findByRole('link', { name: 'Open plan' })
        expect(open.getAttribute('href')).toBe('/tickets/ABC-1/plan')
        expect(screen.queryByRole('button', { name: /Approve|Skip/u })).toBeNull()
        expect(screen.queryByRole('textbox')).toBeNull()
    })

    it('says a plan is needed while none is written, and which run writes one', async () => {
        await renderCard({ newest: null, plans: [], threads: [], planning: 7 })
        const card = await screen.findByTestId('plan-card')
        expect(card.textContent).toContain('needed')
        expect(card.textContent).toContain('Run 7 is writing a new plan.')
    })
})
