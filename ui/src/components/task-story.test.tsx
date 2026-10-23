import { QueryClient } from '@tanstack/react-query'
import { cleanup, screen, within } from '@testing-library/react'
import { afterEach, describe, expect, it } from 'vitest'

import { mockTaskRun, mockTasks } from '@/api/mocks'
import { keys } from '@/api/queries'
import type { Message, TaskDetail, TaskSummary } from '@/api/types'
import { setListOrder } from '@/lib/list-order'
import { renderRouted } from '@/test-utils'

import { TaskStory } from './task-story'

afterEach(() => {
    cleanup()
    setListOrder('conversation', 'oldest')
})

function message(fields: Partial<Message> & Pick<Message, 'id'>): Message {
    return {
        at: '2026-10-08T11:30:00Z',
        body: 'Renamed it in web.',
        channel: 'web',
        comment: null,
        kind: 'report',
        run_id: null,
        task_run_id: 5,
        source: 'worker',
        answers: null,
        ...fields,
    }
}

/** Mock task 4, whose run asked a question in message 13, with whatever `fields` replace. */
function waiting(fields: Partial<TaskSummary> = {}): TaskDetail {
    const task = mockTasks.find((t) => t.id === 4)
    if (task === undefined) {
        throw new Error('no mock task:4')
    }
    return {
        task: { ...task, question_id: 13, ...fields },
        runs: [mockTaskRun({ id: 5, status: 'blocked', state: 'blocked', head: null, reported: false })],
        messages: [message({ id: 12 }), message({ id: 13, kind: 'question', body: 'Rename it in api too?' })],
        tickets: [],
    }
}

async function story(detail: TaskDetail) {
    // The latest tick is known, so nothing is fetched.
    const client = new QueryClient({ defaultOptions: { queries: { staleTime: Infinity } } })
    client.setQueryData(keys.tick, { tick: null, acknowledged: null })
    await renderRouted(<TaskStory detail={detail} />, { client })
}

describe('TaskStory', () => {
    it("heads the story with the operator's instruction, in their words, then what its runs said", async () => {
        await story(waiting())
        const items = within(screen.getByTestId('conversation')).getAllByRole('listitem')
        expect(items.map((item) => item.dataset.testid)).toEqual(['instruction', 'message-12', 'message-13'])
        const instruction = screen.getByTestId('instruction')
        expect(instruction.textContent).toContain('task:4')
        expect(instruction.textContent).toContain('instruction via cli')
        expect(instruction.textContent).toContain('Rename the `billing_v1` feature flag')
        // Each message names the run that wrote it within its task, as text.
        expect(screen.getByTestId('message-12').textContent).toContain('report (task:4#5)')
    })

    it('puts the instruction at the far end when the conversation is flipped newest first', async () => {
        setListOrder('conversation', 'newest')
        await story(waiting())
        const items = within(screen.getByTestId('conversation')).getAllByRole('listitem')
        expect(items.map((item) => item.dataset.testid)).toEqual(['message-13', 'message-12', 'instruction'])
    })

    it('marks the question waiting on you, and names the command that answers it', async () => {
        await story(waiting())
        expect(within(screen.getByTestId('message-13')).getByText('waiting on you')).toBeTruthy()
        const band = screen.getByRole('region', { name: 'A question waiting on you' })
        expect(band.textContent).toContain('Waiting on you')
        expect(band.textContent).toContain('#13')
        expect(band.textContent).toContain('canopy reply task:4 TEXT')
    })

    it('says what a reply does when no question waits, and offers none on a stopped task', async () => {
        await story(waiting({ standing: 'done', question_id: null }))
        expect(screen.queryByText('waiting on you')).toBeNull()
        expect(screen.getByRole('region', { name: 'Reply' }).textContent).toContain('A reply queues its next run')
        cleanup()
        await story(waiting({ standing: 'stopped', question_id: null }))
        expect(screen.queryByTestId('task-reply')).toBeNull()
    })

    it('ends on the run working the task now', async () => {
        const detail = waiting({ standing: 'running', question_id: null })
        await story({ ...detail, runs: [mockTaskRun({ id: 8, status: 'running', state: 'running', ended_at: null })] })
        const now = screen.getByTestId('working-now')
        expect(now.textContent).toContain('working now')
        expect(now.textContent).toContain('task:4#8')
    })
})
