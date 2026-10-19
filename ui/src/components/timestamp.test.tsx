import { act, cleanup, render, screen } from '@testing-library/react'
import { afterEach, describe, expect, it } from 'vitest'

import { DEFAULT_CLOCK, setClock } from '@/lib/clock'

import { Timestamp } from './timestamp'

afterEach(() => {
    cleanup()
    setClock(DEFAULT_CLOCK)
    localStorage.clear()
})

describe('Timestamp', () => {
    it('reads again on the clock picked in Settings, with the zone when asked', () => {
        // 14:05 local, so the 12-hour reading is 2:05 PM in any time zone.
        const at = new Date(2026, 9, 8, 14, 5).toISOString()
        render(<Timestamp at={at} />)
        expect(screen.getByRole('time').textContent).toMatch(/ 14:05$/u)

        act(() => setClock({ hours: '12' }))
        expect(screen.getByRole('time').textContent).toMatch(/ 2:05 PM$/u)
        act(() => setClock({ zone: true }))
        expect(screen.getByRole('time').textContent).toMatch(/ 2:05 PM \S+$/u)
    })
})
