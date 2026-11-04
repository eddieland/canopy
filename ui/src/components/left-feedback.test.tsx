import { cleanup, fireEvent, screen, within } from '@testing-library/react'
import type { Middleware } from 'openapi-fetch'
import { afterEach, describe, expect, it } from 'vitest'

import { api } from '@/api/client'
import type { LeftFeedback } from '@/api/types'
import { renderRouted } from '@/test-utils'

import { LeftFeedbackList } from './left-feedback'

const PR = 'https://github.com/acme/web/pull/91'

function left(over: Partial<LeftFeedback> = {}): LeftFeedback {
    return {
        number: 7,
        repo: 'web',
        pr_url: PR,
        item: 'comment',
        id: 2_468_020_037,
        author: 'carol',
        path: 'src/billing/v1.ts',
        line: 8,
        url: `${PR}#discussion_r2468020037`,
        body: 'Could the v1 shim go in a follow-up instead?',
        reason: 'would_reset_approval',
        decider: 'overseer',
        tick_id: 2,
        ...over,
    }
}

// What the server was sent, and what it answers: the reply `canopy send KEY N` records.
const sent: unknown[] = []
const server: Middleware = {
    async onRequest({ request }) {
        const body = (await request.clone().json()) as { numbers: number[] }
        sent.push(body)
        return Response.json({ numbers: body.numbers, message_id: 41, new: true })
    },
}

afterEach(() => {
    api.eject(server)
    sent.length = 0
    cleanup()
})

