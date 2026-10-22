import { cleanup, fireEvent, screen, within } from '@testing-library/react'
import type { Middleware } from 'openapi-fetch'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

import { api } from '@/api/client'
import { feedbackPlan, feedbackPlanItem, reviewThread } from '@/api/mocks'
import type { FeedbackPlanApproved } from '@/api/types'
import { renderRouted } from '@/test-utils'

import { FeedbackPlanPanel } from './feedback-plan'
import { ThreadCard } from './review-threads'

// Every write sent, by its path, with its body, and what the server stand-in answers it.
let sent: { path: string; body: unknown }[] = []
let answer: () => Response
// What the panel calls once an approval is done, to read again what shows the plan.
const changed = vi.fn<() => void>()

const APPROVED: FeedbackPlanApproved = {
    plan: 1,
    ticket_key: 'ABC-099',
    addressed: [{ number: 2, item_id: 2468013579 }],
    left: [{ number: 1, item_id: 4102337001 }],
    message: 12,
}

const server: Middleware = {
    async onRequest({ request }) {
        const url = new URL(request.url)
        if (request.method !== 'GET') {
            const text = await request.text()
            sent.push({ path: url.pathname, body: text ? JSON.parse(text) : null })
        }
        return answer()
    },
}

beforeEach(() => {
    sent = []
    changed.mockClear()
    answer = () => Response.json(APPROVED)
    api.use(server)
})

afterEach(() => {
    api.eject(server)
    cleanup()
})

