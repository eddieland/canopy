import { cleanup, render, screen, within } from '@testing-library/react'
import { afterEach, describe, expect, it } from 'vitest'

import { readoutDelta } from '@/lib/readout-delta'
import { tipOf } from '@/test-utils'

import { ReadoutTiles } from './readout-tiles'

afterEach(() => {
    cleanup()
})

describe('ReadoutTiles', () => {
    it('names each figure, its hint in a tip', () => {
        render(
            <ReadoutTiles
                testId="health"
                tiles={[
                    { key: 'runs', label: 'runs', value: 25 },
                    {
                        key: 'failed',
                        label: 'failed',
                        hint: 'Runs that did not do what they were started for',
                        value: 3,
                    },
                ]}
            />,
        )
        const list = screen.getByTestId('health-tiles')
        expect(
            within(list)
                .getAllByRole('term')
                .map((t) => t.textContent),
        ).toEqual(['runs', 'failed'])
        expect(
            within(list)
                .getAllByRole('definition')
                .map((d) => d.textContent),
        ).toEqual(['25', '3'])
        expect(tipOf(screen.getByText('failed'))).toBe('Runs that did not do what they were started for')
    })

    it('holds a figure still being read in its place', () => {
        render(<ReadoutTiles testId="ci" tiles={[{ key: 'heads', label: 'heads', value: undefined }]} />)
        expect(screen.getByTestId('ci-heads').textContent).toBe('')
    })

    it('says how each figure moved since the window before, or that it did not', () => {
        render(
            <ReadoutTiles
                testId="health"
                against="the 7 days before"
                tiles={[
                    { key: 'runs', label: 'runs', value: 25, delta: readoutDelta(25, 20, String) },
                    { key: 'failed', label: 'failed', value: 3, delta: readoutDelta(3, 1, String, 'down') },
                    { key: 'cost', label: 'cost', value: 4, delta: readoutDelta(4, 4, String) },
                ]}
            />,
        )
        expect(screen.getByTestId('health-runs-delta').textContent).toBe('+5 on the 7 days before')
        expect(screen.getByTestId('health-failed-delta').textContent).toBe('+2 on the 7 days before')
        expect(screen.getByTestId('health-cost-delta').textContent).toBe('same as the 7 days before')
    })
})
