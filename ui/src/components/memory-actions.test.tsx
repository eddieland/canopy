import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { cleanup, fireEvent, render, screen, within } from '@testing-library/react'
import type { Middleware } from 'openapi-fetch'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

import { api } from '@/api/client'
import type { MemoryEntry, MemoryOverview, MemoryPromoted } from '@/api/types'

import { LessonActions, NoteActions, ProposalActions } from './memory-actions'

const ENTRY: MemoryEntry = {
    id: 5,
    scope: 'proposal',
    ticket_key: 'ABC-099',
    repo: 'web',
    key: 'web-tests',
    text: "Run web's tests with `npm test -- --run`.",
    status: 'pending',
    why: null,
    run_id: 39,
    head: null,
    created_at: '2026-10-08T10:00:00Z',
    use_count: 0,
    used_by: [],
    last_used_at: null,
    review_at: null,
    wrong_at: null,
    wrong_run_id: null,
    promoted_from: null,
    origin: null,
    private: false,
}
const LESSON: MemoryEntry = {
    ...ENTRY,
    id: 8,
    scope: 'lesson',
    ticket_key: null,
    text: 'Run the tests once, with --run.',
    status: 'active',
    run_id: null,
    review_at: '2027-01-06T12:00:00Z',
    promoted_from: 7,
}
const NOTE: MemoryEntry = { ...ENTRY, id: 2, scope: 'ticket', repo: null, key: 'flaky-checkout', status: 'invalid' }
const OVERVIEW: MemoryOverview = {
    state: null,
    tickets: [],
    proposals: [],
    lessons: [LESSON],
    lessons_digest: null,
    repos: ['api', 'mobile', 'web'],
}

function promoted(fields: Partial<MemoryPromoted> = {}): MemoryPromoted {
    return {
        lesson: { ...LESSON, id: 9, promoted_from: 5, review_at: '2027-01-06T12:00:00Z' },
        source: ENTRY,
        superseded: 8,
        served: false,
        private: false,
        ...fields,
    }
}

// Every write the buttons send, and what the server stand-in answers it; a read of the memory gets OVERVIEW.
let sent: { path: string; body: unknown }[] = []
let answer: Response | undefined

