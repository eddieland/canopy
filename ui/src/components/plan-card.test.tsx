import { cleanup, fireEvent, screen } from '@testing-library/react'
import type { Middleware } from 'openapi-fetch'
import { afterEach, beforeEach, describe, expect, it } from 'vitest'

import { api } from '@/api/client'
import { triage } from '@/api/mocks'
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
    triage: null,
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

// Every write the card sends, and the server stand-in's answer to it, as `canopy plan --approve`'s, or as
// `canopy plan`'s when it undoes triage run 7's waiver.
let sent: { path: string; body: unknown }[] = []

const server: Middleware = {
    async onRequest({ request }) {
        if (request.method === 'GET') {
            return Response.json({})
        }
        const body = JSON.parse(await request.text()) as { action: string }
        sent.push({ path: new URL(request.url).pathname, body })
        const { action } = body
        return action === 'request'
            ? Response.json({ action, already: false, plan: null, superseded: null, waived: 7 })
            : Response.json({ action: 'approve', already: false, plan: 2, superseded: null, waived: null })
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

    it("names a triage's waiver while it is in force, why, and how to undo it, as canopy plan does", async () => {
        await renderCard({ newest: null, plans: [], threads: [], triage: triage() })
        const card = await screen.findByTestId('plan-card')
        // Not the operator's skip: the hover says whose word it is.
        expect(screen.getByText('waived').closest('[title]')?.getAttribute('title')).toContain(
            'Triage run 7 judged it trivial',
        )
        expect(screen.getByRole('link', { name: 'run:7' })).toBeTruthy()
        expect(card.textContent).toMatch(/triagerun:7 trivial/u)
        expect(card.textContent).toContain('It fixes one misspelled word in a comment, which policy.trivial names.')
        expect(card.textContent).toContain('Triage waived its plan: the next tick can implement it unplanned.')

        fireEvent.click(screen.getByRole('button', { name: 'Ask for a plan' }))
        expect((await screen.findByRole('status')).textContent).toBe(
            "Triage run 7 had waived ABC-1's plan; it is undone. ABC-1 is planned first: the next tick dispatches a " +
                'planner, and nothing is implemented until you approve its plan.',
        )
        expect(sent).toEqual([{ path: '/api/tickets/ABC-1/plan', body: { action: 'request' } }])
    })

    it('offers no undo once the waived implement has started, and none for a triage that waived nothing', async () => {
        await renderCard({ newest: null, plans: [], threads: [], triage: triage({ undoable: false }) })
        expect((await screen.findByTestId('plan-card')).textContent).toContain(
            'Triage waived its plan, and its implement went ahead unplanned.',
        )
        expect(screen.queryByRole('button', { name: 'Ask for a plan' })).toBeNull()
        cleanup()

        const judged = triage({ verdict: 'plan', waived: false, undoable: false, reason: 'It changes a schema.' })
        await renderCard({ newest: null, plans: [], threads: [], triage: judged })
        const card = await screen.findByTestId('plan-card')
        expect(screen.getByText('needed')).toBeTruthy()
        expect(card.textContent).toMatch(/triagerun:7 needs a plan/u)
        expect(card.textContent).toContain('It changes a schema.')
        expect(card.textContent).toContain('None yet: the next tick dispatches a planner.')
        expect(screen.queryByRole('button', { name: 'Ask for a plan' })).toBeNull()
        cleanup()

        const failed = triage({ status: 'timeout', verdict: null, waived: false, undoable: false, reason: 'timed out' })
        await renderCard({ newest: null, plans: [], threads: [], triage: failed })
        expect((await screen.findByTestId('plan-card')).textContent).toMatch(/triagerun:7 timeout/u)
    })

    it('says which run is judging whether the ticket needs a plan, and nothing it said yet', async () => {
        const running = triage({ status: 'running', verdict: null, waived: false, undoable: false, reason: null })
        await renderCard({ newest: null, plans: [], threads: [], triage: running })
        const card = await screen.findByTestId('plan-card')
        expect(card.textContent).toMatch(/triagerun:7 running/u)
        expect(card.textContent).toContain('Run 7 is judging whether it needs a plan at all.')
        expect(card.textContent).not.toContain('triage said')
    })
})
