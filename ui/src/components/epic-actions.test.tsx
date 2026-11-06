import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { cleanup, fireEvent, render, screen } from '@testing-library/react'
import type { Middleware } from 'openapi-fetch'
import { afterEach, beforeEach, describe, expect, it } from 'vitest'

import { api } from '@/api/client'
import { mockEpics } from '@/api/mocks'
import { keys } from '@/api/queries'
import type { EpicSummary } from '@/api/types'

import { EpicActions } from './epic-actions'

// Every stop the buttons send, and what the server stand-in answers it.
let sent: { path: string; body: unknown }[] = []
let answer: Response | undefined

const server: Middleware = {
    async onRequest({ request }) {
        sent.push({ path: new URL(request.url).pathname, body: (await request.json()) as unknown })
        return answer ?? Response.json({ already: false, running_run: null, ended: false })
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

/** Mock epic 3, not stopped, with whatever `fields` replace. */
function epic(fields: Partial<EpicSummary> = {}): EpicSummary {
    const found = mockEpics.find((e) => e.id === 3)
    if (found === undefined) {
        throw new Error('no mock epic:3')
    }
    return { ...found, stopped_at: null, ...fields }
}

function renderActions(fields: Partial<EpicSummary> = {}, running: number | null = null, client = new QueryClient()) {
    return render(
        <QueryClientProvider client={client}>
            <EpicActions epic={epic(fields)} running={running} />
        </QueryClientProvider>,
    )
}

// The names of the buttons shown, in order.
function buttons(): string[] {
    return screen.getAllByRole('button').map((button) => button.textContent)
}

describe('EpicActions', () => {
    it("asks once more before a stop, saying its members' work is untouched, and can be left alone", () => {
        renderActions()
        expect(buttons()).toEqual(['Stop'])
        fireEvent.click(screen.getByRole('button', { name: 'Stop' }))
        expect(buttons()).toEqual(['Stop epic:3', 'Keep it'])
        expect(
            screen.getByText(
                'No plan run of it starts again, and it takes no more replies. Its members and their work are left ' +
                    'as they are.',
            ),
        ).toBeTruthy()
        fireEvent.click(screen.getByRole('button', { name: 'Keep it' }))
        expect(buttons()).toEqual(['Stop'])
        expect(sent).toEqual([])
    })

    it("stops an epic, saying in the CLI's words that its plan run finishes, and reads the epic again", async () => {
        answer = Response.json({ already: false, running_run: 4, ended: false })
        const client = new QueryClient()
        client.setQueryData(keys.epic(3), {})
        client.setQueryData(keys.epics, [])
        renderActions({}, 4, client)
        expect(buttons()).toEqual(['Stop', 'Stop now'])
        fireEvent.click(screen.getByRole('button', { name: 'Stop' }))
        expect(screen.getByText(/plan run 4 finishes its work/u)).toBeTruthy()
        fireEvent.click(screen.getByRole('button', { name: 'Stop epic:3' }))
        expect((await screen.findByRole('status')).textContent).toBe(
            'epic:3 is stopped; no plan run of it starts again. Its members are left as they are. Its plan run 4 is ' +
                'still working and will finish; Stop now ends it.',
        )
        expect(sent).toEqual([{ path: '/api/epics/3/stop', body: { now: false } }])
        expect(client.getQueryState(keys.epic(3))?.isInvalidated).toBe(true)
        expect(client.getQueryState(keys.epics)?.isInvalidated).toBe(true)
    })

    it('ends the plan run at work only after a second click', async () => {
        answer = Response.json({ already: false, running_run: 4, ended: true })
        renderActions({}, 4)
        fireEvent.click(screen.getByRole('button', { name: 'Stop now' }))
        expect(buttons()).toEqual(['End plan run 4 now', 'Keep it running'])
        expect(sent).toEqual([])
        fireEvent.click(screen.getByRole('button', { name: 'End plan run 4 now' }))
        expect((await screen.findByRole('status')).textContent).toBe(
            'epic:3 is stopped; no plan run of it starts again. Its members are left as they are. Its plan run 4 was ' +
                'ended and its slots returned.',
        )
        expect(sent).toEqual([{ path: '/api/epics/3/stop', body: { now: true } }])
    })

    it('keeps Stop now alone on an epic stopped while its plan run works, and nothing on one with none', () => {
        renderActions({ stopped_at: '2026-10-08T11:00:00Z' }, 4)
        expect(buttons()).toEqual(['Stop now'])
        cleanup()
        renderActions({ standing: 'stopped', stopped_at: '2026-10-08T11:00:00Z' })
        expect(screen.queryByTestId('epic-actions')).toBeNull()
    })

    it('keeps Open plan beside the stop, and alone once the epic is stopped', () => {
        render(
            <QueryClientProvider client={new QueryClient()}>
                <EpicActions
                    epic={epic({ stopped_at: '2026-10-08T11:00:00Z' })}
                    running={null}
                    plan={<span>Open plan</span>}
                />
            </QueryClientProvider>,
        )
        expect(screen.getByTestId('epic-actions').textContent).toBe('Open plan')
    })

    it('names the guard of a refused stop', async () => {
        answer = Response.json({ detail: { guard: 'inside_run', reason: 'canopy is running' } }, { status: 409 })
        renderActions()
        fireEvent.click(screen.getByRole('button', { name: 'Stop' }))
        fireEvent.click(screen.getByRole('button', { name: 'Stop epic:3' }))
        expect((await screen.findByRole('alert')).textContent).toBe('refused (inside_run): canopy is running')
    })
})
