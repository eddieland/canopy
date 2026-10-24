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
        expect(within(panel).getByText('waiting on you')).toBeTruthy()
        expect(within(panel).getByRole('link', { name: 'run:46' })).toBeTruthy()
        expect(panel.textContent).toContain(
            'its resume acts on the items you approve, and only those. It waits on you.',
        )
        const rows = within(panel).getAllByTestId('feedback-plan-item')
        // Each row leads with what was said, then where it is, then the proposal, who said it, why, and its id.
        expect(rows.map((row) => row.textContent)).toEqual([
            '1.Two small things, then good to go.the reviewleavealicetrustedid 4102337001',
            '2.Can it move into a `finally`?on its threadchangealicetrustedMove it into a `finally`.id 2468013579',
        ])
        // The review opens on its host, in a new tab; the thread's card is on this page, under its anchor.
        const review = within(panel).getByRole<HTMLAnchorElement>('link', { name: 'the review' })
        expect(review.href).toBe('https://github.com/acme/web/pull/88#pullrequestreview-4102337001')
        expect(review.target).toBe('_blank')
        const thread = within(panel).getByRole<HTMLAnchorElement>('link', { name: 'on its thread' })
        expect(thread.getAttribute('href')).toBe(
            '/pull-requests/pr?url=https%3A%2F%2Fgithub.com%2Facme%2Fweb%2Fpull%2F88#thread-PRRT_1',
        )
        for (const n of [1, 2]) {
            expect(screen.getByRole('checkbox', { name: `address item ${n}` }).getAttribute('aria-checked')).toBe(
                'true',
            )
        }
        const approve = screen.getByRole<HTMLButtonElement>('button', { name: 'Approve whole' })
        expect(approve.title).toBe('canopy plan ABC-099 --approve')
        fireEvent.change(screen.getByRole('textbox', { name: 'Your words, for its resume (optional)' }), {
            target: { value: 'Go ahead.' },
        })
        fireEvent.click(approve)
        // The moment it is: the band says what it did, with the way back to Attention, and the words are cleared.
        const moment = await screen.findByTestId('plan-approved')
        expect(within(moment).getByRole('status').textContent).toBe(
            'Feedback plan 1 of ABC-099, covering 2 items, is approved whole as its file stands now. The next tick ' +
                'can resume ABC-099 on it, once. Message 12 on ABC-099 names the items.',
        )
        expect(within(moment).getByRole('link', { name: 'Back to Attention' }).getAttribute('href')).toBe('/attention')
        expect(sent).toEqual([
            { path: '/api/tickets/ABC-099/feedback-plan', body: { items: [], leave: [], message: 'Go ahead.' } },
        ])
        expect(changed).toHaveBeenCalledOnce()
        const words = screen.getByRole<HTMLTextAreaElement>('textbox', {
            name: 'Your words, for its resume (optional)',
        })
        expect(words.value).toBe('')
        // At rest until a box or the words change: the send key approves nothing twice.
        const again = screen.getByRole<HTMLButtonElement>('button', { name: 'Approve again' })
        expect(again.disabled).toBe(true)
        expect(screen.getByText('Tick other items, or write words for its resume, to approve it again.')).toBeTruthy()
        fireEvent.keyDown(words, { key: 'Enter' })
        expect(sent).toHaveLength(1)
        fireEvent.change(words, { target: { value: 'And the tests.' } })
        expect(screen.getByRole<HTMLButtonElement>('button', { name: 'Approve again' }).disabled).toBe(false)
        fireEvent.keyDown(words, { key: 'Enter' })
        await vi.waitFor(() => expect(sent).toHaveLength(2))
        expect(sent[1]?.body).toEqual({ items: [], leave: [], message: 'And the tests.' })
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
        expect(screen.getByRole<HTMLButtonElement>('button', { name: 'Approve' }).disabled).toBe(true)
        expect(screen.getByText('Tick an item to approve, or reply on the ticket to ask for changes.')).toBeTruthy()
    })

    it('says what changed on a stale plan, and its first refusal reads as the step it is, not an error', async () => {
        const said = 'reply 2468013702 on https://github.com/acme/web/pull/88 by bob, answering item 2468013579'
        answer = () =>
            Response.json({ detail: { guard: 'stale', reason: `feedback plan 1 is stale` } }, { status: 409 })
        const plan = feedbackPlan({ status: 'stale', changes: [said] })
        await renderRouted(<FeedbackPlanPanel plan={plan} onChange={changed} />)
        const stale = screen.getByTestId('feedback-plan-stale')
        expect(within(stale).getByText(said)).toBeTruthy()
        expect(stale.textContent).toContain('Approving it now is refused once, naming this')
        const approve = screen.getByRole<HTMLButtonElement>('button', { name: 'Approve stale plan' })
        expect(approve.title).toBe('canopy plan ABC-099 --approve')
        fireEvent.click(approve)
        expect((await screen.findByRole('status')).textContent).toBe(
            'Refused once, as a stale plan is the first time: approve it as it is to go ahead.',
        )
        expect(screen.queryByRole('alert')).toBeNull()
        // Read again, since the refusal is recorded and approving again approves it.
        expect(changed).toHaveBeenCalledOnce()
        cleanup()
        await renderRouted(<FeedbackPlanPanel plan={{ ...plan, stale_shown: true }} onChange={changed} />)
        expect(screen.getByTestId('feedback-plan-stale').textContent).toContain(
            'Approving it again approves it as it is; what changed waits for the next plan.',
        )
        expect(screen.getByRole('button', { name: 'Approve as it is' })).toBeTruthy()
    })

    it('shows any other refusal in the failure color, naming its guard', async () => {
        answer = () =>
            Response.json(
                { detail: { guard: 'bad_plan', reason: 'feedback plan run 48 for ABC-099 is running' } },
                { status: 409 },
            )
        await renderRouted(<FeedbackPlanPanel plan={feedbackPlan()} onChange={changed} />)
        fireEvent.click(screen.getByRole('button', { name: 'Approve whole' }))
        expect((await screen.findByRole('alert')).textContent).toBe(
            'refused (bad_plan): feedback plan run 48 for ABC-099 is running',
        )
        expect(screen.queryByTestId('plan-approved')).toBeNull()
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
        expect(within(panel).getByText('approved')).toBeTruthy()
        // The preamble is down to where it stands, and the message links to the ticket's conversation.
        expect(panel.textContent).not.toContain('its resume acts on the items you approve')
        expect(panel.textContent).toContain('Approved by you')
        expect(panel.textContent).toContain(
            'message 12 on the ticket names its items. The next tick may resume ABC-099 on it, once.',
        )
        expect(within(panel).getByRole('link', { name: 'message 12' }).getAttribute('href')).toBe(
            '/tickets/ABC-099#message-12',
        )
        expect(screen.getByRole('checkbox', { name: 'address item 1' }).getAttribute('aria-checked')).toBe('false')
        expect(screen.getByRole('checkbox', { name: 'address item 2' }).getAttribute('aria-checked')).toBe('true')
        expect(within(panel).getByText('left out')).toBeTruthy()
        const again = screen.getByRole<HTMLButtonElement>('button', { name: 'Approve again' })
        expect(again.disabled).toBe(false)
        expect(again.title).toBe('canopy plan ABC-099 --approve --leave 1')
    })

    it("quotes its planner's reason once, from the command line says so, and ends each sentence once", async () => {
        const planner = feedbackPlan({
            status: 'approved',
            approved_at: '2026-10-08T11:55:00Z',
            approved_channel: 'planner',
            approved_reason: 'Every item is a leave: it changes no code.',
        })
        await renderRouted(<FeedbackPlanPanel plan={planner} onChange={changed} />)
        expect(screen.getByTestId('feedback-plan').textContent).toContain(
            ', saying “Every item is a leave: it changes no code.” The next tick may resume ABC-099 on it, once.',
        )
        expect(screen.getByTestId('feedback-plan').textContent).toContain('Its planner approved it')
        cleanup()
        await renderRouted(
            <FeedbackPlanPanel
                plan={{ ...planner, approved_channel: 'cli', approved_reason: null, approved_message: 13 }}
                onChange={changed}
            />,
        )
        expect(screen.getByTestId('feedback-plan').textContent).toContain('Approved by you, from the command line')
        expect(screen.getByTestId('feedback-plan').textContent).toContain(
            '; message 13 on the ticket names its items. The next tick',
        )
    })

    it('offers nothing to approve while the plan’s file is missing, and says how to get a new one', async () => {
        await renderRouted(
            <FeedbackPlanPanel plan={feedbackPlan({ text: null, problem: 'missing' })} onChange={changed} />,
        )
        expect(screen.getByRole<HTMLButtonElement>('button', { name: 'Approve whole' }).disabled).toBe(true)
        expect(
            screen.getByText(
                'Its file is missing, so nothing can be approved: reply on the ticket to ask for a new plan.',
            ),
        ).toBeTruthy()
        expect(screen.getByTestId('feedback-plan-no-file').textContent).toBe(
            'Its file is missing: /home/op/acme/.canopy/plans/ABC-099/46.md',
        )
        expect(screen.queryByRole('button', { name: 'Show the plan' })).toBeNull()
        fireEvent.keyDown(screen.getByRole('textbox', { name: 'Your words, for its resume (optional)' }), {
            key: 'Enter',
        })
        expect(sent).toEqual([])
    })

    it('says a plan that covers no item does', async () => {
        await renderRouted(<FeedbackPlanPanel plan={feedbackPlan({ items: [] })} onChange={changed} />)
        expect(screen.getByText('It covers no item.')).toBeTruthy()
    })

    it('says when an item said nothing, or is no longer on the PR as read', async () => {
        const plan = feedbackPlan({
            items: [
                feedbackPlanItem({
                    number: 1,
                    item: 'review',
                    thread_id: null,
                    excerpt: null,
                    rationale: null,
                    url: null,
                }),
                feedbackPlanItem({ number: 2, excerpt: null, rationale: null }),
            ],
        })
        await renderRouted(<FeedbackPlanPanel plan={plan} onChange={changed} />)
        const said = screen.getAllByTestId('feedback-plan-said').map((s) => s.textContent)
        expect(said).toEqual(['a review with no words', 'no longer on the PR as read'])
        expect(screen.queryByTestId('feedback-plan-why')).toBeNull()
    })

    it('says when an item said nothing, or is no longer on the PR as read', async () => {
        const plan = feedbackPlan({
            items: [
                feedbackPlanItem({
                    number: 1,
                    item: 'review',
                    thread_id: null,
                    excerpt: null,
                    rationale: null,
                    url: null,
                }),
                feedbackPlanItem({ number: 2, excerpt: null, rationale: null }),
            ],
        })
        await renderRouted(<FeedbackPlanPanel plan={plan} onChange={changed} />)
        const said = screen.getAllByTestId('feedback-plan-said').map((s) => s.textContent)
        expect(said).toEqual(['a review with no words', 'no longer on the PR as read'])
        expect(screen.queryByTestId('feedback-plan-why')).toBeNull()
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
            excerpt: '<script>alert(1)</script> Why 250?',
            rationale: 'The ticket asks for **250**.',
            url: null,
        })
        const text = '# Plan\n\n<img src=x onerror=alert(1)> **not bold**\n'
        await renderRouted(<FeedbackPlanPanel plan={feedbackPlan({ items: [review], text })} onChange={changed} />)
        const row = screen.getByTestId('feedback-plan-item')
        expect(within(row).getByTestId('feedback-plan-reply').textContent).toBe('Proposed replyKept <b>250</b> ms.')
        // What was said and why stay characters: no script, no bold, and no link out for a review with no URL.
        expect(within(row).getByTestId('feedback-plan-said').textContent).toBe('<script>alert(1)</script> Why 250?')
        expect(within(row).getByTestId('feedback-plan-why').textContent).toBe('The ticket asks for **250**.')
        expect(row.querySelector('script, strong')).toBeNull()
        expect(within(row).queryByRole('link')).toBeNull()
        expect(row.textContent).toContain('the review 4102337001')
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
        // The card is what the plan's row links to, under the thread's anchor.
        expect(screen.getByTestId('review-thread').id).toBe('thread-PRRT_1')
        // Above the drafts, which answer it.
        const following = proposal.compareDocumentPosition(screen.getByTestId('draft'))
        expect(following & Node.DOCUMENT_POSITION_FOLLOWING).toBeTruthy()
    })
})
