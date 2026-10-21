import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { cleanup, fireEvent, render, screen, within } from '@testing-library/react'
import type { Middleware } from 'openapi-fetch'
import { afterEach, beforeEach, describe, expect, it } from 'vitest'

import { api } from '@/api/client'
import type { PersonaList, ReviewRequest } from '@/api/types'

import { ReviewRequestForm, ReviewRequestStatus } from './review-request'

const PR = 'https://github.com/acme/web/pull/88'
const OPEN: ReviewRequest = {
    channel: 'web',
    created_at: '2026-10-08T11:00:00Z',
    ended_at: null,
    end_reason: null,
    notes: null,
    personas: [],
}
const PERSONAS: PersonaList = {
    reviewer: 'canopy',
    personas: [
        { name: 'canopy', yours: false, defaults: ['worker', 'planner', 'reviewer'], error: null },
        { name: 'gone', yours: true, defaults: [], error: 'persona gone is past 4096 bytes' },
        { name: 'skeptic', yours: false, defaults: [], error: null },
    ],
}

// Every request sent, by its path and the PR it names, the bodies sent, and what the server stand-in answers each.
let sent: { path: string; url: string | null }[] = []
let bodies: unknown[] = []
let answer: Response | undefined

const server: Middleware = {
    async onRequest({ request }) {
        const url = new URL(request.url)
        // The personas the form's menu lists: a read, not one of the requests a test counts.
        if (url.pathname === '/api/personas') {
            return Response.json(PERSONAS)
        }
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

async function openPersonas(name = 'Persona: canopy (default)') {
    const trigger = await screen.findByRole<HTMLButtonElement>('button', { name })
    await expect.poll(() => trigger.disabled).toBe(false)
    fireEvent.pointerDown(trigger, { button: 0, ctrlKey: false })
    return screen.getByRole('menu')
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
        expect(bodies).toEqual([{ notes: '', personas: [] }])
        expect(field().value).toBe('')
    })

    it('requests a review of the PR a link into it names, such as a thread', async () => {
        renderWith(<ReviewRequestForm />)
        fireEvent.change(field(), { target: { value: `${PR}/files#r123` } })
        fireEvent.click(screen.getByRole('button', { name: 'Review' }))

        expect((await screen.findByRole('status')).textContent).toBe(
            `${PR} is requested for review. The next tick reviews its head, once.`,
        )
        expect(sent).toEqual([{ path: '/api/pull-request/start', url: PR }])
    })

    it('hands the reviewer the notes as written, trimmed, and clears them with the URL', async () => {
        renderWith(<ReviewRequestForm />)
        fireEvent.change(field(), { target: { value: PR } })
        fireEvent.change(notesField(), { target: { value: '  Look hard at the retry loop.\n' } })
        fireEvent.click(screen.getByRole('button', { name: 'Review' }))

        await screen.findByRole('status')
        expect(bodies).toEqual([{ notes: 'Look hard at the retry loop.', personas: [] }])
        expect(notesField().value).toBe('')
    })

    it('sends from the notes on the key Settings names, Shift+Enter making a new line', async () => {
        renderWith(<ReviewRequestForm />)
        const review = screen.getByRole('button', { name: 'Review' })
        expect(review.getAttribute('aria-keyshortcuts')).toBe('Enter')
        // With no URL there is nothing to review, so Enter sends nothing.
        fireEvent.change(notesField(), { target: { value: 'Look hard at the retry loop.' } })
        fireEvent.keyDown(notesField(), { key: 'Enter' })
        expect(sent).toEqual([])

        fireEvent.change(field(), { target: { value: PR } })
        fireEvent.keyDown(notesField(), { key: 'Enter', shiftKey: true })
        expect(sent).toEqual([])
        fireEvent.keyDown(notesField(), { key: 'Enter' })
        await screen.findByRole('status')
        expect(sent).toEqual([{ path: '/api/pull-request/start', url: PR }])
        expect(bodies).toEqual([{ notes: 'Look hard at the retry loop.', personas: [] }])
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

    it('reviews in each persona checked, says so as the CLI does, and goes back to the default', async () => {
        answer = Response.json({ already: false, request: { ...OPEN, personas: ['skeptic', 'canopy'] } })
        renderWith(<ReviewRequestForm />)
        fireEvent.change(field(), { target: { value: PR } })
        const menu = await openPersonas()
        const items = within(menu).getAllByRole('menuitemcheckbox')
        expect(items.map((item) => item.textContent)).toEqual(['canopy', 'gone', 'skeptic'])
        // One canopy would refuse to run cannot be chosen, and says why.
        const gone = within(menu).getByRole('menuitemcheckbox', { name: 'gone' })
        expect(gone.getAttribute('aria-disabled')).toBe('true')
        expect(gone.title).toBe('persona gone is past 4096 bytes')
        // The menu stays open, so several can be checked.
        fireEvent.click(within(menu).getByRole('menuitemcheckbox', { name: 'skeptic' }))
        fireEvent.click(within(menu).getByRole('menuitemcheckbox', { name: 'canopy' }))
        expect(within(menu).getByRole('menuitemcheckbox', { name: 'skeptic' }).getAttribute('aria-checked')).toBe(
            'true',
        )
        fireEvent.keyDown(menu, { key: 'Escape' })
        expect(screen.getByRole('button', { name: 'Persona: skeptic, canopy' }).title).toBe(
            'canopy start URL --review --persona NAME',
        )
        expect(screen.getByText('one review in each, side by side')).toBeTruthy()

        fireEvent.click(screen.getByRole('button', { name: 'Review' }))
        expect((await screen.findByRole('status')).textContent).toBe(
            `${PR} is requested for review. The next tick reviews its head, once. ` +
                'It is reviewed once in each of skeptic, canopy, side by side.',
        )
        expect(bodies).toEqual([{ notes: '', personas: ['skeptic', 'canopy'] }])
        // The next request starts from the default again.
        expect(screen.getByRole('button', { name: 'Persona: canopy (default)' })).toBeTruthy()
    })

    it('unchecks a persona, and Use the default clears them all', async () => {
        renderWith(<ReviewRequestForm />)
        let menu = await openPersonas()
        expect(within(menu).getByRole('menuitem', { name: 'Use the default' }).getAttribute('aria-disabled')).toBe(
            'true',
        )
        fireEvent.click(within(menu).getByRole('menuitemcheckbox', { name: 'skeptic' }))
        fireEvent.click(within(menu).getByRole('menuitemcheckbox', { name: 'canopy' }))
        fireEvent.click(within(menu).getByRole('menuitemcheckbox', { name: 'skeptic' }))
        fireEvent.keyDown(menu, { key: 'Escape' })
        menu = await openPersonas('Persona: canopy')
        fireEvent.click(within(menu).getByRole('menuitem', { name: 'Use the default' }))
        expect(await screen.findByRole('button', { name: 'Persona: canopy (default)' })).toBeTruthy()
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

    it('names the personas the request is reviewed in', () => {
        renderWith(<ReviewRequestStatus url={PR} request={{ ...OPEN, personas: ['skeptic'] }} />)
        expect(screen.getByTestId('review-request-personas').textContent).toBe('Its review is written in skeptic.')
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