describe('FeedbackPlanPanel', () => {
    it('shows a waiting plan, an item a row each, every one ticked, and approves it whole', async () => {
        answer = () => Response.json({ ...APPROVED, addressed: [...APPROVED.addressed, ...APPROVED.left], left: [] })
        await renderRouted(<FeedbackPlanPanel plan={feedbackPlan()} onChange={changed} />)
        const panel = screen.getByTestId('feedback-plan')
        expect(within(panel).getByText('waiting')).toBeTruthy()
        expect(within(panel).getByRole('link', { name: 'run:46' })).toBeTruthy()
        const rows = within(panel).getAllByTestId('feedback-plan-item')
        expect(rows.map((row) => row.textContent)).toEqual([
            '1. id 4102337001leavealicetrustedthe review 4102337001',
            '2. id 2468013579changealicetrustedon its thread',
        ])
        for (const n of [1, 2]) {
            expect(screen.getByRole('checkbox', { name: `address item ${n}` }).getAttribute('aria-checked')).toBe(
                'true',
            )
        }
        const approve = screen.getByRole<HTMLButtonElement>('button', { name: 'Approve whole' })
        expect(approve.title).toBe('canopy plan ABC-099 --approve')
        fireEvent.click(approve)
        expect((await screen.findByRole('status')).textContent).toBe(
            'Feedback plan 1 of ABC-099, covering 2 items, is approved whole as its file stands now. The next tick ' +
                'can resume ABC-099 on it, once. Message 12 on ABC-099 names the items.',
        )
        expect(sent).toEqual([
            { path: '/api/tickets/ABC-099/feedback-plan', body: { items: [], leave: [], message: null } },
        ])
        expect(changed).toHaveBeenCalledOnce()
    })

    it('approves only the ticked items, with the operator’s words, as --leave names the rest', async () => {
        await renderRouted(<FeedbackPlanPanel plan={feedbackPlan()} onChange={changed} />)
        fireEvent.click(screen.getByRole('checkbox', { name: 'address item 1' }))
        fireEvent.change(screen.getByRole('textbox', { name: 'Your words, for its resume (optional)' }), {
            target: { value: 'Keep the old name too.' },
        })
        const approve = screen.getByRole<HTMLButtonElement>('button', { name: 'Approve 1 of 2' })
        expect(approve.title).toBe('canopy plan ABC-099 --approve --leave 1 --message TEXT')
        fireEvent.click(approve)
        expect((await screen.findByRole('status')).textContent).toBe(
            'Feedback plan 1 of ABC-099 is approved as its file stands now, for 1 of its 2 items: item 2 (id ' +
                '2468013579). The next tick can resume ABC-099 on it, once. Left out, for the next plan: item 1 (id ' +
                '4102337001). Message 12 on ABC-099 names the items.',
        )
        expect(sent.map((s) => s.body)).toEqual([{ items: [], leave: [1], message: 'Keep the old name too.' }])
    })

    it('approves nothing with every item unticked', async () => {
        await renderRouted(<FeedbackPlanPanel plan={feedbackPlan()} onChange={changed} />)
        fireEvent.click(screen.getByRole('checkbox', { name: 'address item 1' }))
        fireEvent.click(screen.getByRole('checkbox', { name: 'address item 2' }))
        expect(screen.getByRole<HTMLButtonElement>('button', { name: 'Approve 0 of 2' }).disabled).toBe(true)
        expect(screen.getByText('Tick an item to approve, or reply on the ticket to ask for changes.')).toBeTruthy()
    })

    it('says what changed on a stale plan, and a refusal names its guard', async () => {
        const said = 'reply 2468013702 on https://github.com/acme/web/pull/88 by bob, answering item 2468013579'
        answer = () =>
            Response.json({ detail: { guard: 'stale', reason: `feedback plan 1 is stale` } }, { status: 409 })
        const plan = feedbackPlan({ status: 'stale', changes: [said] })
        await renderRouted(<FeedbackPlanPanel plan={plan} onChange={changed} />)
        const stale = screen.getByTestId('feedback-plan-stale')
        expect(within(stale).getByText(said)).toBeTruthy()
        expect(stale.textContent).toContain('Approving it now is refused once, naming this')
        fireEvent.click(screen.getByRole('button', { name: 'Approve whole' }))
        expect((await screen.findByRole('alert')).textContent).toBe('refused (stale): feedback plan 1 is stale')
        // Read again, since the refusal is recorded and approving again approves it.
        expect(changed).toHaveBeenCalledOnce()
        cleanup()
        await renderRouted(<FeedbackPlanPanel plan={{ ...plan, stale_shown: true }} onChange={changed} />)
        expect(screen.getByTestId('feedback-plan-stale').textContent).toContain(
            'Approving it again approves it as it is; what changed waits for the next plan.',
        )
    })

    it('ticks an approved plan’s items as its approval left them, and says how it was approved', async () => {
        const plan = feedbackPlan({
            status: 'approved',
            approved_at: '2026-10-08T11:55:00Z',
            approved_channel: 'web',
            approved_message: 12,
            items: [feedbackPlanItem({ number: 1, left_out: true }), feedbackPlanItem()],
        })
        await renderRouted(<FeedbackPlanPanel plan={plan} onChange={changed} />)
        const panel = screen.getByTestId('feedback-plan')
        expect(panel.textContent).toContain('Approved via web')
        expect(panel.textContent).toContain('message 12 names its items. The next tick may resume ABC-099 on it, once.')
        expect(screen.getByRole('checkbox', { name: 'address item 1' }).getAttribute('aria-checked')).toBe('false')
        expect(screen.getByRole('checkbox', { name: 'address item 2' }).getAttribute('aria-checked')).toBe('true')
        expect(within(panel).getByText('left out')).toBeTruthy()
        expect(screen.getByRole('button', { name: 'Approve 1 of 2' })).toBeTruthy()
    })

    it('offers nothing to approve once a resume spent the plan', async () => {
        await renderRouted(
            <FeedbackPlanPanel plan={feedbackPlan({ status: 'spent', spent_run: 47 })} onChange={changed} />,
        )
        const panel = screen.getByTestId('feedback-plan')
        expect(within(panel).getByRole('link', { name: 'run:47' })).toBeTruthy()
        expect(panel.textContent).toContain('went ahead on it; feedback since then waits for the next plan.')
        expect(screen.queryByRole('checkbox')).toBeNull()
        expect(screen.queryByRole('button', { name: /^Approve/u })).toBeNull()
        expect(within(panel).getAllByTestId('feedback-plan-item')).toHaveLength(2)
    })

    it("shows an item no thread shows with its reply in its row, and the plan's file as text", async () => {
        const review = feedbackPlanItem({
            number: 1,
            item: 'review',
            item_id: 4102337001,
            proposal: 'decline',
            reply: 'Kept <b>250</b> ms.',
            thread_id: null,
        })
        const text = '# Plan\n\n<img src=x onerror=alert(1)> **not bold**\n'
        await renderRouted(<FeedbackPlanPanel plan={feedbackPlan({ items: [review], text })} onChange={changed} />)
        expect(screen.getByTestId('feedback-plan-item').textContent).toContain('Kept <b>250</b> ms.')
        fireEvent.click(screen.getByRole('button', { name: 'Show the plan' }))
        const shown = screen.getByTestId('feedback-plan-text')
        // Its HTML stays its characters, and Markdown is not drawn.
        expect(shown.textContent).toBe(text)
        expect(shown.querySelector('img')).toBeNull()
        expect(shown.querySelector('strong')).toBeNull()
    })
})

describe("ThreadCard's proposal", () => {
    it('carries the plan’s proposal for its thread above its drafts, its reply as text', async () => {
        const item = feedbackPlanItem({ left_out: true })
        await renderRouted(<ThreadCard thread={reviewThread()} item={item} onChange={changed} />)
        const proposal = screen.getByTestId('plan-proposal')
        expect(proposal.textContent).toBe('Plan item 2changeleft outMoved it into a `finally`.')
        // Above the drafts, which answer it.
        const following = proposal.compareDocumentPosition(screen.getByTestId('draft'))
        expect(following & Node.DOCUMENT_POSITION_FOLLOWING).toBeTruthy()
    })
})
