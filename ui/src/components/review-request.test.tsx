import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { cleanup, fireEvent, render, screen, waitFor, within } from '@testing-library/react'
import type { Middleware } from 'openapi-fetch'
import { afterEach, beforeEach, describe, expect, it } from 'vitest'

import { api } from '@/api/client'
import type { PersonaList, ReviewRequest } from '@/api/types'
import { setReviewPersonas } from '@/lib/review-personas'
import { renderRouted } from '@/test-utils'

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
const ENDED: ReviewRequest = { ...OPEN, ended_at: '2026-10-08T12:00:00Z', end_reason: 'merged' }
const SKEPTIC = 'When you review, name the input that breaks a claim before you accept it.'
const PERSONAS: PersonaList = {
    reviewer: 'canopy',
    personas: [
        {
            name: 'canopy',
            yours: false,
            defaults: ['worker', 'planner', 'reviewer'],
            error: null,
            description: 'When you plan, be as long as the work needs and no longer.',
        },
        { name: 'gone', yours: true, defaults: [], error: 'persona gone is past 4096 bytes', description: null },
        { name: 'skeptic', yours: false, defaults: [], error: null, description: SKEPTIC },
    ],
}

// Every request sent, by its path and the PR it names, the bodies sent, and what the server stand-in answers each.
let sent: { path: string; url: string | null }[] = []
let bodies: unknown[] = []
let answer: Response | undefined
// The personas the server stand-in lists.
let listed: PersonaList = PERSONAS

