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
    steps: [],
    percent: null,
    stage: null,
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

describe('RunCardView steps', () => {
    const STEPS: RunCard = {
        ...CARD,
        stuck: null,
        steps: [
            { title: 'add the SSO callback', status: 'done', stage: 'api', stuck_at: null },
            { title: 'wire the login button', status: 'working', stage: 'web', stuck_at: '2026-10-08T12:39:00Z' },
            { title: 'a dark-mode icon', status: 'skipped', stage: null, stuck_at: null },
            { title: 'push', status: 'not_started', stage: null, stuck_at: null },
        ],
        percent: 33,
        stage: 'web',
    }

    it('says how much is done and the stage under way, then each step with where it stands', () => {
        render(<RunCardView card={STEPS} running />)
        const steps = screen.getByTestId('run-card-steps')
        expect(steps.textContent).toContain('33% done · stage web')
        const items = screen.getAllByRole('listitem').map((item) => item.textContent)
        expect(items).toEqual([
            'doneadd the SSO callback · api',
            'workingwire the login button · web',
            'skippeda dark-mode icon',
            'to dopush',
        ])
    })

    it('shows a working step stuck once it has worked past its time, without a new read', () => {
        render(<RunCardView card={STEPS} running />)
        expect(screen.queryByText('stuck')).toBeNull()
        act(() => {
            vi.advanceTimersByTime(10 * 60_000)
        })
        expect(screen.getAllByText('stuck')).toHaveLength(1)
    })

    it('puts the share done on the one-line card', () => {
        render(<RunCardNow card={STEPS} />)
        expect(screen.getByTestId('run-card-now').textContent).toContain('running the login tests33%')
    })
})
