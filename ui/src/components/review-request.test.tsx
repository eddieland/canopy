import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { cleanup, fireEvent, render, screen } from '@testing-library/react'
import type { Middleware } from 'openapi-fetch'
import { afterEach, beforeEach, describe, expect, it } from 'vitest'

import { api } from '@/api/client'
import type { ReviewRequest } from '@/api/types'

import { ReviewRequestForm, ReviewRequestStatus } from './review-request'

const PR = 'https://github.com/acme/web/pull/88'
const OPEN: ReviewRequest = {
    channel: 'web',
    created_at: '2026-10-08T11:00:00Z',
    ended_at: null,
    end_reason: null,
    notes: null,
}

// Every request sent, by its path and the PR it names, the bodies sent, and what the server stand-in answers each.
let sent: { path: string; url: string | null }[] = []
let bodies: unknown[] = []
let answer: Response | undefined

const server: Middleware = {
    async onRequest({ request }) {
        const url = new URL(request.url)
        sent.push({ path: url.pathname, url: url.searchParams.get('url') })
        const body = await request.text()
        if (body !== '') {
            bodies.push(JSON.parse(body))
        }
        return answer ?? Response.json({ already: false, request: OPEN, running_review: null })
    },
}

beforeEach(() => {
    sent = []
    bodies = []
    answer = undefined
    api.use(server)
})

afterEach(() => {
    api.eject(server)
    cleanup()
})

function renderWith(ui: React.JSX.Element) {
    return render(<QueryClientProvider client={new QueryClient()}>{ui}</QueryClientProvider>)
}

function field(): HTMLInputElement {
    return screen.getByRole('textbox', { name: 'PR URL' })
}

function notesField(): HTMLTextAreaElement {
    return screen.getByRole('textbox', { name: 'Notes for the reviewer (optional)' })
}

describe('ReviewRequestForm', () => {
    it('asks for review only once a URL is written, by its button or by Enter', async () => {
        renderWith(<ReviewRequestForm />)
        const review = screen.getByRole<HTMLButtonElement>('button', { name: 'Review' })
        expect(review.title).toBe('canopy start URL --review')
        expect(review.disabled).toBe(true)
        fireEvent.change(field(), { target: { value: '   ' } })
        expect(review.disabled).toBe(true)
        // Enter in the field submits its form.
        fireEvent.submit(field())
        expect(sent).toEqual([])

        fireEvent.change(field(), { target: { value: PR } })
        expect(review.disabled).toBe(false)
        fireEvent.submit(field())
        await screen.findByRole('status')
        expect(sent).toEqual([{ path: '/api/pull-request/start', url: PR }])
    })

    it('requests a review of the PR as written, trimmed, says so as the CLI does, and clears the field', async () => {
        renderWith(<ReviewRequestForm />)
        fireEvent.change(field(), { target: { value: `  ${PR}  ` } })
        fireEvent.click(screen.getByRole('button', { name: 'Review' }))

        expect((await screen.findByRole('status')).textContent).toBe(
            `${PR} is requested for review. The next tick reviews its head, once.`,
        )
        expect(sent).toEqual([{ path: '/api/pull-request/start', url: PR }])
        expect(bodies).toEqual([{ notes: '' }])
        expect(field().value).toBe('')
    })

    it('hands the reviewer the notes as written, trimmed, and clears them with the URL', async () => {
        renderWith(<ReviewRequestForm />)
        fireEvent.change(field(), { target: { value: PR } })
        fireEvent.change(notesField(), { target: { value: '  Look hard at the retry loop.\n' } })
        fireEvent.click(screen.getByRole('button', { name: 'Review' }))

        await screen.findByRole('status')
        expect(bodies).toEqual([{ notes: 'Look hard at the retry loop.' }])
        expect(notesField().value).toBe('')
    })

    it("says the notes replaced the open request's own when the PR was already requested", async () => {
        answer = Response.json({ already: true, request: { ...OPEN, notes: 'Look again.' } })
        renderWith(<ReviewRequestForm />)
        fireEvent.change(field(), { target: { value: PR } })
        fireEvent.change(notesField(), { target: { value: 'Look again.' } })
        fireEvent.click(screen.getByRole('button', { name: 'Review' }))
        expect((await screen.findByRole('status')).textContent).toBe(
            `${PR} was already requested for review. Its notes are replaced.`,
        )
    })

    it('says so when the PR was already requested', async () => {
        answer = Response.json({ already: true, request: OPEN })
        renderWith(<ReviewRequestForm />)
        fireEvent.change(field(), { target: { value: PR } })
        fireEvent.click(screen.getByRole('button', { name: 'Review' }))
        expect((await screen.findByRole('status')).textContent).toBe(`${PR} was already requested for review.`)
    })

    it('names the guard that refused a request, and keeps the URL to fix', async () => {
        answer = Response.json(
            { detail: { guard: 'unknown_repo', reason: 'acme/web is in no repository' } },
            { status: 409 },
        )
        renderWith(<ReviewRequestForm />)
        fireEvent.change(field(), { target: { value: PR } })
        fireEvent.click(screen.getByRole('button', { name: 'Review' }))
        expect((await screen.findByRole('alert')).textContent).toBe(
            'refused (unknown_repo): acme/web is in no repository',
        )
        expect(field().value).toBe(PR)
    })
})

describe('ReviewRequestStatus', () => {
    it('shows nothing for a PR never asked to be reviewed', () => {
        const { container } = renderWith(<ReviewRequestStatus url={PR} request={null} />)
        expect(container.childElementCount).toBe(0)
    })

    it('stops an open request as canopy stop does, and says a review already running still finishes', async () => {
        answer = Response.json({ request: { ...OPEN, ended_at: '2026-10-08T12:00:00Z' }, running_review: 7 })
        const { container } = renderWith(<ReviewRequestStatus url={PR} request={OPEN} />)
        expect(container.textContent).toMatch(/^Requested \S+ ago \(web\)\. canopy reviews its head once/u)
        const stop = screen.getByRole('button', { name: 'Stop' })
        expect(stop.title).toBe(`canopy stop ${PR}`)

        fireEvent.click(stop)
        expect((await screen.findByRole('status')).textContent).toBe(
            `${PR}'s review request is stopped; nothing reviews it now. ` +
                'Review run 7 of it is still running and will finish.',
        )
        expect(sent).toEqual([{ path: '/api/pull-request/stop', url: PR }])
    })

    it('shows the notes the request gave its reviewer, line breaks kept', () => {
        renderWith(<ReviewRequestStatus url={PR} request={{ ...OPEN, notes: 'The retry loop.\nAnd its backoff.' }} />)
        const notes = screen.getByTestId('review-request-notes')
        expect(notes.textContent).toBe('Your notes for the reviewerThe retry loop.\nAnd its backoff.')
    })

    it('says how an ended request ended, with nothing left to stop', () => {
        const { container } = renderWith(
            <ReviewRequestStatus
                url={PR}
                request={{ ...OPEN, ended_at: '2026-10-08T12:00:00Z', end_reason: 'merged' }}
            />,
        )
        expect(container.textContent).toMatch(/^Your review request ended \S+ ago: merged\.$/u)
        expect(screen.queryByRole('button')).toBeNull()
    })
})
