import { QueryClient } from '@tanstack/react-query'
import { cleanup, fireEvent, screen, within } from '@testing-library/react'
import { useState } from 'react'
import { afterEach, describe, expect, it } from 'vitest'

import { configQuery } from '@/api/queries'
import type { ConfigKey, ConfigSettings } from '@/api/types'
import { renderRouted } from '@/test-utils'

import { ConfigForm } from './config-form'

const WORKERS: ConfigKey = {
    name: 'capacity.max_workers',
    value: 3,
    source: 'user',
    kind: 'limit',
    bound: 32,
    looser: 'higher',
    forever_at_zero: false,
    choices: [],
}
const KICKS: ConfigKey = {
    name: 'trust.max_flaky_kicks',
    value: 2,
    source: 'default',
    kind: 'stricter',
    bound: null,
    looser: null,
    forever_at_zero: false,
    choices: [],
}
const SETTINGS: ConfigSettings = {
    keys: [WORKERS, KICKS],
    private_file: '/work/.canopy/config.toml',
    user_file: '/home/me/.config/canopy/config.toml',
    workspace_file: '/work/canopy.toml',
    hash: 'h',
    repos: ['api', 'web'],
    every: null,
}

afterEach(cleanup)

/**
 * The form over `settings`, read already and kept fresh, so it draws at once and asks the server nothing, filtered by
 * `q` as the page's `?q=` would, which its filter field sets.
 */
function renderForm(settings: ConfigSettings = SETTINGS, q?: string): ReturnType<typeof renderRouted> {
    const client = new QueryClient({ defaultOptions: { queries: { staleTime: Infinity } } })
    client.setQueryData(configQuery.queryKey, settings)
    return renderRouted(<Filtered q={q} />, { at: '/settings/limits', client })
}

/** The form with its `?q=` kept here, as the route keeps it in the address. */
function Filtered({ q: initial }: { q: string | undefined }) {
    const [q, setQ] = useState(initial)
    return <ConfigForm q={q} onFilter={setQ} />
}

/** The form's button named `name`. */
function button(name: string): HTMLButtonElement {
    return screen.getByRole<HTMLButtonElement>('button', { name })
}

/** Types `text` into the field named `name`. */
function type(name: string, text: string) {
    fireEvent.change(screen.getByRole('textbox', { name }), { target: { value: text } })
}

