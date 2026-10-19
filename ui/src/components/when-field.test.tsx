import { cleanup, render, screen } from '@testing-library/react'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

import { Fields } from './fields'
import { WhenField } from './when-field'

beforeEach(() => {
    vi.useFakeTimers({ now: Date.parse('2026-10-08T12:00:00Z') })
})

afterEach(() => {
    cleanup()
    vi.useRealTimers()
})

describe('WhenField', () => {
    it('says when it started and how long it has run while it runs', () => {
        render(
            <Fields>
                <WhenField started="2026-10-08T11:57:00Z" ended={null} />
            </Fields>,
        )
        const field = screen.getByRole('definition')
        expect(field.textContent).toMatch(/^\S+ \d+ \d\d:\d\dfor 3m$/u)
    })

    it('says when it started, when it ended, how long it took, and how long ago it ended', () => {
        render(
            <Fields>
                <WhenField started="2026-10-08T11:00:00Z" ended="2026-10-08T11:29:00Z" />
            </Fields>,
        )
        expect(screen.getByTitle('how long it ran').textContent).toBe('29m')
        expect(screen.getByRole('definition').textContent).toContain('· 29m')
        expect(screen.getByRole('definition').textContent).toContain('ended 31m ago')
    })
})
