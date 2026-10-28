import { QueryClient } from '@tanstack/react-query'
import { cleanup, screen, within } from '@testing-library/react'
import { afterEach, describe, expect, it } from 'vitest'

import { mockTaskRun, mockTasks } from '@/api/mocks'
import type { TaskRun, TaskSummary, TaskTicket } from '@/api/types'
import { renderRouted } from '@/test-utils'

import { TaskLeft, THROWAWAY } from './task-left'

afterEach(() => {
    cleanup()
})

const DONE = mockTasks.find((t) => t.id === 1)
const FIRST = 'aaaaaaa1111111111111111111111111111111111'
const SECOND = 'bbbbbbb2222222222222222222222222222222222'

async function left(task: TaskSummary, runs: TaskRun[], tickets: TaskTicket[] = []) {
    // Settings unread: no tracker or branch links, so nothing is fetched.
    const client = new QueryClient({ defaultOptions: { queries: { staleTime: Infinity, enabled: false } } })
    await renderRouted(<TaskLeft task={task} runs={runs} tickets={tickets} />, { client })
    return screen.getByTestId('task-left')
}

describe('TaskLeft', () => {
    it("lists each run's pushed head commit, by its run, to copy whole", async () => {
        if (DONE === undefined) {
            throw new Error('no mock task:1')
        }
        const runs = [
            mockTaskRun({ id: 1, head: FIRST }),
            mockTaskRun({ id: 2, head: null, prs: [] }),
            mockTaskRun({ id: 3, head: SECOND }),
        ]
        const shown = await left(DONE, runs)
        const heads = within(screen.getByTestId('task-heads')).getAllByRole('listitem')
        expect(heads.map((head) => head.textContent)).toEqual(['task:1#1aaaaaaa', 'task:1#3bbbbbbb'])
        expect(within(shown).getByText('agent/task/1')).toBeTruthy()
        // The PR both runs named, once.
        expect(within(shown).getAllByRole('link', { name: 'acme/web#97' })).toHaveLength(1)
        expect(shown.textContent).toContain(THROWAWAY)
    })

    it('links each ticket its runs filed, as the tickets list links a key, in the project it names', async () => {
        if (DONE === undefined) {
            throw new Error('no mock task:1')
        }
        const tickets = [
            { key: 'ABC-120', run_id: 1, at: '2026-10-08T05:40:00Z' },
            { key: 'ABC-121', run_id: 1, at: '2026-10-08T05:40:00Z' },
        ]
        const shown = await left(DONE, [mockTaskRun()], tickets)
        expect(within(shown).getByText('tickets in ABC')).toBeTruthy()
        expect(within(shown).getByRole('link', { name: 'ABC-120' }).getAttribute('href')).toBe('/tickets/ABC-120')
        const from = within(screen.getByTestId('task-tickets')).getAllByRole('link', { name: 'task:1#1' })
        expect(from.map((link) => link.getAttribute('href'))).toEqual(['/tasks/1/runs/1', '/tasks/1/runs/1'])
    })

    it('says plainly what a task left nothing of, and why', async () => {
        const queued = mockTasks.find((t) => t.id === 7)
        if (queued === undefined) {
            throw new Error('no mock task:7')
        }
        const shown = await left(queued, [])
        expect(within(shown).getByText('none: nothing pushed')).toBeTruthy()
        expect(within(shown).getByText('none: it names no project')).toBeTruthy()
        expect(within(shown).queryAllByRole('link')).toEqual([])
    })
})