describe('LeftFeedbackList', () => {
    it('is its header alone, counting none, for a ticket that left nothing', async () => {
        await renderRouted(<LeftFeedbackList ticketKey="ABC-103" items={[]} />)
        const panel = screen.getByRole('region', { name: 'Left feedback' })
        expect(within(panel).getByRole('heading', { name: 'Left feedback' })).toBeTruthy()
        expect(within(panel).getByText('0')).toBeTruthy()
        expect(within(panel).queryByRole('list')).toBeNull()
    })

    it('heads its panel with how many are left', async () => {
        await renderRouted(<LeftFeedbackList ticketKey="ABC-103" items={[left(), left({ number: 8, id: 9 })]} />)
        const panel = screen.getByRole('region', { name: 'Left feedback' })
        expect(within(panel).getByText('2')).toBeTruthy()
        expect(within(panel).getAllByRole('listitem')).toHaveLength(2)
    })

    it('names why each was left, who wrote it, its first line, where it is, and the tick that left it', async () => {
        await renderRouted(
            <LeftFeedbackList
                ticketKey="ABC-103"
                items={[left({ body: '\nCould the v1 shim go in a follow-up instead?\n\nIt is a big diff.' })]}
            />,
        )
        const row = within(screen.getByTestId('left-feedback')).getByRole('listitem')
        expect(within(row).getByText('would reset approval')).toBeTruthy()
        expect(within(row).getByText('carol')).toBeTruthy()
        expect(within(row).getByText('Could the v1 shim go in a follow-up instead?')).toBeTruthy()
        expect(within(row).queryByText(/big diff/u)).toBeNull()
        expect(within(row).getByRole('link', { name: 'tick:2' })).toBeTruthy()
        const where = within(row).getByRole('link', { name: 'src/billing/v1.ts:8 on GitHub' })
        expect(where.getAttribute('href')).toBe(`${PR}#discussion_r2468020037`)
        expect(where.textContent).toBe('v1.ts:8')
        expect(within(row).queryByText(/left by/u)).toBeNull()
    })

    it('names a review by what it is, and an item GitHub gave no link as text, linking nowhere', async () => {
        await renderRouted(
            <LeftFeedbackList
                ticketKey="ABC-103"
                items={[left({ item: 'review', path: null, line: null, url: null, author: null })]}
            />,
        )
        const row = within(screen.getByTestId('left-feedback')).getByRole('listitem')
        expect(within(row).getByText('review')).toBeTruthy()
        expect(within(row).getByText('unknown')).toBeTruthy()
        expect(
            within(row)
                .getAllByRole('link')
                .map((link) => link.textContent),
        ).toEqual(['tick:2'])
        expect(within(row).getByRole('button', { name: 'send review to a worker' })).toBeTruthy()
    })

    it('links what the comment links to, as text it shows rather than markup', async () => {
        const body = 'See https://example.com/spec and <b>this</b>'
        await renderRouted(<LeftFeedbackList ticketKey="ABC-103" items={[left({ body })]} />)
        const row = within(screen.getByTestId('left-feedback')).getByRole('listitem')
        expect(within(row).getByRole('link', { name: 'https://example.com/spec' })).toBeTruthy()
        expect(row.querySelector('b')).toBeNull()
        expect(row.textContent).toContain('<b>this</b>')
    })

    it('sends an item to a worker by its number, and says so in the words the CLI does', async () => {
        api.use(server)
        await renderRouted(<LeftFeedbackList ticketKey="ABC-103" items={[left()]} />)
        fireEvent.click(screen.getByRole('button', { name: 'send src/billing/v1.ts:8 to a worker' }))
        const said = await screen.findByRole('status')
        expect(said.textContent).toBe(
            'ABC-103 feedback 7 went to it as message 41: the next tick reads it as your go-ahead.',
        )
        expect(sent).toEqual([{ numbers: [7], submission: expect.any(String) as unknown }])
    })

    it('sends every item in one reply from its header, and says so in the words the CLI does', async () => {
        api.use(server)
        await renderRouted(<LeftFeedbackList ticketKey="ABC-103" items={[left(), left({ number: 8, id: 9 })]} />)
        fireEvent.click(screen.getByRole('button', { name: 'send all 2' }))
        const said = await screen.findByRole('status')
        expect(said.textContent).toBe(
            'ABC-103 feedback 7, 8 went to it as message 41: the next tick reads it as your go-ahead.',
        )
        expect(sent).toEqual([{ numbers: [7, 8], submission: expect.any(String) as unknown }])
    })

    it('leaves out of send-all what the head already does, which its own row still sends', async () => {
        api.use(server)
        const items = [left(), left({ number: 8, id: 8, reason: 'already_done' }), left({ number: 9, id: 9 })]
        await renderRouted(<LeftFeedbackList ticketKey="ABC-103" items={items} />)
        fireEvent.click(screen.getByRole('button', { name: 'send all 2' }))
        await screen.findByRole('status')
        expect(sent).toEqual([{ numbers: [7, 9], submission: expect.any(String) as unknown }])
    })

    it('offers no send-all when one item at most is not already done', async () => {
        const items = [left(), left({ number: 8, id: 8, reason: 'already_done' })]
        await renderRouted(<LeftFeedbackList ticketKey="ABC-103" items={items} />)
        expect(screen.queryByRole('button', { name: /^send all/u })).toBeNull()
        expect(screen.getAllByRole('button', { name: /to a worker$/u })).toHaveLength(2)
    })

    it('offers no send-all for a single item', async () => {
        await renderRouted(<LeftFeedbackList ticketKey="ABC-103" items={[left()]} />)
        expect(screen.queryByRole('button', { name: /^send all/u })).toBeNull()
    })

    it('sends the oldest 20 past the most one reply names, and says so on its button', async () => {
        api.use(server)
        const items = Array.from({ length: 22 }, (_, at) => left({ number: at + 1, id: at + 1 }))
        await renderRouted(<LeftFeedbackList ticketKey="ABC-103" items={items} />)
        fireEvent.click(screen.getByRole('button', { name: 'send oldest 20' }))
        await screen.findByRole('status')
        expect(sent).toEqual([
            { numbers: Array.from({ length: 20 }, (_, at) => at + 1), submission: expect.any(String) as unknown },
        ])
    })

    it('says to read them before you merge while the ticket waits on your merge', async () => {
        await renderRouted(<LeftFeedbackList ticketKey="ABC-103" items={[left()]} merging />)
        const panel = screen.getByRole('region', { name: 'Left feedback' })
        expect(within(panel).getByText(/^Read these before you merge/u)).toBeTruthy()
    })

    it('says nothing of merging while the ticket does not wait on it, or with nothing left', async () => {
        await renderRouted(<LeftFeedbackList ticketKey="ABC-103" items={[left()]} />)
        expect(screen.queryByText(/before you merge/u)).toBeNull()
        cleanup()
        await renderRouted(<LeftFeedbackList ticketKey="ABC-103" items={[]} merging />)
        expect(screen.queryByText(/before you merge/u)).toBeNull()
    })
})
