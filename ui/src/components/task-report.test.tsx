import { QueryClient } from '@tanstack/react-query'
import { cleanup, screen, within } from '@testing-library/react'
import { afterEach, describe, expect, it } from 'vitest'

import { mockTaskRun, mockTasks } from '@/api/mocks'
import { keys } from '@/api/queries'
import type { TaskReport, TaskRun } from '@/api/types'
import { renderRouted } from '@/test-utils'

import { TaskReportPanel } from './task-report'

afterEach(() => {
    cleanup()
})

const TASK = mockTasks.find((t) => t.id === 1)

function report(fields: Partial<TaskReport> = {}): TaskReport {
    return {
        task_id: 1,
        run_id: 2,
        path: '.canopy/tasks/1/2.md',
        text: '# Checkout bundle\n\nDown to 612 kB. <img src=x onerror=alert(1)> [here](https://example.com)\n',
        problem: null,
        sha256: 'abc',
        edited: false,
        ...fields,
    }
}

/** The panel over `runs`, with run 2's report already read as `found`. */
async function panel(runs: TaskRun[], found: TaskReport = report()) {
    if (TASK === undefined) {
        throw new Error('no mock task:1')
    }
    const client = new QueryClient({ defaultOptions: { queries: { staleTime: Infinity } } })
    client.setQueryData(keys.taskReport(1, 2), found)
    // Its path's copy button reads where the workspace is: known, so nothing is fetched.
    client.setQueryData(keys.meta, { workspace_root: '/home/me/acme' })
    await renderRouted(<TaskReportPanel task={TASK} runs={runs} />, { client })
    return screen.getByTestId('task-report')
}

describe('TaskReportPanel', () => {
    it("lays out the newest report as a document, naming its run, and keeps the agent's markup text", async () => {
        const runs = [
            mockTaskRun({ id: 1 }),
            mockTaskRun({ id: 2 }),
            mockTaskRun({ id: 3, status: 'running', state: 'running', reported: false }),
        ]
        const shown = await panel(runs)
        expect(within(shown).getByText('from task:1#2')).toBeTruthy()
        expect(within(shown).getByRole('heading', { name: 'Checkout bundle' })).toBeTruthy()
        // An image stays its characters, and a link is no link.
        expect(shown.querySelector('img')).toBeNull()
        expect(shown.textContent).toContain('<img src=x onerror=alert(1)>')
        expect(within(shown).queryByRole('link', { name: 'here' })).toBeNull()
        expect(within(shown).queryByText('edited')).toBeNull()
    })

    it('says when the file was edited since its run left it', async () => {
        const shown = await panel([mockTaskRun({ id: 2 })], report({ edited: true }))
        expect(within(shown).getByText('edited')).toBeTruthy()
    })

    it('says why a file is no report any more', async () => {
        // The server says a missing file is edited too, since its hash no longer matches: the problem is what shows.
        const missing = report({ text: null, problem: 'missing', sha256: null, edited: true })
        const shown = await panel([mockTaskRun({ id: 2 })], missing)
        expect(shown.textContent).toContain('no report to read: its file is missing')
        expect(within(shown).queryByText('edited')).toBeNull()
    })

    it('says what comes next while no run has left one', async () => {
        const shown = await panel([mockTaskRun({ id: 3, status: 'running', state: 'running', reported: false })])
        expect(shown.textContent).toContain('no report yet: its run is working')
        expect(within(shown).queryByText(/from task/u)).toBeNull()
    })
})
