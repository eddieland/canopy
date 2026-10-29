import { act, cleanup, render, screen, within } from '@testing-library/react'
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
    steps: [],
    percent_done: null,
    stage: null,
}

/** The same card with steps: one done, one skipped, one working since 12:24 and stuck from 12:33, one not started. */
const STEPPED: RunCard = {
    ...CARD,
    steps: [
        { title: 'add the SSO callback', status: 'done', stage: 'code', since: '2026-10-08T12:14:00Z', stuck_at: null },
        { title: 'ask about SAML', status: 'skipped', stage: null, since: '2026-10-08T12:20:00Z', stuck_at: null },
        {
            title: 'wire the login button',
            status: 'working',
            stage: 'code',
            since: '2026-10-08T12:24:00Z',
            stuck_at: '2026-10-08T12:33:00Z',
        },
        { title: 'push', status: 'not_started', stage: null, since: '2026-10-08T12:14:00Z', stuck_at: null },
    ],
    percent_done: 50,
    stage: 'code',
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

/** Each step the card shows, as its text reads. */
function stepsShown(): (string | null)[] {
    return within(screen.getByRole('list', { name: 'steps' }))
        .getAllByRole('listitem')
        .map((step) => step.textContent)
}

describe('RunCardView steps', () => {
    it('shows how far the steps are, the working stage, and each step with its status', () => {
        render(<RunCardView card={STEPPED} running />)
        expect(screen.getByTestId('run-card').textContent).toContain('steps2 of 4 finished · 50% · stage code')
        expect(stepsShown()).toEqual([
            'doneadd the SSO callback code',
            'skippedask about SAML',
            'workingwire the login button code',
            'not startedpush',
        ])
    })

    it("marks a working step stuck once its time comes, and an ended run's never", () => {
        const { unmount } = render(<RunCardView card={STEPPED} running />)
        act(() => {
            vi.advanceTimersByTime(3 * 60_000)
        })
        expect(stepsShown()[2]).toBe('workingwire the login button code stuck 9m')
        unmount()
        render(<RunCardView card={STEPPED} running={false} />)
        expect(stepsShown()[2]).toBe('workingwire the login button code')
    })

    it('shows no steps for a card that has none', () => {
        render(<RunCardView card={CARD} running />)
        expect(screen.queryByRole('list', { name: 'steps' })).toBeNull()
    })
})

describe('RunCardNow', () => {
    it('says how much of the steps is done when the card has any', () => {
        render(<RunCardNow card={STEPPED} />)
        expect(screen.getByTestId('run-card-now').textContent).toContain('nowrunning the login tests50% done6m ago')
    })

    it('says what the card says it does now, and once it is stale, says so', () => {
        render(<RunCardNow card={CARD} />)
        expect(screen.getByTestId('run-card-now').textContent).toContain('nowrunning the login tests6m ago')
        act(() => {
            vi.advanceTimersByTime(5 * 60_000)
        })
        expect(screen.getByText('stale card')).toBeDefined()
    })
})
