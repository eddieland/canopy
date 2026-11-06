import { QueryClient } from '@tanstack/react-query'
import { cleanup, fireEvent, screen, within } from '@testing-library/react'
import { afterEach, describe, expect, it } from 'vitest'

import { mockEpicDetails } from '@/api/mocks'
import type { EpicDetail, EpicMember } from '@/api/types'
import { renderRouted, tipOf } from '@/test-utils'

import { EpicBoard } from './epic-board'
import { OutlineLights } from './epic-ids'
import { OutlinePanel } from './epic-outline'

afterEach(() => {
    cleanup()
})

/** The mock epic numbered `id`, as its page reads it, with `fields` over it. */
function detail(id: number, fields: Partial<EpicDetail> = {}): EpicDetail {
    const found = mockEpicDetails.find((d) => d.epic.id === id)
    if (found === undefined) {
        throw new Error(`no mock epic:${String(id)}`)
    }
    return { ...found, ...fields }
}

/** The board of `shown`, beside its requirements and contracts, as its page lights them. */
async function board(shown: EpicDetail) {
    await renderRouted(
        <OutlineLights outline={shown.outline}>
            <EpicBoard detail={shown} />
            <OutlinePanel outline={shown.outline} />
        </OutlineLights>,
        // Nothing reads the server: a ticket's link out waits on a config no test serves.
        { client: new QueryClient({ defaultOptions: { queries: { enabled: false } } }) },
    )
    return screen.getByTestId('epic-board')
}

/** The member `key` of the approved mock epic. */
function member(key: string): EpicMember {
    const found = detail(1).members.find((m) => m.key === key)
    if (found === undefined) {
        throw new Error(`no member ${key}`)
    }
    return found
}

/** The board's entries lit now, by test id. */
function lit(): (string | undefined)[] {
    return screen
        .getAllByTestId(/^entry-B\d$/u)
        .filter((row) => row.dataset.lit !== undefined)
        .map((row) => row.dataset.testid)
}

