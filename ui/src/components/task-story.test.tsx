import { QueryClient } from '@tanstack/react-query'
import { cleanup, screen, within } from '@testing-library/react'
import { afterEach, describe, expect, it } from 'vitest'

import { mockNoAttachments, mockTaskRun, mockTasks } from '@/api/mocks'
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
        attachments: mockNoAttachments,
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
        // Its words as written, its `code` set as code.
        expect(instruction.textContent).toContain('Rename the billing_v1 feature flag')
        expect(
            within(instruction)
                .getAllByRole('code')
                .map((code) => code.textContent),
        ).toEqual(['billing_v1', 'billing_legacy'])
        // Each message names the run that wrote it within its task, opening the run's page.
        const report = screen.getByTestId('message-12')
        expect(report.textContent).toContain('report (task:4#5)')
        expect(within(report).getByRole('link', { name: 'task:4#5' }).getAttribute('href')).toBe('/tasks/4/runs/5')
    })

    it('puts the instruction at the far end when the conversation is flipped newest first', async () => {
        setListOrder('conversation', 'newest')
        await story(waiting())
        const items = within(screen.getByTestId('conversation')).getAllByRole('listitem')
        expect(items.map((item) => item.dataset.testid)).toEqual(['message-13', 'message-12', 'instruction'])
    })

    it('marks the question waiting on you, and answers it with the reply form beside it', async () => {
        await story(waiting())
        expect(within(screen.getByTestId('message-13')).getByText('waiting on you')).toBeTruthy()
        const band = screen.getByRole('region', { name: 'A question waiting on you' })
        expect(band.textContent).toContain('Waiting on you')
        expect(band.textContent).toContain('#13')
        // The run that asked opens its page, as a message's head does.
        expect(within(band).getByRole('link', { name: 'task:4#5' })).toBeTruthy()
        expect(within(band).getByRole('textbox', { name: 'Reply to message 13' })).toBeTruthy()
        expect(screen.getByRole('button', { name: 'Stop' })).toBeTruthy()
    })

    it('takes a reply when no question waits, and offers none on a stopped task', async () => {
        await story(waiting({ standing: 'done', question_id: null }))
        expect(screen.queryByText('waiting on you')).toBeNull()
        expect(screen.queryByRole('region', { name: 'A question waiting on you' })).toBeNull()
        expect(screen.getByRole('form', { name: 'Reply' })).toBeTruthy()
        cleanup()
        await story(waiting({ standing: 'stopped', question_id: null, stopped_at: '2026-10-08T11:00:00Z' }))
        expect(screen.queryByRole('form', { name: 'Reply' })).toBeNull()
        expect(screen.queryByRole('button', { name: 'Stop' })).toBeNull()
    })

    it('ends on the run working the task now', async () => {
        const detail = waiting({ standing: 'running', question_id: null })
        await story({ ...detail, runs: [mockTaskRun({ id: 8, status: 'running', state: 'running', ended_at: null })] })
        const now = screen.getByTestId('working-now')
        expect(now.textContent).toContain('working now')
        expect(within(now).getByRole('link', { name: 'task:4#8' }).getAttribute('href')).toBe('/tasks/4/runs/8')
    })
})
