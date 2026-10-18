import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react'
import type { Middleware } from 'openapi-fetch'
import { afterEach, beforeEach, describe, expect, it } from 'vitest'

import { api } from '@/api/client'
import { keys } from '@/api/queries'
import type { Tick } from '@/api/types'
import { StreamContext } from '@/hooks/use-loop-down'

import { TickNow } from './tick-now'

// Every path the button asked, and what the server stand-in answers next: by default, the tick asked for.
let asked: string[] = []
let answers: Response[] = []

const server: Middleware = {
    onRequest({ request }) {
        asked.push(new URL(request.url).pathname)
        return answers.shift() ?? Response.json({ after_tick: false })
    },
}

beforeEach(() => {
    asked = []
    answers = []
    api.use(server)
})

afterEach(() => {
    api.eject(server)
    cleanup()
})

function renderWith(status: Tick['status'] | null) {
    const client = new QueryClient()
    // Nothing is fetched: the latest tick is what the test seeds.
    client.setQueryDefaults(keys.tick, { enabled: false })
    client.setQueryData(keys.tick, { tick: status === null ? null : ({ id: 7, status } as Tick), acknowledged: null })
    return render(
        <QueryClientProvider client={client}>
            <TickNow />
        </QueryClientProvider>,
    )
}

describe('TickNow', () => {
    it("waits while the loop isn't answering, and says why", async () => {
        const client = new QueryClient()
        client.setQueryDefaults(keys.tick, { enabled: false })
        client.setQueryData(keys.tick, { tick: null, acknowledged: null })
        render(
            <QueryClientProvider client={client}>
                <StreamContext value={{ status: 'reconnecting', downSince: Date.now() - 60_000 }}>
                    <TickNow />
                </StreamContext>
            </QueryClientProvider>,
        )
        const button = screen.getByRole<HTMLButtonElement>('button', { name: 'Tick now' })
        await waitFor(() => {
            expect(button.disabled).toBe(true)
        })
        expect(button.title).toBe("The loop isn't answering: start it with `canopy loop` or `canopy daemon start`.")
    })

    it.each([null, 'ok'] as const)('asks the loop for a tick when the latest is %s', async (status) => {
        renderWith(status)
        const button = screen.getByRole<HTMLButtonElement>('button', { name: 'Tick now' })
        expect(button.disabled).toBe(false)

        fireEvent.click(button)
        await waitFor(() => {
            expect(asked).toEqual(['/api/loop/tick'])
        })
    })

    it('waits while a tick runs', () => {
        renderWith('running')
        const button = screen.getByRole<HTMLButtonElement>('button', { name: 'Tick now' })
        expect(button.disabled).toBe(true)
        expect(button.title).toBe('A tick is running now.')
    })

    it('says why it failed', async () => {
        answers = [new Response('down', { status: 502 })]
        renderWith('ok')
        fireEvent.click(screen.getByRole('button', { name: 'Tick now' }))
        expect(await screen.findByRole('alert')).toBeDefined()
    })
})