const server: Middleware = {
    async onRequest({ request }) {
        const path = new URL(request.url).pathname
        if (request.method === 'GET') {
            return Response.json(OVERVIEW)
        }
        const text = await request.text()
        sent.push({ path, body: text ? (JSON.parse(text) as unknown) : undefined })
        return answer ?? Response.json({})
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

function renderIn(ui: React.JSX.Element) {
    return render(<QueryClientProvider client={new QueryClient()}>{ui}</QueryClientProvider>)
}

describe('ProposalActions', () => {
    it("opens the promote form on the proposal's words, naming the lesson it replaces and where", async () => {
        renderIn(<ProposalActions proposal={ENTRY} onSaid={vi.fn<(said: string) => void>()} />)
        fireEvent.click(screen.getByRole('button', { name: 'Promote' }))
        const form = screen.getByRole('form', { name: 'Promote memory:5' })
        expect(
            within(form).getByRole<HTMLTextAreaElement>('textbox', { name: 'The lesson, in your words' }).value,
        ).toBe(ENTRY.text)
        await vi.waitFor(() => {
            expect(within(form).getByTestId('promote-replaces').textContent).toBe(
                'It replaces memory:8, the lesson in force under web-tests: Run the tests once, with --run.',
            )
        })
        // A proposal for one repository keeps it unless another is named: no `every repository` to pick.
        const repos = within(form).getAllByRole('radio')
        expect(repos.map((r) => r.textContent)).toEqual(['web', 'api', 'mobile'])
        expect(repos[0]?.getAttribute('aria-checked')).toBe('true')
        expect(within(form).queryByTestId('promote-private')).toBeNull()
    })

    it('sends its own words and repository as null, as the CLI leaves them out, and says what it made', async () => {
        answer = Response.json(promoted())
        const onSaid = vi.fn<(said: string) => void>()
        renderIn(<ProposalActions proposal={ENTRY} onSaid={onSaid} />)
        fireEvent.click(screen.getByRole('button', { name: 'Promote' }))
        fireEvent.click(screen.getByRole('button', { name: 'Promote memory:5' }))
        await vi.waitFor(() => {
            expect(onSaid).toHaveBeenCalledOnce()
        })
        expect(sent).toEqual([{ path: '/api/memory/5/promote', body: { text: null, repo: null } }])
        const said = onSaid.mock.calls[0]?.[0] ?? ''
        expect(said).toMatch(
            /^Proposal 5 is lesson 9 \(`web-tests`\) for web, due for review at .+\. It replaces lesson 8/u,
        )
        expect(said).toMatch(
            /It is recorded, not served: memory\.proposals is record, so no run reads it until it is use\.$/u,
        )
        expect(screen.queryByRole('form')).toBeNull()
    })

    it('sends the words and repository the operator changed, and holds the text to the bound', async () => {
        answer = Response.json(promoted())
        renderIn(<ProposalActions proposal={ENTRY} onSaid={vi.fn<(said: string) => void>()} />)
        fireEvent.click(screen.getByRole('button', { name: 'Promote' }))
        const field = screen.getByRole('textbox', { name: 'The lesson, in your words' })
        const save = screen.getByRole<HTMLButtonElement>('button', { name: 'Promote memory:5' })
        fireEvent.change(field, { target: { value: 'x'.repeat(601) } })
        expect(screen.getByTestId('lesson-chars').textContent).toBe('601 of 600')
        expect(save.disabled).toBe(true)
        fireEvent.change(field, { target: { value: '   ' } })
        expect(save.disabled).toBe(true)
        fireEvent.change(field, { target: { value: 'Run the tests once.' } })
        fireEvent.click(await screen.findByRole('radio', { name: 'mobile' }))
        fireEvent.click(save)
        await vi.waitFor(() => {
            expect(sent).toEqual([
                { path: '/api/memory/5/promote', body: { text: 'Run the tests once.', repo: 'mobile' } },
            ])
        })
    })

    it("warns while the text is still a private ticket's run's own words, as canopy memory promote does", () => {
        renderIn(<ProposalActions proposal={{ ...ENTRY, private: true }} onSaid={vi.fn<(said: string) => void>()} />)
        fireEvent.click(screen.getByRole('button', { name: 'Promote' }))
        expect(screen.getByTestId('promote-private').textContent).toMatch(/^Warning: its text is from a private/u)
        fireEvent.change(screen.getByRole('textbox', { name: 'The lesson, in your words' }), {
            target: { value: 'In my own words.' },
        })
        expect(screen.queryByTestId('promote-private')).toBeNull()
    })

    it('rejects, and says so in the words of canopy memory reject', async () => {
        answer = Response.json({ id: 5 })
        const onSaid = vi.fn<(said: string) => void>()
        renderIn(<ProposalActions proposal={ENTRY} onSaid={onSaid} />)
        fireEvent.click(screen.getByRole('button', { name: 'Reject' }))
        await vi.waitFor(() => {
            expect(onSaid).toHaveBeenCalledWith('Proposal 5 is rejected.')
        })
        expect(sent).toEqual([{ path: '/api/memory/5/reject', body: undefined }])
    })

    it('promotes as written at once on an attention item, and names a refusal under the row', async () => {
        answer = Response.json(
            { detail: { guard: 'not_pending', reason: 'proposal 5 is invalid: rejected' } },
            { status: 409 },
        )
        const onSaid = vi.fn<(said: string) => void>()
        renderIn(<ProposalActions proposal={ENTRY} asWritten onSaid={onSaid} />)
        fireEvent.click(screen.getByRole('button', { name: 'Promote as written' }))
        expect((await screen.findByRole('alert')).textContent).toBe(
            'refused (not_pending): proposal 5 is invalid: rejected',
        )
        expect(sent).toEqual([{ path: '/api/memory/5/promote', body: { text: null, repo: null } }])
        expect(screen.queryByRole('form')).toBeNull()
        expect(onSaid).not.toHaveBeenCalled()
    })
})

describe('ProposalActions as written', () => {
    it('promotes a proposal at once in its own words and for its repository, as canopy memory promote ID', async () => {
        answer = Response.json(promoted())
        const onSaid = vi.fn<(said: string) => void>()
        renderIn(<ProposalActions proposal={ENTRY} onSaid={onSaid} />)
        expect(screen.getAllByRole('button').map((b) => b.textContent)).toEqual([
            'Promote',
            'As written',
            'Reject',
            'Forget',
        ])
        fireEvent.click(screen.getByRole('button', { name: 'As written' }))
        await vi.waitFor(() => {
            expect(onSaid).toHaveBeenCalledOnce()
        })
        expect(sent).toEqual([{ path: '/api/memory/5/promote', body: { text: null, repo: null } }])
        expect(screen.queryByRole('form')).toBeNull()
    })
})

describe('ProposalActions forget', () => {
    it('forgets a proposal once its ref is typed, so its words leave the journal', async () => {
        answer = Response.json({ id: 5, scope: 'proposal', key: 'web-tests', checkpointed: true })
        const onSaid = vi.fn<(said: string) => void>()
        renderIn(<ProposalActions proposal={ENTRY} onSaid={onSaid} />)
        fireEvent.click(screen.getByRole('button', { name: 'Forget' }))
        const form = screen.getByRole('form', { name: 'Forget memory:5' })
        expect(form.textContent).toContain('Reject is enough')
        fireEvent.change(within(form).getByRole('textbox', { name: 'Type memory:5 to confirm' }), {
            target: { value: 'memory:5' },
        })
        fireEvent.click(within(form).getByRole('button', { name: 'Forget memory:5' }))
        await vi.waitFor(() => {
            expect(onSaid).toHaveBeenCalledWith('Memory 5 (proposal `web-tests`) is forgotten: its text is deleted.')
        })
        expect(sent).toEqual([{ path: '/api/memory/5/forget', body: { confirm: 'memory:5' } }])
    })

    it('offers no Forget on an attention item', () => {
        renderIn(<ProposalActions proposal={ENTRY} asWritten forget={false} onSaid={vi.fn<(said: string) => void>()} />)
        expect(screen.getAllByRole('button').map((b) => b.textContent)).toEqual(['Promote as written', 'Reject'])
    })
})

describe('NoteActions', () => {
    it('forgets a note once its ref is typed', async () => {
        answer = Response.json({ id: 2, scope: 'ticket', key: 'flaky-checkout', checkpointed: true })
        const onSaid = vi.fn<(said: string) => void>()
        renderIn(<NoteActions note={NOTE} onSaid={onSaid} />)
        expect(screen.getAllByRole('button').map((b) => b.textContent)).toEqual(['Promote', 'Forget'])
        fireEvent.click(screen.getByRole('button', { name: 'Forget' }))
        fireEvent.change(screen.getByRole('textbox', { name: 'Type memory:2 to confirm' }), {
            target: { value: 'memory:2' },
        })
        fireEvent.click(screen.getByRole('button', { name: 'Forget memory:2' }))
        await vi.waitFor(() => {
            expect(sent).toEqual([{ path: '/api/memory/2/forget', body: { confirm: 'memory:2' } }])
        })
        expect(onSaid).toHaveBeenCalledOnce()
    })

    it('offers nothing on a note whose text is gone', () => {
        renderIn(<NoteActions note={{ ...NOTE, text: null }} onSaid={vi.fn<(said: string) => void>()} />)
        expect(screen.queryAllByRole('button')).toEqual([])
    })

    it('offers no promote for a note whose text is gone', () => {
        renderIn(<NoteActions note={{ ...NOTE, text: null }} onSaid={vi.fn<(said: string) => void>()} />)
        expect(screen.queryByRole('button')).toBeNull()
    })

    it('promotes an invalidated note for every repository, or one the operator picks', async () => {
        answer = Response.json(promoted({ source: NOTE, superseded: null }))
        renderIn(<NoteActions note={NOTE} onSaid={vi.fn<(said: string) => void>()} />)
        fireEvent.click(screen.getByRole('button', { name: 'Promote' }))
        const repos = await screen.findAllByRole('radio')
        expect(repos.map((r) => r.textContent)).toEqual(['every repository', 'api', 'mobile', 'web'])
        expect(repos[0]?.getAttribute('aria-checked')).toBe('true')
        expect(screen.getByTestId('promote-replaces').textContent).toBe(
            'No lesson is in force under flaky-checkout: it replaces none.',
        )
        fireEvent.click(screen.getByRole('radio', { name: 'api' }))
        fireEvent.click(screen.getByRole('button', { name: 'Promote memory:2' }))
        await vi.waitFor(() => {
            expect(sent).toEqual([{ path: '/api/memory/2/promote', body: { text: null, repo: 'api' } }])
        })
    })
})

describe('LessonActions', () => {
    it('renews, and says when the lesson is next due', async () => {
        answer = Response.json({ id: 8, review_at: '2027-01-16T12:00:00Z' })
        const onSaid = vi.fn<(said: string) => void>()
        renderIn(<LessonActions lesson={LESSON} onSaid={onSaid} />)
        fireEvent.click(screen.getByRole('button', { name: 'Renew' }))
        await vi.waitFor(() => {
            expect(onSaid).toHaveBeenCalledOnce()
        })
        expect(onSaid.mock.calls[0]?.[0]).toMatch(/^Lesson 8 is renewed: due for review at .+\.$/u)
        expect(sent).toEqual([{ path: '/api/memory/8/renew', body: undefined }])
    })

    it('forgets only once the ref is typed out exactly, and keeps the lesson when told', async () => {
        answer = Response.json({ id: 8, scope: 'lesson', key: 'web-tests', checkpointed: true })
        const onSaid = vi.fn<(said: string) => void>()
        renderIn(<LessonActions lesson={LESSON} onSaid={onSaid} />)
        fireEvent.click(screen.getByRole('button', { name: 'Forget' }))
        const field = screen.getByRole('textbox', { name: 'Type memory:8 to confirm' })
        const confirm = screen.getByRole<HTMLButtonElement>('button', { name: 'Forget memory:8' })
        for (const typed of ['8', 'memory:80', 'Memory:8']) {
            fireEvent.change(field, { target: { value: typed } })
            expect(confirm.disabled).toBe(true)
        }
        fireEvent.click(screen.getByRole('button', { name: 'Keep it' }))
        expect(screen.queryByRole('form', { name: 'Forget memory:8' })).toBeNull()
        expect(sent).toEqual([])

        fireEvent.click(screen.getByRole('button', { name: 'Forget' }))
        fireEvent.change(screen.getByRole('textbox', { name: 'Type memory:8 to confirm' }), {
            target: { value: 'memory:8' },
        })
        fireEvent.click(screen.getByRole('button', { name: 'Forget memory:8' }))
        await vi.waitFor(() => {
            expect(onSaid).toHaveBeenCalledWith('Memory 8 (lesson `web-tests`) is forgotten: its text is deleted.')
        })
        expect(sent).toEqual([{ path: '/api/memory/8/forget', body: { confirm: 'memory:8' } }])
    })

    it('offers Renew alone on a lesson_review item', () => {
        renderIn(<LessonActions lesson={LESSON} forget={false} onSaid={vi.fn<(said: string) => void>()} />)
        expect(screen.getAllByRole('button').map((b) => b.textContent)).toEqual(['Renew'])
    })
})
