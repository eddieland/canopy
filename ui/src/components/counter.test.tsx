import { cleanup, render, screen } from '@testing-library/react'
import { afterEach, describe, expect, it } from 'vitest'

import { Counter } from './counter'

afterEach(() => {
    cleanup()
})

describe('Counter', () => {
    it('shows no value until the first data arrives, and then a zero as a zero', () => {
        const { rerender } = render(
            <Counter label="Running" value={undefined} tone="running">
                of 3 slots
            </Counter>,
        )
        expect(screen.getByText('Running')).toBeDefined()
        expect(screen.queryByText('0')).toBeNull()

        rerender(
            <Counter label="Running" value={0} tone="running">
                of 3 slots
            </Counter>,
        )
        expect(screen.getByText('0')).toBeDefined()
    })

    it('is found by the first word of its label, or the test id it is given', () => {
        render(
            <>
                <Counter label="Blocked, waiting on you" value={2} tone="blocked">
                    tickets
                </Counter>
                <Counter label="Spend today" value="$4.20" tone="plain" testId="spend">
                    since midnight
                </Counter>
            </>,
        )
        expect(screen.getByTestId('counter-blocked').textContent).toContain('2')
        expect(screen.getByTestId('counter-spend').textContent).toContain('$4.20')
    })

    it('has no line when it is given none', () => {
        render(<Counter label="Running" value={2} tone="running" />)
        expect(screen.getByTestId('counter-running').textContent).toBe('Running2')
    })

    it('keeps its whole line on hover when the line is text', () => {
        render(
            <Counter label="Worktrees" value={5} tone="plain">
                2 pools unread: api, web
            </Counter>,
        )
        expect(screen.getByTitle('2 pools unread: api, web')).toBeDefined()
    })
})
