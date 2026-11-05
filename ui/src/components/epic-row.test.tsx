import { cleanup, screen, within } from '@testing-library/react'
import { afterEach, describe, expect, it } from 'vitest'

import { mockEpics } from '@/api/mocks'
import type { EpicSummary } from '@/api/types'
import { renderRouted, tipOf } from '@/test-utils'

import { EpicRow } from './epic-row'

afterEach(() => {
    cleanup()
})

/** The mock epic numbered `id`. */
function epic(id: number): EpicSummary {
    const found = mockEpics.find((e) => e.id === id)
    if (found === undefined) {
        throw new Error(`no mock epic:${String(id)}`)
    }
    return found
}

/** The row `shown` renders, in a list as the page has it. */
async function row(shown: EpicSummary) {
    await renderRouted(
        <ul>
            <EpicRow epic={shown} />
        </ul>,
    )
    return screen.getByTestId(`epic-${String(shown.id)}`)
}

describe('EpicRow', () => {
    it("reads an approved epic's standing, id, repositories, goal's first line, and entries filed", async () => {
        const shown = await row(epic(1))
        expect(within(shown).getByText('approved')).toBeTruthy()
        expect(within(shown).getByText('epic:1')).toBeTruthy()
        expect(within(shown).getByText('api, web, mobile')).toBeTruthy()
        expect(
            within(shown).getByText(
                'Move billing to the v2 API everywhere it is called, web and mobile both, and retire v1 once nothing ' +
                    'reads it.',
            ),
        ).toBeTruthy()
        expect(within(shown).queryByText(/v2 is down/u)).toBeNull()
        expect(within(shown).getByText('2 of 4 entries filed')).toBeTruthy()
    })

    it("says a proposed plan waits on you, with the CLI's word and what it means on hover", async () => {
        const shown = await row(epic(2))
        const word = within(shown).getByText('waiting on you')
        expect(tipOf(word)).toBe('proposed\nIts plan waits on you: approve it, or reply with what to change.')
        expect(within(shown).getByText('0 of 3 entries filed')).toBeTruthy()
    })

    it('says an epic still planning has no breakdown yet', async () => {
        const shown = await row(epic(3))
        expect(within(shown).getByText('planning')).toBeTruthy()
        expect(within(shown).getByText('no breakdown')).toBeTruthy()
    })

    it('says an epic whose runs left no plan is unplanned', async () => {
        const shown = await row({ ...epic(3), standing: 'unplanned' })
        expect(within(shown).getByText('unplanned')).toBeTruthy()
    })

    it('says a proposed plan whose breakdown canopy cannot read is unreadable, not missing', async () => {
        const shown = await row({ ...epic(2), entries: null })
        expect(within(shown).getByText('breakdown unreadable')).toBeTruthy()
    })

    it("links nothing in the goal: it is the operator's words, as text", async () => {
        const said = 'Plan https://example.com/spec <b>bold</b>'
        const shown = await row({ ...epic(3), text: said })
        expect(within(shown).getByText(said)).toBeTruthy()
        // Its one link is its id, to its page.
        expect(
            within(shown)
                .getAllByRole('link')
                .map((link) => link.textContent),
        ).toEqual(['epic:3'])
    })

    it("opens the epic's page from its id", async () => {
        const shown = await row(epic(1))
        expect(within(shown).getByRole('link', { name: 'epic:1' }).getAttribute('href')).toBe('/epics/1')
    })
})