const server: Middleware = {
    async onRequest({ request }) {
        const url = new URL(request.url)
        // The personas the menus list: a read, not one of the requests a test counts.
        if (url.pathname === '/api/personas') {
            return Response.json(listed)
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
    listed = PERSONAS
    setReviewPersonas([])
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

// Opens what the form keeps folded: its personas and its notes.
function showMore() {
    fireEvent.click(screen.getByRole('button', { name: 'Show persona and notes' }))
}

async function openPersonas(name = 'Persona: canopy (default)') {
    const trigger = await screen.findByRole<HTMLButtonElement>('button', { name })
    await expect.poll(() => trigger.disabled).toBe(false)
    fireEvent.pointerDown(trigger, { button: 0, ctrlKey: false })
    return screen.getByRole('menu')
}

describe('ReviewRequestForm', () => {
    it('is a URL and an outline Review, saying its review is a draft, its persona and notes folded', async () => {
        await renderRouted(<ReviewRequestForm />)
        expect(screen.getByRole('status').textContent).toBe(
            "For a PR the loop does not own, such as a coworker's. " +
                'Its review is a draft you may publish, word for word, as your own; nothing posts until you do.',
        )
        expect(screen.queryByRole('textbox', { name: 'Notes for the reviewer (optional)' })).toBeNull()
        expect(screen.getByRole('button', { name: 'Review' }).getAttribute('aria-keyshortcuts')).toBeNull()
        // Closed, it names what the review is written in.
        expect(await screen.findByText('in canopy, the default')).toBeTruthy()
        showMore()
        expect(notesField()).toBeTruthy()
        expect(screen.getByRole('button', { name: 'Persona: canopy (default)' })).toBeTruthy()
    })

    it('asks for review only once a URL is written, by its button or by Enter', async () => {
        await renderRouted(<ReviewRequestForm />)
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
        await waitFor(() => {
            expect(sent).toEqual([{ path: '/api/pull-request/start', url: PR }])
        })
    })

    it("requests a review of the PR as written, trimmed, then opens the PR's page", async () => {
        const { router } = await renderRouted(<ReviewRequestForm />, { at: '/reviews' })
        fireEvent.change(field(), { target: { value: `  ${PR}  ` } })
        fireEvent.click(screen.getByRole('button', { name: 'Review' }))

        await waitFor(() => {
            expect(router.state.location.pathname).toBe('/pull-requests/pr')
        })
        expect(router.state.location.search).toEqual({ url: PR })
        expect(sent).toEqual([{ path: '/api/pull-request/start', url: PR }])
        expect(bodies).toEqual([{ notes: '', personas: [] }])
    })

    it('requests a review of the PR a link into it names, such as a thread', async () => {
        const { router } = await renderRouted(<ReviewRequestForm />, { at: '/reviews' })
        fireEvent.change(field(), { target: { value: `${PR}/files#r123` } })
        fireEvent.click(screen.getByRole('button', { name: 'Review' }))
        await waitFor(() => {
            expect(router.state.location.search).toEqual({ url: PR })
        })
        expect(sent).toEqual([{ path: '/api/pull-request/start', url: PR }])
    })

    it('hands the reviewer the notes as written, trimmed', async () => {
        await renderRouted(<ReviewRequestForm />)
        fireEvent.change(field(), { target: { value: PR } })
        showMore()
        fireEvent.change(notesField(), { target: { value: '  Look hard at the retry loop.\n' } })
        fireEvent.click(screen.getByRole('button', { name: /^Review/u }))
        await waitFor(() => {
            expect(bodies).toEqual([{ notes: 'Look hard at the retry loop.', personas: [] }])
        })
    })

    it('sends from the notes on the key Settings names, Shift+Enter making a new line', async () => {
        await renderRouted(<ReviewRequestForm />)
        showMore()
        const review = screen.getByRole('button', { name: /^Review/u })
        expect(review.getAttribute('aria-keyshortcuts')).toBe('Enter')
        // With no URL there is nothing to review, so Enter sends nothing.
        fireEvent.change(notesField(), { target: { value: 'Look hard at the retry loop.' } })
        fireEvent.keyDown(notesField(), { key: 'Enter' })
        expect(sent).toEqual([])

        fireEvent.change(field(), { target: { value: PR } })
        fireEvent.keyDown(notesField(), { key: 'Enter', shiftKey: true })
        expect(sent).toEqual([])
        fireEvent.keyDown(notesField(), { key: 'Enter' })
        await waitFor(() => {
            expect(sent).toEqual([{ path: '/api/pull-request/start', url: PR }])
        })
        expect(bodies).toEqual([{ notes: 'Look hard at the retry loop.', personas: [] }])
    })

    it('reviews in each persona checked, each described, and Use the default goes back', async () => {
        await renderRouted(<ReviewRequestForm />)
        fireEvent.change(field(), { target: { value: PR } })
        showMore()
        const menu = await openPersonas()
        const items = within(menu).getAllByRole('menuitemcheckbox')
        expect(items).toEqual(
            ['canopy', 'gone', 'skeptic'].map((name) => within(menu).getByRole('menuitemcheckbox', { name })),
        )
        // Each says what it is under its name, apart from its name.
        expect(within(menu).getByRole('menuitemcheckbox', { name: 'skeptic', description: SKEPTIC })).toBe(items[2])
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

        fireEvent.click(screen.getByRole('button', { name: /^Review/u }))
        await waitFor(() => {
            expect(bodies).toEqual([{ notes: '', personas: ['skeptic', 'canopy'] }])
        })
    })

    it('unchecks a persona, and Use the default clears them all', async () => {
        await renderRouted(<ReviewRequestForm />)
        showMore()
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

    it('starts from the personas Settings prefers, and says so while folded', async () => {
        setReviewPersonas(['skeptic', 'canopy'])
        await renderRouted(<ReviewRequestForm />)
        expect(await screen.findByText('in skeptic, canopy, as Settings prefers')).toBeTruthy()
        showMore()
        expect(await screen.findByRole('button', { name: 'Persona: skeptic, canopy' })).toBeTruthy()
        expect(screen.getByText('as Settings prefers')).toBeTruthy()

        // Picked for this request alone: Settings keeps its choice.
        fireEvent.change(field(), { target: { value: PR } })
        const menu = await openPersonas('Persona: skeptic, canopy')
        fireEvent.click(within(menu).getByRole('menuitemcheckbox', { name: 'canopy' }))
        fireEvent.keyDown(menu, { key: 'Escape' })
        expect(screen.getByRole('button', { name: 'Persona: skeptic' })).toBeTruthy()
        expect(screen.queryByText('as Settings prefers')).toBeNull()

        fireEvent.click(screen.getByRole('button', { name: /^Review/u }))
        await waitFor(() => {
            expect(bodies).toEqual([{ notes: '', personas: ['skeptic'] }])
        })
    })

    it("leaves out a preferred persona canopy would not run, and Use the default goes to the config's", async () => {
        setReviewPersonas(['gone', 'removed', 'skeptic'])
        await renderRouted(<ReviewRequestForm />)
        fireEvent.change(field(), { target: { value: PR } })
        showMore()
        const menu = await openPersonas('Persona: skeptic')
        fireEvent.click(within(menu).getByRole('menuitem', { name: 'Use the default' }))
        fireEvent.click(await screen.findByRole('button', { name: /^Review/u }))
        await waitFor(() => {
            expect(bodies).toEqual([{ notes: '', personas: [] }])
        })
    })

    it('checks no more personas than one request may name', async () => {
        const names = Array.from({ length: 11 }, (_, i) => `p${String(i).padStart(2, '0')}`)
        listed = {
            reviewer: 'canopy',
            personas: names.map((name) => ({ name, yours: true, defaults: [], error: null, description: null })),
        }
        await renderRouted(<ReviewRequestForm />)
        showMore()
        const menu = await openPersonas()
        for (const name of names.slice(0, 10)) {
            fireEvent.click(within(menu).getByRole('menuitemcheckbox', { name }))
        }
        expect(within(menu).getByRole('menuitemcheckbox', { name: 'p10' }).getAttribute('aria-disabled')).toBe('true')
        // One checked may still be unchecked.
        expect(within(menu).getByRole('menuitemcheckbox', { name: 'p09' }).getAttribute('aria-disabled')).toBeNull()
    })

    it('names the guard that refused a request in place of the hint, keeps the URL, and stays', async () => {
        answer = Response.json(
            { detail: { guard: 'unknown_repo', reason: 'acme/web is in no repository' } },
            { status: 409 },
        )
        const { router } = await renderRouted(<ReviewRequestForm />, { at: '/reviews' })
        fireEvent.change(field(), { target: { value: PR } })
        fireEvent.click(screen.getByRole('button', { name: 'Review' }))
        expect((await screen.findByRole('alert')).textContent).toBe(
            'refused (unknown_repo): acme/web is in no repository',
        )
        expect(screen.queryByRole('status')).toBeNull()
        expect(field().value).toBe(PR)
        expect(router.state.location.pathname).toBe('/reviews')
    })
})

describe('ReviewRequestStatus', () => {
    it("shows nothing for one of the loop's own PRs never asked to be reviewed", () => {
        const { container } = renderWith(<ReviewRequestStatus url={PR} request={null} loopPr reviewed={false} />)
        expect(container.childElementCount).toBe(0)
    })

    it('asks for a review of a PR never requested, in the personas Settings prefers, as the CLI does', async () => {
        setReviewPersonas(['skeptic'])
        answer = Response.json({ already: false, request: { ...OPEN, personas: ['skeptic'] } })
        renderWith(<ReviewRequestStatus url={PR} request={null} loopPr={false} reviewed={false} />)
        expect(screen.getByTestId('review-request').textContent).toContain('nothing posts until you do')
        const ask = screen.getByRole('button', { name: 'Review this PR' })
        expect(ask.title).toBe(`canopy start ${PR} --review`)
        expect(await screen.findByRole('button', { name: 'Persona: skeptic' })).toBeTruthy()

        fireEvent.click(ask)
        expect((await screen.findByRole('status')).textContent).toBe(
            `${PR} is requested for review. The next tick reviews its head, once. Its review is written in skeptic.`,
        )
        expect(sent).toEqual([{ path: '/api/pull-request/start', url: PR }])
        expect(bodies).toEqual([{ notes: '', personas: ['skeptic'] }])
    })

    it('asks again once canopy has reviewed it, though nobody requested it', () => {
        renderWith(<ReviewRequestStatus url={PR} request={null} loopPr={false} reviewed />)
        expect(screen.getByRole('button', { name: 'Review again' })).toBeTruthy()
    })

    it('asks again after a request ended, in its personas, which the menu changes', async () => {
        setReviewPersonas(['canopy'])
        renderWith(
            <ReviewRequestStatus url={PR} request={{ ...ENDED, personas: ['skeptic'] }} loopPr={false} reviewed />,
        )
        expect(screen.getByTestId('review-request').textContent).toMatch(
            /^Your review request ended \S+ ago: merged\./u,
        )
        const menu = await openPersonas('Persona: skeptic')
        fireEvent.click(within(menu).getByRole('menuitemcheckbox', { name: 'canopy' }))
        fireEvent.keyDown(menu, { key: 'Escape' })
        fireEvent.click(screen.getByRole('button', { name: 'Review again' }))
        await screen.findByRole('status')
        expect(bodies).toEqual([{ notes: '', personas: ['skeptic', 'canopy'] }])
    })

    it('says so when the PR was already requested', async () => {
        answer = Response.json({ already: true, request: OPEN })
        renderWith(<ReviewRequestStatus url={PR} request={ENDED} loopPr={false} reviewed />)
        fireEvent.click(screen.getByRole('button', { name: 'Review again' }))
        expect((await screen.findByRole('status')).textContent).toBe(`${PR} was already requested for review.`)
    })

    it('names the guard that refused it, as the CLI does', async () => {
        answer = Response.json(
            { detail: { guard: 'reviews_off', reason: 'capacity.max_reviews is 0, so no review can run' } },
            { status: 409 },
        )
        renderWith(<ReviewRequestStatus url={PR} request={null} loopPr={false} reviewed={false} />)
        fireEvent.click(screen.getByRole('button', { name: 'Review this PR' }))
        expect((await screen.findByRole('alert')).textContent).toBe(
            'refused (reviews_off): capacity.max_reviews is 0, so no review can run',
        )
    })

    it('stops an open request as canopy stop does, and says a review already running still finishes', async () => {
        answer = Response.json({ request: ENDED, running_review: 7 })
        const { container } = renderWith(<ReviewRequestStatus url={PR} request={OPEN} loopPr={false} reviewed />)
        expect(container.textContent).toMatch(/^Requested \S+ ago \(web\)\. canopy reviews its head once/u)
        // While one is open there is nothing to ask for.
        expect(screen.queryByRole('button', { name: /^Review/u })).toBeNull()
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
        renderWith(
            <ReviewRequestStatus
                url={PR}
                request={{ ...OPEN, notes: 'The retry loop.\nAnd its backoff.' }}
                loopPr={false}
                reviewed={false}
            />,
        )
        const notes = screen.getByTestId('review-request-notes')
        expect(notes.textContent).toBe('Your notes for the reviewerThe retry loop.\nAnd its backoff.')
    })

    it('names the personas the request is reviewed in', () => {
        renderWith(
            <ReviewRequestStatus url={PR} request={{ ...OPEN, personas: ['skeptic'] }} loopPr={false} reviewed />,
        )
        expect(screen.getByTestId('review-request-personas').textContent).toBe('Its review is written in skeptic.')
    })

    it('says a request in several personas ends once each has reviewed', () => {
        const { container } = renderWith(
            <ReviewRequestStatus
                url={PR}
                request={{ ...OPEN, personas: ['skeptic', 'canopy'] }}
                loopPr={false}
                reviewed={false}
            />,
        )
        expect(container.textContent).toContain(
            'canopy reviews its head once in each persona, in the repository it is in, ' +
                'and the request ends once each has.',
        )
    })

    it("says how an ended request on one of the loop's own PRs ended, with nothing to stop or ask", () => {
        const { container } = renderWith(<ReviewRequestStatus url={PR} request={ENDED} loopPr reviewed />)
        expect(container.textContent).toMatch(/^Your review request ended \S+ ago: merged\.$/u)
        expect(screen.queryByRole('button')).toBeNull()
    })
})
