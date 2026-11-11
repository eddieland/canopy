import { cleanup, fireEvent, screen, waitFor, within } from '@testing-library/react'
import type { Middleware } from 'openapi-fetch'
import { afterEach, beforeEach, describe, expect, it } from 'vitest'

import { api } from '@/api/client'
import type { PlanSummary, TicketPlans } from '@/api/types'
import { STORAGE_KEY } from '@/lib/plan-picks'
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
    epic_plan: null,
}

const PLANS: TicketPlans = {
    needed: true,
    setting: null,
    trivial: null,
    policy: 'approve',
    planning: null,
    changes_asked: null,
    plans: [PLAN],
    newest: {
        plan: PLAN,
        path: '/state/plans/ABC-1/41.md',
        archive_name: '41-PROPOSED-a-plan.md',
        text: '# Plan\n',
        problem: null,
        sha256: 'abc',
        edited: false,
        changed_since_approval: false,
        ticket_changed: [],
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
            read: false,
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
            read: false,
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
    // The picks on a plan's open decisions are this browser's: none carries from one test to the next.
    localStorage.clear()
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

    it('offers Approve again for a plan whose ticket changed since, and says what changed', async () => {
        const approved = { ...PLAN, status: 'approved' as const, approved_at: '2026-10-08T11:30:00Z' }
        const newest =
            PLANS.newest === null
                ? null
                : { ...PLANS.newest, plan: approved, ticket_changed: ['title' as const, 'description' as const] }
        await renderCard({ newest })
        const card = await screen.findByTestId('plan-card')
        expect(card.textContent).toContain(
            'Its ticket’s title and description changed since you approved it: approve it again if it still fits.',
        )
        fireEvent.click(await screen.findByRole('button', { name: 'Approve' }))
        await screen.findByRole('status')
        expect(sent).toEqual([{ path: '/api/tickets/ABC-1/plan', body: { action: 'approve' } }])
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

    it('says a trivial member of an epic needs no plan, and why on hover', async () => {
        await renderCard({
            newest: null,
            plans: [],
            threads: [],
            needed: false,
            trivial: 'B4: a one-line config change',
        })
        await screen.findByTestId('plan-card')
        expect(screen.getByText('not needed').closest('[title]')?.getAttribute('title')).toBe(
            "Its epic's plan marks it trivial (B4: a one-line config change): " +
                'your approval of that plan stands for its own.',
        )
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

    describe("the plan's open decisions", () => {
        const DECIDING = [
            '# Plan',
            '',
            '## Decisions',
            '',
            '### Decision 1: Which encoding the file is in',
            '',
            '- **A (chosen):** UTF-8, as the other exports are.',
            '- **B:** Latin-1, for the old spreadsheet.',
            '',
        ].join('\n')
        const SECOND = [
            '### Decision 2: Where the file is written',
            '',
            '- **A (chosen):** Beside the report.',
            '- **B:** In the exports folder.',
            '',
        ].join('\n')
        const ANSWER = 'Decision 1 (Which encoding the file is in): take B, not A.'

        function deciding(text = DECIDING, plan = PLAN): Partial<TicketPlans> {
            return { newest: PLANS.newest === null ? null : { ...PLANS.newest, plan, text }, plans: [plan] }
        }

        it("asks each over Approve, the planner's choice picked, and approves as planned with no note", async () => {
            await renderCard(deciding())
            const decisions = await screen.findByRole('region', { name: 'Open decisions' })
            const group = within(decisions).getByRole('radiogroup', {
                name: 'Decision 1: Which encoding the file is in',
            })
            const radios = within(group).getAllByRole('radio')
            expect(radios.map((radio) => radio.getAttribute('aria-checked'))).toEqual(['true', 'false'])
            expect(within(group).getByRole('radio', { name: /^A: UTF-8.*, recommended$/u })).toBe(radios[0])
            // Its own words say whose choices it takes, and so does the line beside it.
            expect(screen.queryByRole('button', { name: 'Approve' })).toBeNull()
            expect(screen.getByTestId('plan-card').textContent).toContain(
                "Approving takes the planner's choice on its open decision. " +
                    'Its 1 open comment is not sent: open the plan to ask for changes.',
            )
            fireEvent.click(screen.getByRole('button', { name: 'Approve as planned' }))
            await screen.findByRole('status')
            expect(sent).toEqual([{ path: '/api/tickets/ABC-1/plan', body: { action: 'approve' } }])
        })

        it('approves with another option picked as a note for the implement, and says it went', async () => {
            await renderCard({ ...deciding(), threads: [] })
            fireEvent.click(await screen.findByRole('radio', { name: /^B: Latin-1/u }))
            expect(screen.getByTestId('plan-card').textContent).toContain(
                'Approving sends your answer to the implement. Open the plan to ask the planner for changes instead.',
            )
            fireEvent.click(screen.getByRole('button', { name: 'Approve with notes' }))
            expect((await screen.findByRole('status')).textContent).toBe(
                'Plan 2 of ABC-1 is approved as its file stands now. The next tick can implement it. ' +
                    'Your notes went with it, to its implement.',
            )
            expect(sent).toEqual([{ path: '/api/tickets/ABC-1/plan', body: { action: 'approve', message: ANSWER } }])
            // Sent: the plan's page asks none of them again.
            await waitFor(() => expect(localStorage.getItem(STORAGE_KEY)).toBe('{}'))
        })

        it("says whose choice stands on each decision left as the planner's", async () => {
            await renderCard({ ...deciding(`${DECIDING}\n${SECOND}`), threads: [] })
            const card = await screen.findByTestId('plan-card')
            expect(card.textContent).toContain("Approving takes the planner's choice on each of its 2 open decisions.")
            fireEvent.click(screen.getByRole('radio', { name: /^B: In the exports folder/u }))
            expect(card.textContent).toContain(
                "Approving sends your answer to the implement, and takes the planner's choice on the other.",
            )
        })

        it("keeps a pick in this browser, for the plan's page and the next visit", async () => {
            await renderCard(deciding())
            fireEvent.click(await screen.findByRole('radio', { name: /^B: Latin-1/u }))
            cleanup()
            await renderCard(deciding())
            const picked = await screen.findByRole('radio', { name: /^B: Latin-1/u })
            expect(picked.getAttribute('aria-checked')).toBe('true')
            expect(screen.getByRole('button', { name: 'Approve with notes' })).toBeTruthy()
            cleanup()
            // A new plan is asked afresh.
            await renderCard(deciding(DECIDING, { ...PLAN, id: 3 }))
            expect((await screen.findByRole('radio', { name: /^A: UTF-8/u })).getAttribute('aria-checked')).toBe('true')
        })

        it('asks none of a plan that waits on no answer: one approved, or one a planner is replacing', async () => {
            const approved = { ...PLAN, status: 'approved' as const, approved_at: '2026-10-08T11:30:00Z' }
            const changed =
                PLANS.newest === null
                    ? null
                    : { ...PLANS.newest, plan: approved, text: DECIDING, ticket_changed: ['title' as const] }
            await renderCard({ newest: changed, plans: [approved] })
            await screen.findByTestId('plan-card')
            expect(screen.queryByRole('region', { name: 'Open decisions' })).toBeNull()
            expect(screen.getByRole('button', { name: 'Approve' })).toBeTruthy()
            cleanup()

            await renderCard({ ...deciding(), planning: 7 })
            await screen.findByTestId('plan-card')
            expect(screen.queryByRole('region', { name: 'Open decisions' })).toBeNull()
        })
    })
})
