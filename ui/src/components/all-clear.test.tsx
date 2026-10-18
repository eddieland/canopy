import { cleanup, render, screen, waitFor } from '@testing-library/react'
import { afterEach, describe, expect, it } from 'vitest'

import { StreamContext } from '@/hooks/use-loop-down'

import { AllClear } from './all-clear'

afterEach(cleanup)

describe('AllClear', () => {
    it('says nothing needs the operator while the loop answers', () => {
        render(<AllClear />)
        expect(screen.getByTestId('all-clear').textContent).toContain('Nothing needs you.')
    })

    it("says nothing needed them as of the drop, and never celebrates, while the loop isn't answering", async () => {
        render(
            <StreamContext value={{ status: 'reconnecting', downSince: Date.now() - 60_000 }}>
                <AllClear />
            </StreamContext>,
        )
        await waitFor(() => {
            expect(screen.getByTestId('all-clear').textContent).toMatch(/^Nothing needed you as of .+\./u)
        })
        expect(screen.getByTestId('all-clear').textContent).not.toContain('all clear')
    })
})
