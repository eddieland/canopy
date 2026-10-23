import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { cleanup, fireEvent, render, screen } from '@testing-library/react'
import type { Middleware } from 'openapi-fetch'
import { afterEach, beforeEach, describe, expect, it } from 'vitest'

import { api } from '@/api/client'
import { mockTasks } from '@/api/mocks'
import type { TaskSummary } from '@/api/types'

import { TaskActions } from './task-actions'

// Every stop the buttons send, and what the server stand-in answers it.
let sent: { path: string; body: unknown }[] = []
let answer: Response | undefined

const server: Middleware = {
    async onRequest({ request }) {
        sent.push({ path: new URL(request.url).pathname, body: (await request.json()) as unknown })
        return answer ?? Response.json({ already: false, dropped: false, running_run: null, ended: false })
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

/** Mock task 4, with whatever `fields` replace. */
function task(fields: Partial<TaskSummary> = {}): TaskSummary {
    const found = mockTasks.find((t) => t.id === 4)
    if (found === undefined) {
        throw new Error('no mock task:4')
    }
    return { ...found, stopped_at: null, ...fields }
}

function renderActions(fields: Partial<TaskSummary> = {}, running: number | null = null) {
    return render(
        <QueryClientProvider client={new QueryClient()}>
            <TaskActions task={task(fields)} running={running} />
        </QueryClientProvider>,
    )
}

// The names of the buttons shown, in order.
function buttons(): string[] {
    return screen.getAllByRole('button').map((button) => button.textContent)
}

describe('TaskActions', () => {
    it('asks once more before a stop, since nothing undoes it, and can be left alone', () => {
        renderActions()
        expect(buttons()).toEqual(['Stop'])
        fireEvent.click(screen.getByRole('button', { name: 'Stop' }))
        expect(buttons()).toEqual(['Stop task:4', 'Keep it'])
        expect(screen.getByText('Nothing starts it again, and it takes no more replies.')).toBeTruthy()
        fireEvent.click(screen.getByRole('button', { name: 'Keep it' }))
        expect(buttons()).toEqual(['Stop'])
        expect(sent).toEqual([])
    })

    it('stops a task, saying in the CLI’s words that its run finishes', async () => {
        answer = Response.json({ already: false, dropped: false, running_run: 6, ended: false })
        renderActions({}, 6)
        expect(buttons()).toEqual(['Stop', 'Stop now'])
        fireEvent.click(screen.getByRole('button', { name: 'Stop' }))
        fireEvent.click(screen.getByRole('button', { name: 'Stop task:4' }))
        expect((await screen.findByRole('status')).textContent).toBe(
            'task:4 is stopped; nothing starts it again. Its run 6 is still working and will finish; Stop now ends it.',
        )
        expect(sent).toEqual([{ path: '/api/tasks/4/stop', body: { now: false } }])
    })

    it('ends the running run only after a second click', async () => {
        answer = Response.json({ already: false, dropped: false, running_run: 6, ended: true })
        renderActions({}, 6)
        fireEvent.click(screen.getByRole('button', { name: 'Stop now' }))
        expect(buttons()).toEqual(['End run 6 now', 'Keep it running'])
        expect(sent).toEqual([])
        fireEvent.click(screen.getByRole('button', { name: 'End run 6 now' }))
        expect((await screen.findByRole('status')).textContent).toBe(
            'task:4 is stopped; nothing starts it again. Its run 6 was ended and its slot returned.',
        )
        expect(sent).toEqual([{ path: '/api/tasks/4/stop', body: { now: true } }])
    })

    it('keeps Stop now alone on a task stopped while its run works, and nothing on one with none', () => {
        renderActions({ stopped_at: '2026-10-08T11:00:00Z' }, 6)
        expect(buttons()).toEqual(['Stop now'])
        cleanup()
        renderActions({ standing: 'stopped', stopped_at: '2026-10-08T11:00:00Z' })
        expect(screen.queryByTestId('task-actions')).toBeNull()
    })

    it('names the guard of a refused stop', async () => {
        answer = Response.json({ detail: { guard: 'stopped', reason: 'task:4 is stopped' } }, { status: 409 })
        renderActions()
        fireEvent.click(screen.getByRole('button', { name: 'Stop' }))
        fireEvent.click(screen.getByRole('button', { name: 'Stop task:4' }))
        expect((await screen.findByRole('alert')).textContent).toBe('refused (stopped): task:4 is stopped')
    })
})
