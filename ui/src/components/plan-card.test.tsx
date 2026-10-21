import { cleanup, fireEvent, screen } from '@testing-library/react'
import type { Middleware } from 'openapi-fetch'
import { afterEach, beforeEach, describe, expect, it } from 'vitest'

import { api } from '@/api/client'
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
    approved_reason: null,
    effort: null,
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
        persona: null,
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

// Every write the card sends, and the server stand-in's answer to it, as `canopy plan --approve`'s.
let sent: { path: string; body: unknown }[] = []

const server: Middleware = {
    async onRequest({ request }) {
        if (request.method === 'GET') {
            return Response.json({})
        }
        const body = JSON.parse(await request.text()) as { action: string }
        sent.push({ path: new URL(request.url).pathname, body })
        return Response.json({ action: 'approve', already: false, plan: 2, superseded: null })
    },
}

beforeEach(() => {
    sent = []
    api.use(server)
})

afterEach(() => {
    api.eject(server)
    cleanup()
})

async function renderCard(plans: Partial<TicketPlans> = {}) {
    await renderRouted(<PlanCard ticketKey="ABC-1" plans={{ ...PLANS, ...plans }} />, { at: '/tickets/ABC-1' })
}

describe('PlanCard', () => {
    it('says where the plan stands in words, which it is, who wrote it, and how many comments are open', async () => {
        await renderCard()
        const card = await screen.findByTestId('plan-card')
        expect(card.textContent).toContain('waiting on you')
        expect(card.textContent).not.toContain('proposed')
        expect(card.textContent).toContain('plan:2')
        expect(screen.getByRole('link', { name: 'run:41' })).toBeTruthy()
        expect(card.textContent).toMatch(/open comments1/u)
        expect(card.textContent).toContain('1 open comment: approving sends none.')
    })

    it('approves a waiting plan as canopy plan --approve does, and says so in its words', async () => {
        await renderCard()
        fireEvent.click(await screen.findByRole('button', { name: 'Approve' }))
        expect((await screen.findByRole('status')).textContent).toBe(
            'Plan 2 of ABC-1 is approved as its file stands now. The next tick can implement it.',
        )
        expect(sent).toEqual([{ path: '/api/tickets/ABC-1/plan', body: { action: 'approve' } }])
    })

    it("opens the plan's own page, and edits nothing itself", async () => {
        await renderCard()
        const open = await screen.findByRole('link', { name: 'Open plan' })
        expect(open.getAttribute('href')).toBe('/tickets/ABC-1/plan')
        expect(screen.queryByRole('button', { name: /Skip/u })).toBeNull()
        expect(screen.queryByRole('textbox')).toBeNull()
    })

    it('offers no Approve for a plan approved and unchanged since, or one a planner is replacing', async () => {
        const approved = { ...PLAN, status: 'approved' as const, approved_at: '2026-10-08T11:30:00Z' }
        const newest = PLANS.newest === null ? null : { ...PLANS.newest, plan: approved }
        await renderCard({ newest })
        expect((await screen.findByTestId('plan-card')).textContent).toContain('approved')
        expect(screen.queryByRole('button', { name: 'Approve' })).toBeNull()
        cleanup()

        await renderCard({ planning: 7 })
        const card = await screen.findByTestId('plan-card')
        expect(card.textContent).toContain('proposed')
        expect(card.textContent).not.toContain('waiting on you')
        expect(screen.queryByRole('button', { name: 'Approve' })).toBeNull()
    })

    it('says the planner approved a plan it said needs no review, and why, and who approved no other', async () => {
        const approved = {
            ...PLAN,
            status: 'approved' as const,
            approved_at: '2026-10-08T11:30:00Z',
            approved_channel: 'planner',
            approved_reason: 'A one-line typo fix in the README.',
        }
        const newest = PLANS.newest === null ? null : { ...PLANS.newest, plan: approved }
        await renderCard({ newest })
        expect((await screen.findByTestId('plan-card')).textContent).toContain(
            'approved bythe planner: A one-line typo fix in the README.',
        )
        cleanup()

        await renderCard()
        expect((await screen.findByTestId('plan-card')).textContent).not.toContain('approved by')
    })

    it('says how much work its planner judged the plan, and nothing when it gave no estimate', async () => {
        const newest = PLANS.newest === null ? null : { ...PLANS.newest, plan: { ...PLAN, effort: 'large' as const } }
        await renderCard({ newest })
        expect((await screen.findByTestId('plan-card')).textContent).toContain('effortlarge')
        cleanup()

        await renderCard()
        expect((await screen.findByTestId('plan-card')).textContent).not.toContain('effort')
    })

    it('says changes are asked of a proposed plan, which waits on the planner now, not on you', async () => {
        await renderCard({ changes_asked: '2026-10-08T11:40:00Z' })
        const card = await screen.findByTestId('plan-card')
        expect(card.textContent).toContain('changes asked')
        expect(card.textContent).not.toContain('waiting on you')
        expect(card.textContent).not.toContain('proposed')
    })

    it('says a plan is needed while none is written, why on hover, and which run writes one', async () => {
        await renderCard({ newest: null, plans: [], threads: [], planning: 7 })
        const card = await screen.findByTestId('plan-card')
        expect(screen.getByText('needed').closest('[title]')?.getAttribute('title')).toBe(
            'policy.plan is approve: every implement waits on a plan you approve.',
        )
        expect(card.textContent).toContain('Run 7 is writing a new plan.')
    })

    it('says changes you asked for in a band of their own, until a planner starts on them', async () => {
        await renderCard({ changes_asked: '2026-10-08T11:40:00Z' })
        const band = await screen.findByRole('region', { name: 'Changes asked' })
        expect(band.textContent).toMatch(
            /^You asked for changes \S+ ago: the next tick asks the planner for a new plan\.$/u,
        )
        expect(screen.getByText('changes asked')).toBeTruthy()
        expect(screen.queryByText('waiting on you')).toBeNull()
        cleanup()

        await renderCard({ changes_asked: '2026-10-08T11:40:00Z', planning: 51 })
        expect((await screen.findByTestId('plan-card')).textContent).toContain('Run 51 is writing a new plan.')
        expect(screen.queryByRole('region', { name: 'Changes asked' })).toBeNull()
        cleanup()

        // A plan put aside on a ticket that needs none now: no planner comes to read them.
        const superseded = { ...PLAN, status: 'superseded' as const }
        const newest = PLANS.newest === null ? null : { ...PLANS.newest, plan: superseded }
        await renderCard({ changes_asked: '2026-10-08T11:40:00Z', needed: false, newest, plans: [superseded] })
        expect((await screen.findByTestId('plan-card')).textContent).toContain('superseded')
        expect(screen.queryByRole('region', { name: 'Changes asked' })).toBeNull()
    })
})
