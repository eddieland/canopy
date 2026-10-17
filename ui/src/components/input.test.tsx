import { cleanup, fireEvent, render, screen } from '@testing-library/react'
import { afterEach, describe, expect, it, vi } from 'vitest'

import { SearchField } from './input'

afterEach(() => {
    cleanup()
})

function renderField(value: string, onClear = vi.fn<() => void>()) {
    render(
        <SearchField
            value={value}
            onChange={() => {}}
            onClear={onClear}
            clearLabel="Clear the filter"
            aria-label="Filter tickets"
            idle={<kbd>/</kbd>}
        />,
    )
    return onClear
}

describe('SearchField', () => {
    it('shows what it holds in place of a clear button while empty', () => {
        renderField('')
        expect(screen.getByRole('searchbox', { name: 'Filter tickets' })).toBeDefined()
        expect(screen.getByText('/')).toBeDefined()
        expect(screen.queryByRole('button')).toBeNull()
    })

    it('offers a clear button, by its name, while it holds text, which empties it through onClear', () => {
        const onClear = renderField('export')
        expect(screen.queryByText('/')).toBeNull()
        fireEvent.click(screen.getByRole('button', { name: 'Clear the filter' }))
        expect(onClear).toHaveBeenCalledOnce()
    })
})
