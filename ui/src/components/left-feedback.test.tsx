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
        sent.push(await request.clone().json())
        return Response.json({ numbers: [7], message_id: 41, new: true })
    },
}

afterEach(() => {
    api.eject(server)
    sent.length = 0
    cleanup()
})

describe('LeftFeedbackList', () => {
    it('shows nothing for a ticket that left nothing', async () => {
        await renderRouted(<LeftFeedbackList ticketKey="ABC-103" items={[]} />)
        expect(screen.queryByRole('region', { name: 'Feedback left with no worker' })).toBeNull()
    })

    it('names where each item is, who wrote it, why it was left, and the tick that left it', async () => {
        await renderRouted(<LeftFeedbackList ticketKey="ABC-103" items={[left()]} />)
        const row = within(screen.getByTestId('left-feedback')).getByRole('listitem')
        expect(within(row).getByText('src/billing/v1.ts:8')).toBeTruthy()
        expect(within(row).getByText('by carol')).toBeTruthy()
        expect(within(row).getByText('would reset approval')).toBeTruthy()
        expect(within(row).getByRole('link', { name: 'tick:2' })).toBeTruthy()
        expect(within(row).getByRole('link', { name: 'open comment 2468020037 on GitHub' }).getAttribute('href')).toBe(
            `${PR}#discussion_r2468020037`,
        )
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
})