describe('ConfigForm', () => {
    it.each([
        ['capacity.max_workers', '9999', 'at most 32 from here; set more in the file'],
        ['capacity.max_workers', 'abc', 'not a whole number'],
        ['trust.max_flaky_kicks', '3', 'only fewer from here: at most 2; set more in the file'],
        ['trust.max_flaky_kicks', '1.5', 'not a whole number'],
        ['capacity.max_workers', '', 'empty: type a count, or Discard to keep 3'],
    ])('marks %s holding %s invalid, says why under it, and keeps Save off', async (name, text, why) => {
        await renderForm()
        type(name, text)
        const field = screen.getByRole('textbox', { name, description: why })
        expect(field.getAttribute('aria-invalid')).toBe('true')
        expect(button('Save').disabled).toBe(true)
        // The field in error is a change: Discard is on, and the bar says so.
        expect(button('Discard').disabled).toBe(false)
        expect(screen.getByTestId('config-pending').textContent).toBe('1 unsaved change, 1 to fix before saving')
    })

    it.each([
        ['capacity.max_workers', '32'],
        ['trust.max_flaky_kicks', '1'],
    ])('takes %s at %s, within how far the page may take it', async (name, text) => {
        await renderForm()
        type(name, text)
        const field = screen.getByRole('textbox', { name, description: '' })
        expect(field.getAttribute('aria-invalid')).toBeNull()
        expect(button('Save').disabled).toBe(false)
        expect(screen.getByTestId('config-pending').textContent).toBe('1 unsaved change')
    })

    it('shows the save bar only once something changed, and takes it away when it is typed back', async () => {
        await renderForm()
        expect(screen.queryByRole('button', { name: 'Save' })).toBeNull()
        type('capacity.max_workers', '4')
        expect(button('Save').disabled).toBe(false)
        type('capacity.max_workers', '3')
        expect(screen.queryByRole('button', { name: 'Save' })).toBeNull()
    })

    it('marks a changed row with its value as read, and lists the change in the bar', async () => {
        await renderForm()
        expect(screen.queryByText(/was 3/u)).toBeNull()
        type('capacity.max_workers', '5')
        expect(screen.getByText('at most 32 from here · was 3')).toBeTruthy()
        expect(changes()).toEqual(['capacity.max_workers: 3 → 5'])
        expect(screen.queryByTestId('config-one-way')).toBeNull()
    })

    it("names each row's source in a chip, and puts a minute's unit after its field", async () => {
        await renderForm({
            ...SETTINGS,
            keys: [WORKERS, KICKS, { ...WORKERS, name: 'loop.interval_minutes', bound: 2 }],
        })
        expect(screen.getAllByText('user')).toHaveLength(2)
        expect(screen.getByText('default')).toBeTruthy()
        expect(screen.getByText('min')).toBeTruthy()
        expect(screen.getByText('Time between ticks')).toBeTruthy()
    })

    it("counts each repository's own count as a change of its own, as the bar lists them", async () => {
        const slots: ConfigKey = { ...WORKERS, name: 'capacity.repo_slots', value: { api: 2, web: 4 } }
        await renderForm({ ...SETTINGS, keys: [slots] })
        type('capacity.repo_slots.api', '3')
        type('capacity.repo_slots.web', '5')
        expect(screen.getByTestId('config-pending').textContent).toBe('2 unsaved changes')
        expect(changes()).toEqual(['capacity.repo_slots.api: 2 → 3', 'capacity.repo_slots.web: 4 → 5'])
    })

    it('warns that only the file undoes a stricter change', async () => {
        await renderForm()
        type('trust.max_flaky_kicks', '1')
        expect(screen.getByTestId('config-one-way').textContent).toBe(
            'trust.max_flaky_kicks: only an edit to config.toml undoes this',
        )
    })

    it('folds the list of changes away past three', async () => {
        const counts = ['a', 'b', 'c', 'd', 'e'].map((n) => count(`capacity.max_${n}`))
        await renderForm({ ...SETTINGS, keys: counts })
        for (const key of counts) {
            type(key.name, '4')
        }
        expect(changes()).toEqual(['capacity.max_a: 3 → 4', 'capacity.max_b: 3 → 4', 'capacity.max_c: 3 → 4'])
        fireEvent.click(button('Show 2 more'))
        expect(screen.getByText('capacity.max_e: 3 → 4')).toBeTruthy()
    })

    it("indexes the bands, counting each one's keys set in this workspace and its rows changed", async () => {
        await renderForm({ ...SETTINGS, keys: [{ ...WORKERS, source: 'private' }, KICKS] })
        const index = screen.getByRole('navigation', { name: 'Bands' })
        expect(
            within(index)
                .getAllByRole('link')
                .map((link) => link.textContent),
        ).toEqual(['Capacity1 set', 'Guardrails'])
        type('trust.max_flaky_kicks', '1')
        expect(within(index).getByRole('link', { name: /^Guardrails/u }).textContent).toBe('Guardrails1 unsaved')
    })

    it('makes each row the anchor of its key', async () => {
        await renderForm()
        const row = document.querySelector<HTMLElement>('[id="capacity.max_workers"]')
        expect(row && within(row).getByRole('textbox', { name: 'capacity.max_workers' })).toBeTruthy()
    })

    it('shows only the rows the filter matches, and says how many', async () => {
        await renderForm(SETTINGS, 'flaky')
        expect(screen.queryByRole('textbox', { name: 'capacity.max_workers' })).toBeNull()
        expect(screen.getByRole('textbox', { name: 'trust.max_flaky_kicks' })).toBeTruthy()
        expect(screen.getByText('1 of 2')).toBeTruthy()
        const index = screen.getByRole('navigation', { name: 'Bands' })
        expect(within(index).getByRole('link', { name: 'Capacity' }).dataset['hidden']).toBe('true')
    })

    it('keeps a row with an unsaved change in view whatever the filter says', async () => {
        await renderForm()
        type('capacity.max_workers', '5')
        fireEvent.change(screen.getByRole('searchbox', { name: 'Filter settings by label or key' }), {
            target: { value: 'flaky' },
        })
        expect(screen.getByRole('textbox', { name: 'capacity.max_workers' })).toBeTruthy()
        expect(screen.getByText('2 of 2')).toBeTruthy()
    })

    it('says so when nothing matches, and Escape empties the filter', async () => {
        await renderForm(SETTINGS, 'nothing like it')
        expect(screen.getByText("no setting's label or key holds “nothing like it”")).toBeTruthy()
        fireEvent.keyDown(screen.getByRole('searchbox', { name: 'Filter settings by label or key' }), { key: 'Escape' })
        expect(screen.getByRole('textbox', { name: 'capacity.max_workers' })).toBeTruthy()
        expect(screen.getByRole<HTMLInputElement>('searchbox', { name: 'Filter settings by label or key' }).value).toBe(
            '',
        )
    })

    it('shows a key at its strictest as its value beside a lock, not as a control', async () => {
        await renderForm({ ...SETTINGS, keys: [{ ...KICKS, value: 0 }] })
        expect(screen.queryByRole('textbox', { name: 'trust.max_flaky_kicks' })).toBeNull()
        expect(screen.getByText('strictest · loosen in config.toml')).toBeTruthy()
        expect(screen.getByText('0')).toBeTruthy()
    })

    it('asks before dropping an authorized replier, and drops it only on Drop', async () => {
        const repliers: ConfigKey = { ...KICKS, name: 'trust.authorized_repliers', value: ['me', 'bot'] }
        await renderForm({ ...SETTINGS, keys: [repliers] })
        fireEvent.click(screen.getByRole('checkbox', { name: 'me' }))
        const asking = screen.getByRole('group', { name: 'Drop me?' })
        expect(screen.queryByRole('button', { name: 'Save' })).toBeNull()
        fireEvent.click(within(asking).getByRole('button', { name: 'Keep' }))
        expect(screen.queryByRole('group', { name: 'Drop me?' })).toBeNull()
        expect(screen.getByRole('checkbox', { name: 'me' }).getAttribute('aria-checked')).toBe('true')
        fireEvent.click(screen.getByRole('checkbox', { name: 'me' }))
        fireEvent.click(within(screen.getByRole('group', { name: 'Drop me?' })).getByRole('button', { name: 'Drop' }))
        expect(changes()).toEqual(['trust.authorized_repliers: me, bot → bot'])
    })
})

/** A count like `capacity.max_workers`, named `name`. */
function count(name: string): ConfigKey {
    return { ...WORKERS, name }
}

/** The changes the save bar lists, a line each, as shown. */
function changes(): (string | null)[] {
    return [...screen.getByTestId('config-changes').querySelectorAll('li')].map((li) => li.textContent)
}
