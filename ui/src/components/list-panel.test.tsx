import { cleanup, render, screen } from '@testing-library/react'
import { afterEach, describe, expect, it } from 'vitest'

import { ListPanel } from './list-panel'

afterEach(() => {
    cleanup()
})

describe('ListPanel', () => {
    it('heads its list with its name, its count, and its order once it has two to order', () => {
        render(
            <ListPanel label="Runs" count={2} list="pr-runs" empty="no runs yet">
                <p>the runs</p>
            </ListPanel>,
        )
        expect(screen.getByText('Runs')).toBeDefined()
        expect(screen.getByTestId('list-count').textContent).toBe('2')
        expect(screen.getByTestId('list-count').title).toBe('')
        expect(screen.getByRole('button', { name: /^newest first/u })).toBeDefined()
        expect(screen.getByText('the runs')).toBeDefined()
    })

    it('has no order to flip with one row', () => {
        render(
            <ListPanel label="Runs" count={1} list="pr-runs" empty="no runs yet">
                <p>the run</p>
            </ListPanel>,
        )
        expect(screen.queryByRole('button')).toBeNull()
        expect(screen.getByText('the run')).toBeDefined()
    })

    it('collapses to its header when empty, why on its count’s hover', () => {
        render(
            <ListPanel label="Decisions" count={0} list="pr-decisions" empty="no decisions yet: no tick has named it">
                <p>the decisions</p>
            </ListPanel>,
        )
        expect(screen.getByTestId('list-count').textContent).toBe('0')
        expect(screen.getByTestId('list-count').title).toBe('no decisions yet: no tick has named it')
        expect(screen.queryByText('the decisions')).toBeNull()
        expect(screen.queryByText(/no decisions yet/u)).toBeNull()
    })
})
