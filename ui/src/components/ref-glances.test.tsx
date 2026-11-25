import { QueryClient } from '@tanstack/react-query'
import { act, cleanup, screen, waitFor, within } from '@testing-library/react'
import type { Middleware } from 'openapi-fetch'
import { afterEach, describe, expect, it } from 'vitest'

import { api } from '@/api/client'
import { mockRuns, mockTickets } from '@/api/mocks'
import { keys } from '@/api/queries'
import type { Run } from '@/api/types'
import { Glance, GlanceCard } from '@/components/glance'
import { RunLink } from '@/components/run-link'
import { TicketLink } from '@/components/ticket-link'
import { renderRouted } from '@/test-utils'

const RUN = mockRuns[0] as Run

// Every request the page makes, answered by `answer`, and counted.
function serve(answer: () => Response): { asked: string[]; stop: () => void } {
    const asked: string[] = []
    const middleware: Middleware = {
        onRequest({ request }) {
            asked.push(new URL(request.url).pathname)
            return answer()
        },
    }
    api.use(middleware)
    return { asked, stop: () => api.eject(middleware) }
}

function focus(name: string) {
    act(() => {
        screen.getByRole('link', { name }).focus()
    })
}

afterEach(cleanup)

describe('a reference’s hover card', () => {
    it('shows a run at a glance when its link has the focus, and still opens its page', async () => {
        const client = new QueryClient()
        client.setQueryData(keys.run(41), RUN)
        await renderRouted(<RunLink id={41} />, { client })
        const link = screen.getByRole('link', { name: 'run:41' })
        expect(link.getAttribute('href')).toBe('/workspace/runs/41')
        expect(screen.queryByTestId('run-card')).toBeNull()

        focus('run:41')
        const card = await waitFor(() => screen.getByTestId('run-card'))
        expect(card.textContent).toContain('run:41')
        expect(card.textContent).toContain('run:41running')
        expect(card.textContent).toContain('Sign in with SSO')
        expect(card.textContent).toContain('ABC-101')
        expect(card.textContent).toContain('implement')
        // A preview, never a place to act: it holds no link and no control.
        expect(card.querySelector('a, button, input, select, textarea, [role], [tabindex]')).toBeNull()
    })

    it("says what kind of run it is in chips, and draws a running run's steps as a meter", async () => {
        const steps = [
            { title: 'add the SSO callback', status: 'done' as const, stage: null, stuck_at: null },
            { title: 'wire the login button', status: 'working' as const, stage: null, stuck_at: null },
        ]
        const client = new QueryClient()
        client.setQueryData(keys.run(41), { ...RUN, private: true, card: RUN.card && { ...RUN.card, steps } })
        await renderRouted(<RunLink id={41} />, { client })
        focus('run:41')
        const card = within(await waitFor(() => screen.getByTestId('run-card')))
        expect(card.getByText('implement')).toBeDefined()
        expect(card.getByText('canopy')).toBeDefined()
        expect(card.getByText('private')).toBeDefined()
        expect(card.getByTestId('progress-meter').textContent).toBe('1 of 2 steps done')
    })

    it('reads nothing until its card opens, then reads what its page reads', async () => {
        const served = serve(() => Response.json(RUN))
        try {
            await renderRouted(<RunLink id={41} />)
            expect(served.asked).toEqual([])
            focus('run:41')
            const card = await waitFor(() => screen.getByTestId('run-card'))
            await waitFor(() => expect(card.textContent).toContain('Sign in with SSO'))
            expect(served.asked).toEqual(['/api/runs/41'])
        } finally {
            served.stop()
        }
    })

    it('says why when it could not be read', async () => {
        const served = serve(() => Response.json({ detail: 'no such run' }, { status: 404 }))
        try {
            await renderRouted(<RunLink id={41} />, {
                client: new QueryClient({ defaultOptions: { queries: { retry: false } } }),
            })
            focus('run:41')
            const card = await waitFor(() => screen.getByTestId('run-card'))
            await waitFor(() =>
                expect(card.textContent).toContain('could not read it: the server answered 404: no such run'),
            )
        } finally {
            served.stop()
        }
    })

    it('says a ticket waits on the operator, in those words', async () => {
        const ticket = { ...mockTickets[0], key: 'ABC-102', awaiting: 5, running_run: null, done: false }
        const client = new QueryClient()
        client.setQueryData(keys.ticket('ABC-102'), {
            ticket,
            units: [{ repo: 'web', phase: 'ci_failing', pr_url: 'https://github.com/acme/web/pull/88' }],
            cost: { cost_usd: 1.5, runs: 2, reviews: 0, priced: 2, models: [], unread_cost_usd: null },
        })
        await renderRouted(<TicketLink ticketKey="ABC-102" />, { client })
        focus('ABC-102')
        const card = await waitFor(() => screen.getByTestId('ticket-card'))
        expect(card.textContent).toContain('waiting on you')
        expect(card.textContent).toContain('acme/web#88 · ci failing')
        expect(card.textContent).toContain('$1.50 over 2 runs')
    })

    it('opens no card of its own inside another card', async () => {
        const client = new QueryClient()
        client.setQueryData(keys.run(41), RUN)
        await renderRouted(
            <Glance
                testId="outer"
                card={
                    <GlanceCard title="outer">
                        <RunLink id={41} />
                    </GlanceCard>
                }
            >
                <a href="#outer">outer link</a>
            </Glance>,
            { client },
        )
        focus('outer link')
        await waitFor(() => screen.getByTestId('outer'))
        focus('run:41')
        expect(screen.queryByTestId('run-card')).toBeNull()
    })
})
