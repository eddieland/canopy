import { QueryClient } from '@tanstack/react-query'
import { cleanup, fireEvent, screen, waitFor, within } from '@testing-library/react'
import type { Middleware } from 'openapi-fetch'
import { afterEach, beforeEach, describe, expect, it } from 'vitest'

import { api } from '@/api/client'
import { keys } from '@/api/queries'
import type { Meta, TaskSummary } from '@/api/types'
import { ToastContext } from '@/hooks/use-toast'
import type { NewToast } from '@/lib/toasts'
import { renderRouted } from '@/test-utils'

import { TaskSubmitForm } from './task-submit'

// What each submission sent, and what the server stand-in answers.
let sent: unknown[] = []
let answer: Response | undefined
let toasts: NewToast[] = []

const server: Middleware = {
    async onRequest({ request }) {
        if (new URL(request.url).pathname === '/api/tasks') {
            sent.push(await request.json())
        }
        return answer ?? Response.json({ id: 9, repo: 'web', branch: 'agent/task/9', no_capacity: false })
    },
}

beforeEach(() => {
    sent = []
    answer = undefined
    toasts = []
    api.use(server)
})

afterEach(() => {
    api.eject(server)
    cleanup()
})

/** The form at `/tasks`, in a workspace of `repos`, over `tasks` and the list's `filter`. */
function renderForm(repos: string[], tasks: Pick<TaskSummary, 'repo'>[] = [], filter?: string) {
    const client = new QueryClient()
    const meta: Meta = {
        branch_urls: {},
        build: null,
        mock: false,
        ticket_url: null,
        version: '0.4.0',
        workspace_root: '/w',
        repos,
    }
    client.setQueryData(keys.meta, meta)
    return renderRouted(
        <ToastContext
            value={(toast) => {
                toasts.push(toast)
            }}
        >
            <TaskSubmitForm tasks={tasks as TaskSummary[]} filter={filter} />
        </ToastContext>,
        { at: '/tasks', client },
    )
}

function write(text: string, project = '') {
    fireEvent.change(screen.getByRole('textbox', { name: 'Task' }), { target: { value: text } })
    fireEvent.change(screen.getByRole('textbox', { name: 'Tracker project' }), { target: { value: project } })
}

function submit() {
    fireEvent.submit(screen.getByRole('form', { name: 'Submit a task' }))
}

describe('TaskSubmitForm', () => {
    it('says up front what a task may do', async () => {
        await renderForm(['web'])
        expect(screen.getByRole('status').textContent).toBe(
            'It opens a draft PR only if your text asks for one, and files tickets only in the project you name, ' +
                'none without one.',
        )
    })

    it('submits the text in a workspace of one, naming no repository, then says so and opens the task', async () => {
        const { router } = await renderForm(['web'])
        expect(screen.queryByRole('button', { name: /^Runs in/u })).toBeNull()
        write('Find out why the build is slow.')
        submit()
        await waitFor(() => {
            expect(router.state.location.pathname).toBe('/tasks/9')
        })
        expect(sent).toEqual([{ text: 'Find out why the build is slow.', repo: null, project: null }])
        expect(toasts).toEqual([
            { title: 'Submitted task:9; the next tick starts it.', detail: 'web on agent/task/9', tone: 'done' },
        ])
    })

    it("starts at the newest task's repository, sends the one picked, and the project trimmed", async () => {
        const { router } = await renderForm(['api', 'web', 'mobile'], [{ repo: 'web' }])
        fireEvent.click(screen.getByRole('button', { name: 'Runs in: web' }))
        fireEvent.click(within(screen.getByRole('listbox')).getByRole('option', { name: 'mobile' }))
        expect(screen.getByRole('button', { name: 'Runs in: mobile' })).toBeTruthy()
        write('Plan the offline mode.', '  MOB ')
        submit()
        await waitFor(() => {
            expect(router.state.location.pathname).toBe('/tasks/9')
        })
        expect(sent).toEqual([{ text: 'Plan the offline mode.', repo: 'mobile', project: 'MOB' }])
    })

    it('starts at the one repository the list is narrowed to', async () => {
        await renderForm(['api', 'web'], [{ repo: 'web' }], 'api')
        expect(screen.getByRole('button', { name: 'Runs in: api' })).toBeTruthy()
    })

    it('adds that no tick starts it while capacity.max_tasks is 0', async () => {
        answer = Response.json({ id: 9, repo: 'web', branch: 'agent/task/9', no_capacity: true })
        await renderForm(['web'])
        write('Try the new parser.')
        submit()
        await waitFor(() => {
            expect(toasts).toHaveLength(1)
        })
        expect(toasts[0]?.title).toBe(
            'Submitted task:9; the next tick starts it. ' +
                'capacity.max_tasks is 0, so no tick starts a task until you raise it.',
        )
    })

    it('sends nothing for blank text', async () => {
        await renderForm(['web'])
        write('   ')
        submit()
        expect(sent).toEqual([])
        expect(screen.getByRole<HTMLButtonElement>('button', { name: /^Submit/u }).disabled).toBe(true)
    })

    it('names the guard that refused it, in place of the line, and stays on the page', async () => {
        answer = Response.json({ detail: { guard: 'bad_project', reason: 'no tracker names `x y`' } }, { status: 409 })
        const { router } = await renderForm(['web'])
        write('Plan it.', 'x y')
        submit()
        expect((await screen.findByRole('alert')).textContent).toBe('refused (bad_project): no tracker names x y')
        expect(screen.queryByRole('status')).toBeNull()
        expect(router.state.location.pathname).toBe('/tasks')
        expect(toasts).toEqual([])
    })
})
