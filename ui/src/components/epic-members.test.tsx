import { QueryClient } from '@tanstack/react-query'
import { cleanup, fireEvent, screen, waitFor, within } from '@testing-library/react'
import type { Middleware } from 'openapi-fetch'
import { afterEach, beforeEach, describe, expect, it } from 'vitest'

import { api } from '@/api/client'
import { mockEpicDetails } from '@/api/mocks'
import type { EpicDetail } from '@/api/types'
import { renderRouted } from '@/test-utils'

import { EpicBoard } from './epic-board'
import { OutlineLights } from './epic-ids'

// What the server stand-in answers, by `METHOD path`, and what was sent to it. A read of the epic after a write finds
// the mock as it was unless a test answers otherwise: the board shows what the page holds, not the write.
let answers: Record<string, () => Response> = {}
let sent: { method: string; path: string; body: unknown }[] = []
const server: Middleware = {
    async onRequest({ request }) {
        const path = new URL(request.url).pathname
        const body: unknown = request.method === 'POST' ? await request.json() : undefined
        sent.push({ method: request.method, path, body })
        const answer = answers[`${request.method} ${path}`]
        return answer === undefined ? Response.json({ detail: 'not found' }, { status: 404 }) : answer()
    },
}

beforeEach(() => {
    answers = Object.fromEntries(
        mockEpicDetails.map((epic) => [`GET /api/epics/${epic.epic.id}`, () => Response.json(epic)]),
    )
    sent = []
    api.use(server)
})

afterEach(() => {
    api.eject(server)
    cleanup()
})

/** The mock epic numbered `id`, as its page reads it. */
function detail(id: number): EpicDetail {
    const found = mockEpicDetails.find((d) => d.epic.id === id)
    if (found === undefined) {
        throw new Error(`no mock epic:${String(id)}`)
    }
    return found
}

/** A refusal, as the server answers one: 409, naming its guard. */
function refusal(guard: string, reason: string): () => Response {
    return () => Response.json({ detail: { guard, reason } }, { status: 409 })
}

/** The board of mock epic `id`, as its page lights it. */
async function board(id: number): Promise<HTMLElement> {
    await renderRouted(
        <OutlineLights outline={detail(id).outline}>
            <EpicBoard detail={detail(id)} />
        </OutlineLights>,
        // Only what a write sends, and what it reads again, reaches the server: a ticket's link out waits on a config.
        { client: new QueryClient({ defaultOptions: { queries: { enabled: false } } }) },
    )
    return screen.getByTestId('epic-board')
}

/** What was sent to the server but reads. */
function writes(): { method: string; path: string; body: unknown }[] {
    return sent.filter((request) => request.method !== 'GET')
}

