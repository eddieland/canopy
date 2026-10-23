import { cleanup, screen, within } from '@testing-library/react'
import { afterEach, describe, expect, it } from 'vitest'

import { mockTaskRun, mockTasks } from '@/api/mocks'
import type { TaskRun, TaskSummary } from '@/api/types'
import { renderRouted } from '@/test-utils'

import { TaskRow, TaskRunRow } from './task-row'

afterEach(() => {
    cleanup()
})

/** The mock task numbered `id`. */
function task(id: number): TaskSummary {
    const found = mockTasks.find((t) => t.id === id)
    if (found === undefined) {
        throw new Error(`no mock task:${String(id)}`)
    }
    return found
}

/** The row `task` renders, in a list as the page has it. */
async function row(shown: TaskSummary) {
    await renderRouted(
        <ul>
            <TaskRow task={shown} />
        </ul>,
    )
    return screen.getByTestId(`task-${String(shown.id)}`)
}

/** The row `run` of task 1 renders, in a list as the task's page has it. */
async function runRow(run: TaskRun) {
    await renderRouted(
        <ul>
            <TaskRunRow task={1} run={run} />
        </ul>,
    )
    return screen.getByTestId(`task-run-${String(run.id)}`)
}

describe('TaskRow', () => {
    it('says a task whose run asked a question is waiting on you, with what its run said under its text', async () => {
        const shown = await row(task(4))
        expect(within(shown).getByText('waiting on you')).toBeTruthy()
        expect(within(shown).getByText('web')).toBeTruthy()
        expect(within(shown).getByText(/^Rename the `billing_v1` feature flag/u)).toBeTruthy()
        expect(within(shown).getByText(/rename it there too\?$/u)).toBeTruthy()
    })

    it("opens the task's page from its id", async () => {
        const shown = await row(task(4))
        expect(within(shown).getByRole('link', { name: 'task:4' }).getAttribute('href')).toBe('/tasks/4')
    })

    it("names a task by its text's first line alone", async () => {
        const shown = await row(task(1))
        expect(within(shown).getByText("The checkout page's bundle grew past 900 kB.")).toBeTruthy()
        expect(within(shown).queryByText(/Find out what grew/u)).toBeNull()
        expect(within(shown).getByText('done')).toBeTruthy()
    })

    it('says a task no run has started is queued, with nothing under its text', async () => {
        const shown = await row(task(7))
        expect(within(shown).getByText('queued')).toBeTruthy()
        expect(shown.textContent).toMatch(/^queuedtask:7apiList the endpoints .*query string\.\d+\w ago$/u)
    })

    it('links a PR its run named in what it said, and nothing else but the task', async () => {
        const done = task(1)
        const said = 'Opened https://github.com/acme/web/pull/97'
        const shown = await row({ ...done, latest: done.latest === null ? null : { ...done.latest, summary: said } })
        const links = within(shown).getAllByRole('link')
        expect(links.map((link) => link.getAttribute('href'))).toEqual([
            '/tasks/1',
            'https://github.com/acme/web/pull/97',
        ])
    })
})

describe('TaskRunRow', () => {
    it('names the run within its task, with its status, cost, what it said, and the PR it named', async () => {
        const shown = await runRow(mockTaskRun({ id: 3 }))
        expect(within(shown).getByText('task:1#3')).toBeTruthy()
        expect(within(shown).getByText('done')).toBeTruthy()
        expect(within(shown).getByText('$2.12')).toBeTruthy()
        expect(within(shown).getByText(/^Cut the checkout bundle/u)).toBeTruthy()
        expect(within(shown).getByRole('link', { name: 'acme/web#97' }).getAttribute('href')).toBe(
            '/pull-requests/pr?url=https%3A%2F%2Fgithub.com%2Facme%2Fweb%2Fpull%2F97',
        )
    })

    it("names itself as a link to the run's page", async () => {
        const shown = await runRow(mockTaskRun({ id: 3, prs: [], session_id: null }))
        const links = within(shown).getAllByRole('link')
        expect(links.map((link) => [link.textContent, link.getAttribute('href')])).toEqual([
            ['task:1#3', '/tasks/1/runs/3'],
        ])
    })
})
