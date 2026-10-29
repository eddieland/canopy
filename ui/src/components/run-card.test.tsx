import { act, cleanup, render, screen } from '@testing-library/react'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

import type { RunCard } from '@/api/types'

import { RunCardNow, RunCardView } from './run-card'

const CARD: RunCard = {
    summary: 'The SSO callback is in and its tests pass; see https://example.test/ci for the run.',
    now: 'running the login tests',
    done: [{ step: 'add the SSO callback', proof: 'tests pass: 12/12' }],
    next: ['wire the login button', 'push'],
    stuck: 'CI is down; running the tests here instead',
    at: '2026-10-08T12:24:00Z',
    calls_since: 3,
    stale: false,
    stale_at: '2026-10-08T12:34:00Z',
}

beforeEach(() => {
    vi.useFakeTimers({ now: Date.parse('2026-10-08T12:30:00Z') })
})

afterEach(() => {
    cleanup()
    vi.useRealTimers()
})

describe('RunCardView', () => {
    it('shows the whole card as text, its age in time and tool calls, its links as links', () => {
        render(<RunCardView card={CARD} running />)
        const card = screen.getByTestId('run-card')
        expect(card.textContent).toContain('card6m ago3 tool calls since')
        expect(screen.getByText('running the login tests')).toBeDefined()
        expect(screen.getByText('add the SSO callback')).toBeDefined()
        expect(screen.getByText('tests pass: 12/12')).toBeDefined()
        expect(screen.getByText('wire the login button')).toBeDefined()
        expect(screen.getByText('CI is down; running the tests here instead')).toBeDefined()
        expect(screen.getByRole('link', { name: 'https://example.test/ci' })).toBeDefined()
        expect(screen.queryByText('stale')).toBeNull()
    })

    it('marks a running card stale once its time comes, without a new read', () => {
        render(<RunCardView card={CARD} running />)
        expect(screen.queryByText('stale')).toBeNull()
        act(() => {
            vi.advanceTimersByTime(5 * 60_000)
        })
        expect(screen.getByText('stale')).toBeDefined()
    })

    it('marks it stale at once when the run went too many tool calls without one', () => {
        render(<RunCardView card={{ ...CARD, stale: true, calls_since: 20 }} running />)
        expect(screen.getByText('stale')).toBeDefined()
    })

    it("shows an ended run's last card, which is never stale", () => {
        render(<RunCardView card={{ ...CARD, stuck: null, stale_at: null }} running={false} />)
        expect(screen.getByTestId('run-card').textContent).toContain('last card6m ago3 tool calls before the run ended')
        expect(screen.queryByText('stuck')).toBeNull()
        act(() => {
            vi.advanceTimersByTime(60 * 60_000)
        })
        expect(screen.queryByText('stale')).toBeNull()
    })
})

describe('RunCardNow', () => {
    it('says what the card says it does now, and once it is stale, says so', () => {
        render(<RunCardNow card={CARD} />)
        expect(screen.getByTestId('run-card-now').textContent).toContain('nowrunning the login tests6m ago')
        act(() => {
            vi.advanceTimersByTime(5 * 60_000)
        })
        expect(screen.getByText('stale card')).toBeDefined()
    })
})
