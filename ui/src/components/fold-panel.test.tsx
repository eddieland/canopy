import { cleanup, fireEvent, render, screen } from '@testing-library/react'
import { afterEach, describe, expect, it } from 'vitest'

import { FoldPanel } from './fold-panel'

afterEach(() => {
    cleanup()
})

describe('FoldPanel', () => {
    it('arrives folded to its header and readout, and opens its rows on Show', () => {
        render(
            <FoldPanel label="Memory" what="memory" readout="wrote 2 · read none">
                <p>a note it wrote</p>
            </FoldPanel>,
        )
        expect(screen.getByText('Memory')).toBeDefined()
        expect(screen.getByText('wrote 2 · read none')).toBeDefined()
        expect(screen.queryByText('a note it wrote')).toBeNull()

        fireEvent.click(screen.getByRole('button', { name: 'Show memory', expanded: false }))
        expect(screen.getByText('a note it wrote')).toBeDefined()
        fireEvent.click(screen.getByRole('button', { name: 'Hide memory', expanded: true }))
        expect(screen.queryByText('a note it wrote')).toBeNull()
    })
})
