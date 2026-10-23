import { cleanup, render, screen, within } from '@testing-library/react'
import { afterEach, describe, expect, it } from 'vitest'

import { mockTasks } from '@/api/mocks'
import type { TaskSummary } from '@/api/types'

import { TaskRow } from './task-row'

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
function row(shown: TaskSummary) {
    render(
        <ul>
            <TaskRow task={shown} />
        </ul>,
    )
    return screen.getByTestId(`task-${String(shown.id)}`)
}

describe('TaskRow', () => {
    it('says a task whose run asked a question is waiting on you, with what its run said under its text', () => {
        const shown = row(task(4))
        expect(within(shown).getByText('waiting on you')).toBeTruthy()
        expect(within(shown).getByText('task:4')).toBeTruthy()
        expect(within(shown).getByText('web')).toBeTruthy()
        expect(within(shown).getByText(/^Rename the `billing_v1` feature flag/u)).toBeTruthy()
        expect(within(shown).getByText(/rename it there too\?$/u)).toBeTruthy()
    })

    it("names a task by its text's first line alone", () => {
        const shown = row(task(1))
        expect(within(shown).getByText("The checkout page's bundle grew past 900 kB.")).toBeTruthy()
        expect(within(shown).queryByText(/Find out what grew/u)).toBeNull()
        expect(within(shown).getByText('done')).toBeTruthy()
    })

    it('says a task no run has started is queued, with nothing under its text', () => {
        const shown = row(task(7))
        expect(within(shown).getByText('queued')).toBeTruthy()
        expect(shown.textContent).toMatch(/^queuedtask:7apiList the endpoints .*query string\.\d+\w ago$/u)
    })

    it('links a PR its run named in what it said, and nothing else', () => {
        const done = task(1)
        const said = 'Opened https://github.com/acme/web/pull/97'
        const shown = row({ ...done, latest: done.latest === null ? null : { ...done.latest, summary: said } })
        expect(within(shown).getByRole('link').getAttribute('href')).toBe('https://github.com/acme/web/pull/97')
    })
})
