import { cleanup, render, screen } from '@testing-library/react'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

import { DEFAULT_CLOCK } from '@/lib/clock'
import { localTime } from '@/lib/time'
import { tipOf } from '@/test-utils'

import { Age } from './age'

beforeEach(() => {
    vi.useFakeTimers({ now: Date.parse('2026-10-08T12:00:00Z') })
})

afterEach(() => {
    cleanup()
    vi.useRealTimers()
})

describe('Age', () => {
    it('says how long something has stood open, bare or as a moment ago', () => {
        const { rerender } = render(<Age at="2026-10-08T11:57:00Z" />)
        expect(screen.getByRole('time').textContent).toBe('3m')
        rerender(<Age at="2026-10-08T11:57:00Z" variant="ago" />)
        expect(screen.getByRole('time').textContent).toBe('3m ago')
    })

    it('says how long something has run, and once it ended, how long ago that was', () => {
        const { rerender } = render(<Age variant="span" started="2026-10-08T11:00:00Z" ended={null} />)
        expect(screen.getByRole('time').textContent).toBe('for 1h')
        expect(screen.getByRole('time').getAttribute('datetime')).toBe('2026-10-08T11:00:00Z')

        rerender(<Age variant="span" started="2026-10-08T11:00:00Z" ended="2026-10-08T11:55:00Z" />)
        expect(screen.getByRole('time').textContent).toBe('ended 5m ago')
        expect(screen.getByRole('time').getAttribute('datetime')).toBe('2026-10-08T11:55:00Z')
    })

    it("gives the local time in its tip, on hover and on the keyboard's focus", () => {
        render(<Age at="2026-10-08T11:57:00Z" />)
        expect(tipOf(screen.getByRole('time'))).toBe(localTime('2026-10-08T11:57:00Z', DEFAULT_CLOCK))
    })
})
