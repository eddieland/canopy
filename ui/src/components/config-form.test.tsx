import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { cleanup, fireEvent, render, screen } from '@testing-library/react'
import { afterEach, describe, expect, it } from 'vitest'

import { configQuery } from '@/api/queries'
import type { ConfigKey, ConfigSettings } from '@/api/types'

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

/** The form over `settings`, read already and kept fresh, so it draws at once and asks the server nothing. */
function renderForm(settings: ConfigSettings = SETTINGS) {
    const client = new QueryClient({ defaultOptions: { queries: { staleTime: Infinity } } })
    client.setQueryData(configQuery.queryKey, settings)
    return render(
        <QueryClientProvider client={client}>
            <ConfigForm />
        </QueryClientProvider>,
    )
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
    ])('marks %s holding %s invalid, says why under it, and keeps Save off', (name, text, why) => {
        renderForm()
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
    ])('takes %s at %s, within how far the page may take it', (name, text) => {
        renderForm()
        type(name, text)
        const field = screen.getByRole('textbox', { name, description: '' })
        expect(field.getAttribute('aria-invalid')).toBeNull()
        expect(button('Save').disabled).toBe(false)
        expect(screen.getByTestId('config-pending').textContent).toBe('1 unsaved change')
    })

    it('shows the save bar only once something changed, and takes it away when it is typed back', () => {
        renderForm()
        expect(screen.queryByRole('button', { name: 'Save' })).toBeNull()
        type('capacity.max_workers', '4')
        expect(button('Save').disabled).toBe(false)
        type('capacity.max_workers', '3')
        expect(screen.queryByRole('button', { name: 'Save' })).toBeNull()
    })

    it('marks a changed row with its value as read, and lists the change in the bar', () => {
        renderForm()
        expect(screen.queryByText(/was 3/u)).toBeNull()
        type('capacity.max_workers', '5')
        expect(screen.getByText('at most 32 from here · was 3')).toBeTruthy()
        expect(changes()).toEqual(['capacity.max_workers: 3 → 5'])
        expect(screen.queryByTestId('config-one-way')).toBeNull()
    })

    it("names each row's source in a chip, and puts a minute's unit after its field", () => {
        renderForm({ ...SETTINGS, keys: [WORKERS, KICKS, { ...WORKERS, name: 'loop.interval_minutes', bound: 2 }] })
        expect(screen.getAllByText('user')).toHaveLength(2)
        expect(screen.getByText('default')).toBeTruthy()
        expect(screen.getByText('min')).toBeTruthy()
        expect(screen.getByText('Time between ticks')).toBeTruthy()
    })

    it('warns that only the file undoes a stricter change', () => {
        renderForm()
        type('trust.max_flaky_kicks', '1')
        expect(screen.getByTestId('config-one-way').textContent).toBe(
            'trust.max_flaky_kicks: only an edit to config.toml undoes this',
        )
    })

    it('folds the list of changes away past three', () => {
        const counts = ['a', 'b', 'c', 'd', 'e'].map((n) => count(`capacity.max_${n}`))
        renderForm({ ...SETTINGS, keys: counts })
        for (const key of counts) {
            type(key.name, '4')
        }
        expect(changes()).toEqual(['capacity.max_a: 3 → 4', 'capacity.max_b: 3 → 4', 'capacity.max_c: 3 → 4'])
        fireEvent.click(button('Show 2 more'))
        expect(screen.getByText('capacity.max_e: 3 → 4')).toBeTruthy()
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
