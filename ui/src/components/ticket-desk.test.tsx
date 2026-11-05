import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { cleanup, fireEvent, render, screen } from '@testing-library/react'
import type { Middleware } from 'openapi-fetch'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

import { api } from '@/api/client'
import type { DeskOpened, OpenDesk, TicketDesk as TicketDeskData } from '@/api/types'

import { TicketDesk } from './ticket-desk'

const OPEN: OpenDesk = {
    branch: 'agent/ABC-1-export',
    path: 'checkouts/ABC-1',
    workspace_file: '/w/checkouts/ABC-1/ABC-1.code-workspace',
    open_command: 'code /w/checkouts/ABC-1/ABC-1.code-workspace',
    editor_url: 'vscode://file/w/checkouts/ABC-1/ABC-1.code-workspace',
    slots: [
        { repo: 'api', path: '.treehouse/api-1/2/api' },
        { repo: 'web', path: '.treehouse/web-1/4/web' },
    ],
}

// Every request the desk sends, and what the server stand-in answers each, in turn; the last is kept.
let sent: { path: string; body: unknown }[] = []
let answers: Response[] = []

const server: Middleware = {
    async onRequest({ request }) {
        const text = await request.text()
        const path = new URL(request.url).pathname
        if (!path.includes('/desk')) {
            // The tick and the ticket the desk reads again, which no test here answers.
            return Response.json({ tick: null })
        }
        sent.push({ path, body: text ? (JSON.parse(text) as unknown) : undefined })
        return (answers.length > 1 ? answers.shift() : answers[0]) ?? Response.json({})
    },
}

beforeEach(() => {
    sent = []
    answers = []
    api.use(server)
})

afterEach(() => {
    api.eject(server)
    cleanup()
})

function renderDesk(desk: TicketDeskData, client = new QueryClient()) {
    return render(
        <QueryClientProvider client={client}>
            <TicketDesk ticketKey="ABC-1" desk={desk} />
        </QueryClientProvider>,
    )
}

function opened(over: Partial<DeskOpened> = {}): Response {
    return Response.json({ already: false, desk: OPEN, running_run: null, running_kind: null, ...over })
}

describe('TicketDesk', () => {
    it('is not there before the ticket has a branch', () => {
        renderDesk({ repos: [], open: null })
        expect(screen.queryByRole('region', { name: 'Desk' })).toBeNull()
    })

    it('opens a desk over every repository with the branch, and says what the CLI says', async () => {
        answers = [opened()]
        renderDesk({ repos: ['web'], open: null })
        expect(screen.queryByRole('button', { name: /Repositories at the desk/u })).toBeNull()
        fireEvent.click(screen.getByRole('button', { name: 'Open desk' }))
        expect(await screen.findByText("ABC-1's desk is open.")).toBeDefined()
        expect(sent).toEqual([{ path: '/api/tickets/ABC-1/desk', body: { repos: [] } }])
    })

    it('offers a choice of repositories when the branch is in more than one', () => {
        renderDesk({ repos: ['api', 'web'], open: null })
        expect(screen.getByRole('button', { name: 'Repositories at the desk: every repository' })).toBeDefined()
    })

    it('says a run of the ticket pushes to the same branch meanwhile', async () => {
        answers = [opened({ running_run: 41, running_kind: 'resume' })]
        renderDesk({ repos: ['web'], open: null })
        fireEvent.click(screen.getByRole('button', { name: 'Open desk' }))
        expect(
            await screen.findByText(
                "ABC-1's desk is open. Run 41 (resume) is working ABC-1 now, in slots of its own, and pushes to the " +
                    'same branch; pull before you push.',
            ),
        ).toBeDefined()
    })

    it('names the guard that refused an open', async () => {
        answers = [
            Response.json(
                {
                    detail: {
                        guard: 'desk_failed',
                        reason: "could not open ABC-1's desk: web's pool has no idle slot",
                    },
                },
                { status: 409 },
            ),
        ]
        renderDesk({ repos: ['web'], open: null })
        fireEvent.click(screen.getByRole('button', { name: 'Open desk' }))
        expect((await screen.findByRole('alert')).textContent).toBe(
            "refused (desk_failed): could not open ABC-1's desk: web's pool has no idle slot",
        )
    })

    it('shows an open desk: each slot, a link that opens it in VS Code, and the command that does', () => {
        renderDesk({ repos: ['api', 'web'], open: OPEN })
        expect(screen.getByText('api')).toBeDefined()
        expect(screen.getByText('.treehouse/web-1/4/web')).toBeDefined()
        const link = screen.getByRole('link', { name: 'Open in VS Code' })
        expect(link.getAttribute('href')).toBe(OPEN.editor_url)
        expect(link.getAttribute('target')).toBeNull()
        expect(screen.getByText(OPEN.open_command)).toBeDefined()
        expect(screen.queryByRole('button', { name: 'Open desk' })).toBeNull()
    })

    it('closes a desk and names the slots it returned', async () => {
        answers = [Response.json({ returned: ['api', 'web'] })]
        renderDesk({ repos: ['api', 'web'], open: OPEN })
        fireEvent.click(screen.getByRole('button', { name: 'Close desk' }))
        expect(await screen.findByText("ABC-1's desk is closed; its slots are returned: api, web.")).toBeDefined()
        expect(sent).toEqual([{ path: '/api/tickets/ABC-1/desk/close', body: { discard: false } }])
    })

    it('reads the ticket and the worktrees again after a refused close, which may have returned slots', async () => {
        answers = [
            Response.json(
                { detail: { guard: 'desk_failed', reason: "ABC-1's desk is kept: web: its pool refused" } },
                { status: 409 },
            ),
        ]
        const client = new QueryClient()
        const invalidate = vi.spyOn(client, 'invalidateQueries')
        renderDesk({ repos: ['api', 'web'], open: OPEN }, client)
        fireEvent.click(screen.getByRole('button', { name: 'Close desk' }))
        expect((await screen.findByRole('alert')).textContent).toContain('refused (desk_failed)')
        expect(invalidate.mock.calls.map(([filters]) => filters?.queryKey)).toEqual([
            ['ticket', 'ABC-1'],
            ['worktrees'],
        ])
    })

    it('offers to discard work origin lacks once a close is refused for it, with the key typed out', async () => {
        const reason =
            "ABC-1's desk has work origin lacks: web has 2 uncommitted changes. Commit and push it, or discard it"
        answers = [
            Response.json({ detail: { guard: 'unpushed', reason } }, { status: 409 }),
            Response.json({ returned: ['api', 'web'] }),
        ]
        renderDesk({ repos: ['api', 'web'], open: OPEN })
        fireEvent.click(screen.getByRole('button', { name: 'Close desk' }))
        expect((await screen.findByRole('alert')).textContent).toBe(`refused (unpushed): ${reason}`)
        fireEvent.click(screen.getByRole('button', { name: 'Discard it and close' }))
        const discard = screen.getByRole('button', { name: 'Discard and close' })
        expect(discard).toHaveProperty('disabled', true)
        fireEvent.change(screen.getByLabelText('Type ABC-1 to confirm'), { target: { value: 'ABC-1' } })
        fireEvent.click(discard)
        expect(await screen.findByText("ABC-1's desk is closed; its slots are returned: api, web.")).toBeDefined()
        expect(sent.at(-1)).toEqual({
            path: '/api/tickets/ABC-1/desk/close',
            body: { discard: true, confirm: 'ABC-1' },
        })
    })
})
