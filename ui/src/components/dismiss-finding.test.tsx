import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { cleanup, fireEvent, render, screen, waitFor, within } from '@testing-library/react'
import type { Middleware } from 'openapi-fetch'
import { afterEach, beforeEach, describe, expect, it } from 'vitest'

import { api } from '@/api/client'
import { keys } from '@/api/queries'

import { dismissedLabel, useDismissFinding, useDismissReviewFinding } from './dismiss-finding'

// Every dismissal sent, and what the server stand-in answers it.
let sent: { path: string; body: unknown }[] = []
let answer: Response | undefined

const server: Middleware = {
    async onRequest({ request }) {
        const body = (await request.json()) as { finding: unknown; undo: boolean; reason?: string }
        sent.push({ path: new URL(request.url).pathname, body })
        if (answer !== undefined) {
            return answer
        }
        return request.url.includes('/chores/')
            ? Response.json({ chore: 'deps', finding: body.finding, dismissed: !body.undo })
            : Response.json({ run: 4, finding: body.finding, dismissed: !body.undo, reason: body.reason ?? null })
    },
}

beforeEach(() => {
    sent = []
    answer = undefined
    api.use(server)
})

afterEach(() => {
    api.eject(server)
    cleanup()
})

// The button and the notice, where a finding's row puts them.
function ChoreDismissal({ dismissed }: { dismissed: boolean }) {
    const { button, notice } = useDismissFinding('deps', 'lodash-advisory', dismissed)
    return (
        <>
            {button}
            {notice}
        </>
    )
}

function ReviewDismissal({ dismissed }: { dismissed: boolean }) {
    const { button, notice } = useDismissReviewFinding(4, 2, dismissed)
    return (
        <>
            {button}
            {notice}
        </>
    )
}

function renderWith(ui: React.JSX.Element, client = new QueryClient()) {
    return render(<QueryClientProvider client={client}>{ui}</QueryClientProvider>)
}

describe('useDismissFinding', () => {
    it("dismisses a chore's finding, says so as canopy dismiss does, and reads the attention list again", async () => {
        const client = new QueryClient()
        client.setQueryData(keys.chore('deps'), null)
        client.setQueryData(keys.attention, [])
        renderWith(<ChoreDismissal dismissed={false} />, client)
        const button = screen.getByRole('button', { name: 'dismiss' })
        expect(button.title).toBe('Keep it off the attention list until the chore stops reporting it')
        expect(screen.queryByRole('status')).toBeNull()

        fireEvent.click(button)
        expect((await screen.findByRole('status')).textContent).toBe(
            'chore:deps lodash-advisory is dismissed: it is off the attention list until the chore stops reporting it.',
        )
        expect(sent).toEqual([
            { path: '/api/chores/deps/dismissals', body: { finding: 'lodash-advisory', undo: false } },
        ])
        await waitFor(() => {
            expect(client.getQueryState(keys.chore('deps'))?.isInvalidated).toBe(true)
        })
        expect(client.getQueryState(keys.attention)?.isInvalidated).toBe(true)
    })

    it('undoes a dismissal, listing the finding again', async () => {
        renderWith(<ChoreDismissal dismissed />)
        const button = screen.getByRole('button', { name: 'undo' })
        expect(button.title).toBe('List it on the attention list again')

        fireEvent.click(button)
        expect((await screen.findByRole('status')).textContent).toBe(
            'chore:deps lodash-advisory is listed again while the chore reports it.',
        )
        expect(sent).toEqual([
            { path: '/api/chores/deps/dismissals', body: { finding: 'lodash-advisory', undo: true } },
        ])
    })

    it('names the guard that refused a dismissal', async () => {
        answer = Response.json(
            { detail: { guard: 'bad_ref', reason: 'no open finding lodash-advisory' } },
            { status: 409 },
        )
        renderWith(<ChoreDismissal dismissed={false} />)
        fireEvent.click(screen.getByRole('button', { name: 'dismiss' }))
        expect((await screen.findByRole('alert')).textContent).toBe(
            'refused (bad_ref): no open finding lodash-advisory',
        )
    })
})

describe('useDismissReviewFinding', () => {
    it("dismisses a review's finding by its number for the reason picked, and undoes it, as the CLI says", async () => {
        const { unmount } = renderWith(<ReviewDismissal dismissed={false} />)
        const dismiss = screen.getByRole('button', { name: 'dismiss' })
        expect(dismiss.title).toBe('Say why, and no worker or tick acts on it')
        // A click alone sends nothing: the dismissal waits on its reason.
        fireEvent.pointerDown(dismiss, { button: 0, ctrlKey: false })
        const reasons = within(screen.getByRole('menu')).getAllByRole('menuitem')
        expect(reasons.map((r) => r.textContent)).toEqual([
            'wrongIt does not hold: the reviewer misread the code',
            'intentionalIt holds, and the change means it to',
            'not worth itIt holds, and is not worth the fix',
        ])
        expect(sent).toEqual([])
        fireEvent.click(reasons[0] as HTMLElement)
        expect((await screen.findByRole('status')).textContent).toBe(
            'review:4 finding 2 is dismissed as wrong: no worker or tick acts on it.',
        )
        unmount()

        renderWith(<ReviewDismissal dismissed />)
        const undo = screen.getByRole('button', { name: 'undo' })
        expect(undo.title).toBe('Hand it to a resumed worker again')
        fireEvent.click(undo)
        expect((await screen.findByRole('status')).textContent).toBe(
            'review:4 finding 2 is no longer dismissed: a resume hands it to the worker again.',
        )
        expect(sent).toEqual([
            { path: '/api/reviews/4/dismissals', body: { finding: 2, undo: false, reason: 'wrong' } },
            { path: '/api/reviews/4/dismissals', body: { finding: 2, undo: true } },
        ])
    })
})

describe('dismissedLabel', () => {
    it('names why a finding was dismissed, when the operator said', () => {
        const finding = {
            severity: 'minor' as const,
            title: 't',
            location: '',
            detail: '',
            file: null,
            line: null,
            dismissed: true,
        }
        expect(dismissedLabel({ ...finding, dismissed_reason: 'not_worth_it' })).toBe('dismissed: not worth it')
        expect(dismissedLabel({ ...finding, dismissed_reason: null })).toBe('dismissed')
    })
})
