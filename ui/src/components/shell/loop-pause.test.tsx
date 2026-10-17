import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react'
import type { Middleware } from 'openapi-fetch'
import { afterEach, beforeEach, describe, expect, it } from 'vitest'

import { api } from '@/api/client'
import { keys } from '@/api/queries'
import type { LoopState } from '@/api/types'
import { StreamContext } from '@/hooks/use-loop-down'

import { LoopPause } from './loop-pause'

const SINCE = '2026-10-08T11:57:00Z'
const RUNNING: LoopState = { memory: null, notice: null, paused: null }
const PAUSED: LoopState = { memory: null, notice: null, paused: { channel: 'cli', since: SINCE } }

// Every request the button sends, and what the server stand-in answers each.
let sent: string[] = []
let answer: Response | undefined

const server: Middleware = {
    onRequest({ request }) {
        sent.push(`${request.method} ${new URL(request.url).pathname}`)
        return answer
    },
}

beforeEach(() => {
    sent = []
    answer = undefined
    api.use(server)
})

afterEach(() => {
    api.eject(server)
    cleanup()
})

function renderPause(loop: LoopState | undefined, downSince: number | null = null) {
    const client = new QueryClient()
    // Nothing is fetched: the loop's state is what the test seeds, as the stream would send it.
    client.setQueryDefaults(keys.loop, { enabled: false })
    if (loop !== undefined) {
        client.setQueryData(keys.loop, loop)
    }
    render(
        <QueryClientProvider client={client}>
            <StreamContext value={{ status: downSince === null ? 'open' : 'reconnecting', downSince }}>
                <LoopPause />
            </StreamContext>
        </QueryClientProvider>,
    )
    return client
}

describe('LoopPause', () => {
    it("waits while the loop isn't answering, and says why", async () => {
        renderPause(RUNNING, Date.now() - 60_000)
        const button = screen.getByRole<HTMLButtonElement>('button', { name: 'Pause' })
        await waitFor(() => {
            expect(button.disabled).toBe(true)
        })
        expect(button.title).toBe("The loop isn't answering: start it with `canopy loop` or `canopy daemon start`.")
    })

    it('offers neither verb before the loop state arrives', () => {
        renderPause(undefined)
        expect(screen.queryByRole('button')).toBeNull()
    })

    it('pauses a running loop as `canopy pause` does, and shows the pause the server answers', async () => {
        answer = Response.json({ already: false, loop: { ...RUNNING, paused: { channel: 'web', since: SINCE } } })
        const client = renderPause(RUNNING)
        expect(screen.queryByText(/paused/u)).toBeNull()

        fireEvent.click(screen.getByRole('button', { name: 'Pause' }))
        expect(await screen.findByRole('button', { name: 'Resume' })).toBeDefined()
        expect(sent).toEqual(['POST /api/loop/pause'])
        expect(client.getQueryData<LoopState>(keys.loop)?.paused?.channel).toBe('web')
        expect(screen.getByTitle(/^Paused at .+ from the web UI$/u).textContent).toMatch(/^paused · \d+[smhd]$/u)
    })

    it("says where a pause came from in the CLI's words, and resumes it", async () => {
        answer = Response.json({ already: false, loop: RUNNING })
        renderPause(PAUSED)
        expect(screen.getByTitle(/^Paused at .+ from `canopy pause`$/u)).toBeDefined()

        fireEvent.click(screen.getByRole('button', { name: 'Resume' }))
        expect(await screen.findByRole('button', { name: 'Pause' })).toBeDefined()
        expect(sent).toEqual(['POST /api/loop/resume'])
        expect(screen.queryByText(/paused/u)).toBeNull()
    })

    it('says why it failed, to a screen reader and on hover, and keeps the state it had', async () => {
        answer = Response.json({ detail: 'the journal is locked' }, { status: 503 })
        renderPause(RUNNING)

        fireEvent.click(screen.getByRole('button', { name: 'Pause' }))
        expect((await screen.findByRole('alert')).textContent).toBe('the journal is locked')
        expect(screen.getByRole('button', { name: 'Pause' }).title).toBe('the journal is locked')
    })
})
