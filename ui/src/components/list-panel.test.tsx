import { cleanup, render, screen } from '@testing-library/react'
import { afterEach, describe, expect, it } from 'vitest'

import { ListPanel } from './list-panel'

afterEach(() => {
    cleanup()
})

describe('ListPanel', () => {
    it('heads its list with its noun and count, and flips the order of two or more', () => {
        render(
            <ListPanel label="Decisions" count={2} list="pr-decisions">
                <ul>
                    <li>needs reviewer</li>
                    <li>dispatch</li>
                </ul>
            </ListPanel>,
        )
        expect(screen.getByText('Decisions')).toBeDefined()
        expect(screen.getByText('2')).toBeDefined()
        expect(screen.getAllByRole('listitem')).toHaveLength(2)
        expect(screen.getByRole('button', { name: 'newest first: show oldest first' })).toBeDefined()
    })

    it('has nothing to flip with one', () => {
        render(
            <ListPanel label="Runs" count={1} list="pr-runs">
                <p>run:39</p>
            </ListPanel>,
        )
        expect(screen.getByText('run:39')).toBeDefined()
        expect(screen.queryByRole('button')).toBeNull()
    })

    it('is its header alone, counting 0, when it holds none', () => {
        render(
            <ListPanel label="Reviews" count={0} list="pr-reviews">
                <p>no reviews yet</p>
            </ListPanel>,
        )
        expect(screen.getByText('Reviews')).toBeDefined()
        expect(screen.getByText('0')).toBeDefined()
        expect(screen.queryByText('no reviews yet')).toBeNull()
        expect(screen.queryByRole('button')).toBeNull()
    })
})
