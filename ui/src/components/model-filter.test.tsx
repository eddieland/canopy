import { cleanup, fireEvent, render, screen, within } from '@testing-library/react'
import { useState } from 'react'
import { afterEach, describe, expect, it } from 'vitest'

import { ModelFilter } from './model-filter'

afterEach(cleanup)

const MODELS = ['anthropic/claude-haiku-4-5', 'anthropic/claude-opus-4-1', 'openai/gpt-5', 'openai/gpt-5@high']

/** A `ModelFilter` that keeps what is chosen, as the runs page's search does. */
function Filter({ start }: { start?: string }) {
    const [chosen, setChosen] = useState(start)
    return <ModelFilter models={MODELS} chosen={chosen} onChoose={setChosen} />
}

function options(list: HTMLElement): [string | null, string | null][] {
    return within(list)
        .getAllByRole('option')
        .map((o) => [o.textContent, o.getAttribute('aria-checked')])
}

describe('ModelFilter', () => {
    it('says it filters nothing, and lists every model whole under the item that clears it', () => {
        render(<Filter />)
        fireEvent.click(screen.getByRole('button', { name: 'Filter by model: every model' }))
        expect(options(screen.getByRole('listbox', { name: 'Models' }))).toEqual([
            ['every model', 'true'],
            ...MODELS.map((m): [string, string] => [m, 'false']),
        ])
    })

    it('narrows to the ids holding what is typed, and sets the one picked, closing the list', () => {
        render(<Filter />)
        fireEvent.click(screen.getByRole('button', { name: 'Filter by model: every model' }))
        fireEvent.change(screen.getByRole('combobox', { name: 'Find a model' }), { target: { value: 'GPT' } })
        const list = screen.getByRole('listbox', { name: 'Models' })
        expect(options(list).map(([name]) => name)).toEqual(['openai/gpt-5', 'openai/gpt-5@high'])
        fireEvent.click(within(list).getByRole('option', { name: 'openai/gpt-5@high' }))
        expect(screen.queryByRole('listbox')).toBeNull()
        fireEvent.click(screen.getByRole('button', { name: 'Filter by model: openai/gpt-5@high' }))
        fireEvent.click(screen.getByRole('option', { name: 'every model' }))
        expect(screen.getByRole('button', { name: 'Filter by model: every model' })).toBeDefined()
    })
})