describe('EpicBoard', () => {
    it('reads each entry with what it cites and the members that fulfil it, or none yet', async () => {
        await board(detail(1))
        const b1 = screen.getByTestId('entry-B1')
        expect(within(b1).getByText('A v2 billing client in web')).toBeTruthy()
        expect(within(b1).getByRole('link', { name: 'ABC-103' })).toBeTruthy()
        expect(within(b1).getByText('review pending')).toBeTruthy()
        expect(within(b1).getByText('R1')).toBeTruthy()
        expect(within(b1).getByText('C1')).toBeTruthy()
        const b2 = screen.getByTestId('entry-B2')
        expect(within(b2).getByRole('link', { name: 'ABC-104' })).toBeTruthy()
        expect(within(b2).getByText('mobile, web')).toBeTruthy()
        expect(within(b2).getByText('B1')).toBeTruthy()
        expect(within(screen.getByTestId('entry-B3')).getByText('none yet')).toBeTruthy()
        expect(within(screen.getByTestId('entry-B4')).getByText('none yet')).toBeTruthy()
        // The board's rows, in the plan's order, and no member of another entry in any of them.
        expect(screen.getAllByTestId(/^entry-B\d$/u).map((row) => row.dataset.testid)).toEqual([
            'entry-B1',
            'entry-B2',
            'entry-B3',
            'entry-B4',
        ])
        expect(within(screen.getByTestId('entry-B1')).queryByText('ABC-104')).toBeNull()
    })

    it('marks a trivial entry, with the reason in its tip', async () => {
        await board(detail(1))
        const mark = within(screen.getByTestId('entry-B4')).getByText('trivial')
        expect(tipOf(mark)).toContain('it deletes one flag and its read, which nothing calls once B1 and B3 ship')
        expect(within(screen.getByTestId('entry-B1')).queryByText('trivial')).toBeNull()
    })

    it('lists the members of no entry under the board, each with its title', async () => {
        const shown = await board(detail(1))
        const none = within(shown).getByTestId('members-of-no-entry')
        expect(within(none).getByRole('heading', { name: 'Members of no entry' })).toBeTruthy()
        expect(within(none).getByRole('link', { name: 'ABC-100' })).toBeTruthy()
        expect(within(none).getByText('Fix the flaky checkout test')).toBeTruthy()
        expect(within(shown).queryByTestId('members-of-dropped-entries')).toBeNull()
        // The rest are on the board's rows, so not listed again.
        expect(within(shown).queryByTestId('members-of-entries')).toBeNull()
    })

    it('lists a member registered against an entry the approved plan dropped, with the entry', async () => {
        const moved = { ...member('ABC-100'), dropped: ['B5'] }
        const shown = await board(detail(1, { members: [member('ABC-103'), member('ABC-104'), moved] }))
        const dropped = within(shown).getByTestId('members-of-dropped-entries')
        expect(within(dropped).getByRole('link', { name: 'ABC-100' })).toBeTruthy()
        expect(dropped.textContent).toContain('registered against B5, which the approved plan no longer holds')
        expect(within(shown).queryByTestId('members-of-no-entry')).toBeNull()
    })

    it("marks a proposed plan's breakdown so, every entry left to file", async () => {
        const shown = await board(detail(2))
        expect(within(shown).getByText('proposed')).toBeTruthy()
        expect(within(shown).queryByText('approved')).toBeNull()
        expect(within(shown).getAllByText('none yet')).toHaveLength(3)
    })

    it('says a plan that does not read is its problem, in a Notice, and draws no half of it', async () => {
        const outline = detail(1).outline
        if (outline === null) {
            throw new Error('the approved mock epic has an outline')
        }
        const broken = { ...outline, problem: 'B2 is repeated', requirements: [], contracts: [], entries: [] }
        const shown = await board(detail(1, { outline: broken }))
        expect(within(shown).getByRole('alert').textContent).toBe('its plan does not read: B2 is repeated')
        expect(within(shown).queryByTestId('breakdown')).toBeNull()
        expect(screen.getByText('none read: its plan does not read, as its breakdown says')).toBeTruthy()
        // The members registered against its entries are still on the page, with the entries they fulfil.
        const registered = within(shown).getByTestId('members-of-entries')
        expect(within(registered).getByRole('link', { name: 'ABC-103' })).toBeTruthy()
        expect(registered.textContent).toContain('registered against B1')
        expect(within(registered).getByRole('link', { name: 'ABC-104' })).toBeTruthy()
        expect(within(shown).getByTestId('members-of-no-entry').textContent).toContain('ABC-100')
    })

    it('is one line naming the plan run at work while there is no plan yet', async () => {
        const shown = await board(detail(3))
        const working = within(shown).getByTestId('plan-run-working')
        expect(working.textContent).toContain('epic:3#4 is writing its plan')
        expect(within(shown).queryByTestId('breakdown')).toBeNull()
    })

    it('says why no plan run works on an epic with no plan', async () => {
        const [working] = detail(3).runs
        if (working === undefined) {
            throw new Error('a plan run')
        }
        const failed = { ...working, status: 'failed', state: 'failed' as const, ended_at: '2026-10-08T12:10:00Z' }
        const epic = { ...detail(3).epic, standing: 'unplanned' as const }
        await board(detail(3, { epic, runs: [failed] }))
        expect(
            screen.getByText('no plan yet: its plan runs ended without one, and a reply starts the next'),
        ).toBeTruthy()
        cleanup()
        const used = [failed, { ...failed, id: 5 }, { ...failed, id: 6 }]
        await board(detail(3, { epic, runs: used }))
        expect(screen.getByText(/^no plan: its 3 plan runs,/u).textContent).toBe(
            'no plan: its 3 plan runs, policy.max_plan_attempts, ended without one',
        )
        cleanup()
        await board(detail(3, { epic: { ...epic, standing: 'queued' }, runs: [] }))
        expect(screen.getByText('no plan yet: the next tick starts its plan run')).toBeTruthy()
    })

    it("lights a contract's entries, and the contract wherever it shows, while it is pointed at", async () => {
        await board(detail(1))
        const [inPanel] = within(screen.getByTestId('epic-outline')).getAllByText('C1')
        if (inPanel === undefined) {
            throw new Error('C1 in the outline')
        }
        fireEvent.pointerEnter(inPanel)
        expect(lit()).toEqual(['entry-B1', 'entry-B2', 'entry-B3'])
        expect(screen.getAllByText('C1').every((id) => id.dataset.lit !== undefined)).toBe(true)
        fireEvent.pointerLeave(inPanel)
        expect(lit()).toEqual([])
        // Its tip reads the board the other way.
        expect(tipOf(inPanel)).toBe('provided by B1 · used by B2, B3')
    })
})
