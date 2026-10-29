import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { act, cleanup, fireEvent, render, screen } from '@testing-library/react'
import type { Middleware } from 'openapi-fetch'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

import { api } from '@/api/client'
import type { RunCard, RunCardQuestion } from '@/api/types'

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
    question: null,
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

function renderQuestion(question: RunCardQuestion, running = true) {
    return render(
        <QueryClientProvider client={new QueryClient()}>
            <RunCardView card={{ ...CARD, question }} running={running} answers={{ kind: 'run', id: 41 }} />
        </QueryClientProvider>,
    )
}

describe('RunCardView question', () => {
    const QUESTION: RunCardQuestion = {
        ask: 'Keep the password form beside the SSO button, or hide it behind a link?',
        options: ['keep both side by side', 'hide the form behind a link'],
        recommend: 'B',
        asked_at: '2026-10-08T12:24:00Z',
        answer: null,
        answered_at: null,
    }
    // Every answer the card sends, and what the server stand-in answers next.
    let sent: { path: string; body: unknown }[] = []
    let replies: Response[] = []
    const server: Middleware = {
        async onRequest({ request }) {
            sent.push({ path: new URL(request.url).pathname, body: await request.json() })
            return (
                replies.shift() ??
                Response.json({ letter: 'B', option: QUESTION.options[1], already: false, heard: true })
            )
        },
    }

    beforeEach(() => {
        vi.useRealTimers()
        sent = []
        replies = []
        api.use(server)
    })

    afterEach(() => {
        api.eject(server)
    })

    it('asks you, names each option by letter and the one recommended, and answers with the one you pick', async () => {
        renderQuestion(QUESTION)
        const asked = screen.getByTestId('run-card-question')
        expect(asked.textContent).toContain('asks you')
        expect(asked.textContent).toContain('Bhide the form behind a link · recommended')
        fireEvent.click(screen.getByRole('button', { name: 'Answer B: hide the form behind a link' }))
        expect(
            await screen.findByText(
                'Answered B: hide the form behind a link. Its agent hears it on its next tool call.',
            ),
        ).toBeDefined()
        expect(sent).toEqual([{ path: '/api/runs/41/answers', body: { letter: 'B', asked_at: QUESTION.asked_at } }])
    })

    it('marks your answer, and offers the other options to change it', () => {
        renderQuestion({ ...QUESTION, answer: 'B', answered_at: '2026-10-08T12:26:00Z' })
        expect(screen.getByTestId('run-card-question').textContent).toContain('answered B')
        expect(screen.getByText(/your answer/u)).toBeDefined()
        expect(screen.getAllByRole('button').map((b) => b.getAttribute('aria-label'))).toEqual([
            'Answer A: keep both side by side',
        ])
    })

    it("shows an ended run's question as never answered, with nothing to press", () => {
        renderQuestion(QUESTION, false)
        expect(screen.getByTestId('run-card-question').textContent).toContain('never answered')
        expect(screen.queryAllByRole('button')).toEqual([])
    })

    it('drops what an answer said once the card asks another question', async () => {
        const { rerender } = renderQuestion(QUESTION)
        fireEvent.click(screen.getByRole('button', { name: 'Answer B: hide the form behind a link' }))
        expect(await screen.findByText(/^Answered B/u)).toBeDefined()
        rerender(
            <QueryClientProvider client={new QueryClient()}>
                <RunCardView
                    card={{ ...CARD, question: { ...QUESTION, asked_at: '2026-10-08T12:29:00Z' } }}
                    running
                    answers={{ kind: 'run', id: 41 }}
                />
            </QueryClientProvider>,
        )
        expect(screen.queryByText(/^Answered B/u)).toBeNull()
    })

    it('names the guard that refused an answer', async () => {
        replies = [
            Response.json(
                { detail: { guard: 'moved_on', reason: 'its card asks another question now' } },
                { status: 409 },
            ),
        ]
        renderQuestion(QUESTION)
        fireEvent.click(screen.getByRole('button', { name: 'Answer A: keep both side by side' }))
        expect((await screen.findByRole('alert')).textContent).toContain('refused (moved_on)')
    })

    it('says on the one-line card that it asks you, until you answer', () => {
        const { rerender } = render(<RunCardNow card={{ ...CARD, question: QUESTION }} />)
        expect(screen.getByText('asks you')).toBeDefined()
        rerender(<RunCardNow card={{ ...CARD, question: { ...QUESTION, answer: 'A' } }} />)
        expect(screen.queryByText('asks you')).toBeNull()
    })
})