describe("an epic's members, from its board", () => {
    it("registers a ticket on an entry with none yet, that entry picked, and says so in the CLI's words", async () => {
        answers['POST /api/epics/1/members'] = () => Response.json({ key: 'ABC-105', added: true, entries: ['B3'] })
        const shown = await board(1)
        // Only the entries with no member offer it.
        expect(within(screen.getByTestId('entry-B1')).queryByRole('button', { name: 'Register a ticket' })).toBeNull()
        fireEvent.click(within(screen.getByTestId('entry-B3')).getByRole('button', { name: 'Register a ticket' }))
        const form = screen.getByRole('form', { name: 'Register a ticket against B3' })
        expect(within(form).getByRole('checkbox', { name: /^B3 /u }).getAttribute('aria-checked')).toBe('true')
        expect(within(form).getByRole('checkbox', { name: /^B1 /u }).getAttribute('aria-checked')).toBe('false')
        // The key field has the focus, and what adding does and does not is said where it is done.
        const key = within(form).getByRole('textbox', { name: 'Ticket key' })
        expect(document.activeElement).toBe(key)
        expect(within(form).getByText(/authorizes no work/u).textContent).toBe(
            'Adding a ticket authorizes no work: a member is worked once you label it or start it. Registering a ' +
                'member again replaces its entries; check none for a ticket the breakdown did not foresee.',
        )
        fireEvent.change(key, { target: { value: ' ABC-105 ' } })
        fireEvent.click(within(form).getByRole('button', { name: 'Add and register' }))
        await waitFor(() => {
            expect(within(shown).getByRole('status').textContent).toContain(
                'Added ABC-105 to epic:1. Registered ABC-105 against B3.',
            )
        })
        expect(writes()).toEqual([
            { method: 'POST', path: '/api/epics/1/members', body: { key: 'ABC-105', entries: ['B3'] } },
        ])
        expect(screen.queryByRole('form')).toBeNull()
    })

    it('adds a ticket for several entries, or registers a member again, from the foot', async () => {
        answers['POST /api/epics/1/members'] = () =>
            Response.json({ key: 'ABC-103', added: false, entries: ['B1', 'B4'] })
        const shown = await board(1)
        fireEvent.click(within(shown).getByRole('button', { name: 'Add a ticket' }))
        const form = screen.getByRole('form', { name: 'Add a ticket' })
        // None picked: with none checked, it adds a ticket of no entry.
        expect(
            within(form)
                .getAllByRole('checkbox')
                .map((box) => box.getAttribute('aria-checked')),
        ).toEqual(['false', 'false', 'false', 'false'])
        expect(within(form).getByRole('button', { name: 'Add' }).title).toBe('canopy epic add epic:1 KEY --no-entry')
        fireEvent.change(within(form).getByRole('textbox', { name: 'Ticket key' }), { target: { value: 'ABC-103' } })
        fireEvent.click(within(form).getByRole('checkbox', { name: /^B4 /u }))
        fireEvent.click(within(form).getByRole('checkbox', { name: /^B1 /u }))
        // A member already: the button says it registers it again, its entries in the breakdown's order.
        const again = within(form).getByRole('button', { name: 'Register again' })
        expect(again.title).toBe('canopy epic add epic:1 ABC-103 --entry B1 --entry B4')
        fireEvent.click(again)
        await waitFor(() => {
            expect(within(shown).getByRole('status').textContent).toContain(
                'Already a member: ABC-103. Registered ABC-103 against B1, B4.',
            )
        })
        expect(writes()).toEqual([
            { method: 'POST', path: '/api/epics/1/members', body: { key: 'ABC-103', entries: ['B1', 'B4'] } },
        ])
    })

    it('keeps the form open on a refusal, naming its guard', async () => {
        answers['POST /api/epics/1/members'] = refusal('other_epic', 'ABC-140 is a member of epic:2')
        await board(1)
        fireEvent.click(within(screen.getByTestId('entry-B4')).getByRole('button', { name: 'Register a ticket' }))
        const form = screen.getByRole('form', { name: 'Register a ticket against B4' })
        fireEvent.change(within(form).getByRole('textbox', { name: 'Ticket key' }), { target: { value: 'ABC-140' } })
        fireEvent.click(within(form).getByRole('button', { name: 'Add and register' }))
        expect((await within(form).findByRole('alert')).textContent).toBe(
            'refused (other_epic): ABC-140 is a member of epic:2',
        )
        expect(within(form).getByRole('textbox', { name: 'Ticket key' })).toHaveProperty('value', 'ABC-140')
    })

    it('sends nothing for a blank key, and Cancel or Escape closes the form', async () => {
        const shown = await board(1)
        fireEvent.click(within(shown).getByRole('button', { name: 'Add a ticket' }))
        const form = screen.getByRole('form', { name: 'Add a ticket' })
        const key = within(form).getByRole('textbox', { name: 'Ticket key' })
        fireEvent.change(key, { target: { value: '  ' } })
        expect(within(form).getByRole('button', { name: 'Add' })).toHaveProperty('disabled', true)
        fireEvent.keyDown(key, { key: 'Escape' })
        expect(screen.queryByRole('form')).toBeNull()
        fireEvent.click(within(screen.getByTestId('entry-B3')).getByRole('button', { name: 'Register a ticket' }))
        fireEvent.click(screen.getByRole('button', { name: 'Cancel' }))
        expect(screen.queryByRole('form')).toBeNull()
        expect(writes()).toEqual([])
    })

    it('adds a ticket of no entry alone before a plan is approved, and says why', async () => {
        answers['POST /api/epics/2/members'] = () => Response.json({ key: 'ABC-140', added: true, entries: [] })
        const shown = await board(2)
        // A proposed breakdown takes no registration.
        expect(within(shown).queryByRole('button', { name: 'Register a ticket' })).toBeNull()
        fireEvent.click(within(shown).getByRole('button', { name: 'Add a ticket' }))
        const form = screen.getByRole('form', { name: 'Add a ticket' })
        expect(within(form).queryAllByRole('checkbox')).toEqual([])
        expect(within(form).getByText(/authorizes no work/u).textContent).toBe(
            'No plan of it is approved yet, so a ticket joins as a member of no entry. Adding a ticket authorizes ' +
                'no work: a member is worked once you label it or start it. Registering a member again replaces its ' +
                'entries.',
        )
        fireEvent.change(within(form).getByRole('textbox', { name: 'Ticket key' }), { target: { value: 'ABC-140' } })
        fireEvent.click(within(form).getByRole('button', { name: 'Add' }))
        await waitFor(() => {
            expect(within(shown).getByRole('status').textContent).toContain(
                'Added ABC-140 to epic:2. Registered ABC-140 against no entry.',
            )
        })
        expect(writes()).toEqual([
            { method: 'POST', path: '/api/epics/2/members', body: { key: 'ABC-140', entries: [] } },
        ])
    })

    it('removes a member once asked, under the row it was asked from', async () => {
        answers['DELETE /api/epics/1/members/ABC-104'] = () => Response.json({ key: 'ABC-104' })
        const shown = await board(1)
        fireEvent.click(within(screen.getByTestId('entry-B2')).getByRole('button', { name: 'Remove ABC-104' }))
        // Asked first: nothing is sent until the operator says so.
        expect(writes()).toEqual([])
        const under = within(screen.getByTestId('entry-B2-open'))
        expect(under.getByText('It stops being a member; the ticket and its work stay as they are.')).toBeTruthy()
        fireEvent.click(under.getByRole('button', { name: 'Keep it' }))
        expect(screen.queryByRole('button', { name: 'Remove ABC-104 from epic:1' })).toBeNull()
        expect(writes()).toEqual([])

        fireEvent.click(within(screen.getByTestId('entry-B2')).getByRole('button', { name: 'Remove ABC-104' }))
        fireEvent.click(screen.getByRole('button', { name: 'Remove ABC-104 from epic:1' }))
        await waitFor(() => {
            expect(within(shown).getByRole('status').textContent).toContain('Removed ABC-104 from epic:1.')
        })
        expect(writes()).toEqual([{ method: 'DELETE', path: '/api/epics/1/members/ABC-104', body: undefined }])
    })

    it('removes a member of no entry from its line under the board, and says a refusal there', async () => {
        answers['DELETE /api/epics/1/members/ABC-100'] = refusal('inside_run', 'canopy refuses this inside a run')
        await board(1)
        const none = screen.getByTestId('members-of-no-entry')
        fireEvent.click(within(none).getByRole('button', { name: 'Remove ABC-100' }))
        fireEvent.click(within(none).getByRole('button', { name: 'Remove ABC-100 from epic:1' }))
        expect((await within(none).findByRole('alert')).textContent).toBe(
            'refused (inside_run): canopy refuses this inside a run',
        )
        expect(writes()).toEqual([{ method: 'DELETE', path: '/api/epics/1/members/ABC-100', body: undefined }])
    })
})
