import { cleanup, fireEvent, screen, waitFor, within } from '@testing-library/react'
import type { Middleware } from 'openapi-fetch'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

import { api } from '@/api/client'
import { reviewDraft } from '@/api/mocks'
import type { DiffLine, ReviewDiff, ReviewDraft } from '@/api/types'
import { placeFindings } from '@/lib/reviews'
import { renderRouted } from '@/test-utils'

import { ReviewDiffPanels } from './review-diff'
import { DraftCommentCard, ReviewDraftPanel } from './review-draft'

const PR = 'https://github.com/acme/api/pull/14'
const SHA = `a61f7c08${'4'.repeat(32)}`

// Every request sent, by its method and path, with its body, and what the server stand-in answers each.
let sent: { method: string; path: string; body: unknown }[] = []
let answer: (path: string, body: unknown) => Response
// What the panel calls when a link to a comment's card is followed.
const followed = vi.fn<(file: number) => void>()

const server: Middleware = {
    async onRequest({ request }) {
        const url = new URL(request.url)
        const text = request.method === 'GET' ? '' : await request.text()
        const body: unknown = text ? JSON.parse(text) : null
        sent.push({ method: request.method, path: url.pathname, body })
        return answer(url.pathname, body)
    },
}

beforeEach(() => {
    sent = []
    answer = () => Response.json(reviewDraft({ version: 2, hash: 'aaaaaaaaaaaa', change: 'edited the body' }))
    api.use(server)
})

afterEach(() => {
    api.eject(server)
    cleanup()
})

function writes() {
    return sent.filter((s) => s.method === 'POST')
}

async function panel(draft: ReviewDraft = reviewDraft(), hasDiff = true) {
    await renderRouted(
        <ReviewDraftPanel run={5} prUrl={PR} sha={SHA} draft={draft} hasDiff={hasDiff} onFollow={followed} />,
    )
    return screen.getByTestId('review-draft')
}

describe('ReviewDraftPanel', () => {
    it('shows what would post word for word, its comments and versions, every hidden character named', async () => {
        const hidden = `Retry${String.fromCodePoint(8203)}s.`
        const found = await panel(reviewDraft({ body: hidden }))
        expect(within(found).getByText('waiting')).toBeTruthy()
        expect(within(found).getByText('version 1, 3f9a1c27b0de')).toBeTruthy()
        expect(within(found).getByText('<U+200B>')).toBeTruthy()
        const comments = within(found).getByTestId('draft-comments')
        expect(within(comments).getByText('1 of at most 30')).toBeTruthy()
        expect(within(comments).getByText('finding 1')).toBeTruthy()
        expect(within(comments).getByText('api/upstream.py:15')).toBeTruthy()
        expect(within(found).getByTestId('draft-versions').textContent).toContain(
            "1 3f9a1c27b0de by the reviewer: made from review run 5's summary and findings",
        )
    })

    it('stages the version shown by default, and submits it once ticked, as canopy review publish does', async () => {
        answer = () =>
            Response.json({ draft: reviewDraft({ status: 'staged' }), published: 1, failed: null }, { status: 200 })
        const found = await panel()
        const stage = within(found).getByRole('button', { name: 'Start the review on GitHub' })
        expect(stage.getAttribute('title')).toBe('canopy review publish 5 3f9a1c27b0de')
        fireEvent.click(stage)
        await waitFor(() => {
            expect(
                within(found).getByText(/^Staged version 1 of review run 5's draft in a pending review/u),
            ).toBeTruthy()
        })
        expect(writes()).toEqual([
            { method: 'POST', path: '/api/reviews/5/draft/publish', body: { hash: '3f9a1c27b0de', submit: false } },
        ])

        cleanup()
        sent = []
        answer = () =>
            Response.json({
                draft: reviewDraft({ status: 'published', published_url: `${PR}#pullrequestreview-9` }),
                published: 1,
                failed: null,
            })
        const again = await panel()
        fireEvent.click(within(again).getByRole('checkbox', { name: 'Submit it on GitHub now' }))
        fireEvent.click(within(again).getByRole('button', { name: 'Publish version 1' }))
        await waitFor(() => {
            expect(
                within(again).getByText(`Published version 1 of review run 5's draft: ${PR}#pullrequestreview-9`),
            ).toBeTruthy()
        })
        expect(writes()[0]?.body).toEqual({ hash: '3f9a1c27b0de', submit: true })
    })

    it('names the guard of a refused publish, as the CLI does', async () => {
        answer = () =>
            Response.json(
                { detail: { guard: 'stale', reason: "review run 5's draft is version 2 now" } },
                { status: 409 },
            )
        const found = await panel()
        fireEvent.click(within(found).getByRole('button', { name: 'Start the review on GitHub' }))
        expect(await within(found).findByText('refused (stale):')).toBeTruthy()
    })

    it('edits the body in the operator’s words, a new version', async () => {
        const found = await panel()
        fireEvent.click(within(found).getByRole('button', { name: 'edit' }))
        const form = within(found).getByRole('form', { name: "Edit review run 5's draft's body" })
        fireEvent.change(within(form).getByRole('textbox'), { target: { value: 'Mostly fine.' } })
        fireEvent.click(within(form).getByRole('button', { name: /Save/u }))
        await waitFor(() => {
            expect(
                within(found).getByText("Review run 5's draft is version 2 now, hash aaaaaaaaaaaa: edited the body."),
            ).toBeTruthy()
        })
        expect(writes()).toEqual([
            { method: 'POST', path: '/api/reviews/5/draft/body', body: { text: 'Mostly fine.' } },
        ])
    })

    it('offers nothing to change once published, and links to the review on GitHub', async () => {
        const url = `${PR}#pullrequestreview-9`
        const found = await panel(reviewDraft({ status: 'published', published_url: url }))
        expect(within(found).queryByRole('button', { name: 'edit' })).toBeNull()
        expect(within(found).queryByRole('button', { name: 'Start the review on GitHub' })).toBeNull()
        expect(within(found).getByRole('link', { name: 'on GitHub' }).getAttribute('href')).toBe(url)
    })

    it('says where to finish a staged review', async () => {
        const found = await panel(reviewDraft({ status: 'staged' }))
        expect(within(found).getByTestId('draft-staged').textContent).toContain('It waits in the review you staged.')
        expect(within(found).getByRole('link', { name: 'on GitHub' }).getAttribute('href')).toBe(`${PR}/files`)
    })
})

describe('DraftCommentCard', () => {
    it('edits and drops a comment, as canopy review edit does', async () => {
        const draft = reviewDraft()
        const [comment] = draft.comments
        if (comment === undefined) {
            throw new Error('the mock draft has a comment')
        }
        await renderRouted(<DraftCommentCard run={5} comment={comment} draft={draft} />)
        const card = screen.getByTestId('draft-comment')
        expect(within(card).getByText('from finding 1')).toBeTruthy()
        fireEvent.click(within(card).getByRole('button', { name: 'edit' }))
        fireEvent.change(within(card).getByRole('textbox'), { target: { value: 'Raise once it gives up.' } })
        fireEvent.click(within(card).getByRole('button', { name: /Save/u }))
        await waitFor(() => {
            expect(writes()).toHaveLength(1)
        })
        fireEvent.click(await within(card).findByRole('button', { name: 'drop' }))
        await waitFor(() => {
            expect(writes()).toHaveLength(2)
        })
        expect(writes()).toEqual([
            {
                method: 'POST',
                path: '/api/reviews/5/draft/comments/1/edit',
                body: { text: 'Raise once it gives up.' },
            },
            { method: 'POST', path: '/api/reviews/5/draft/comments/1/drop', body: null },
        ])
    })
})

describe('ReviewDiffPanels with a draft', () => {
    const lines = Array.from({ length: 15 }, (_, i): DiffLine => ({
        kind: 'add',
        old: null,
        new: i + 1,
        text: `l${i}`,
    }))
    const diff: ReviewDiff = {
        truncated: false,
        files: [{ path: 'api/upstream.py', old_path: null, binary: false, hunks: [{ header: '', lines }] }],
    }

    it('puts each comment on its line, and adds one on any line of the diff', async () => {
        await renderRouted(
            <ReviewDiffPanels run={5} diff={diff} placed={placeFindings([], true)} draft={reviewDraft()} />,
        )
        expect(screen.getByTestId('draft-comment').textContent).toContain('The last 503 is returned')
        fireEvent.click(screen.getByRole('button', { name: 'Comment on api/upstream.py:3' }))
        const form = screen.getByRole('form', { name: 'Comment on api/upstream.py:3' })
        fireEvent.change(within(form).getByRole('textbox'), { target: { value: 'Why random?' } })
        fireEvent.click(within(form).getByRole('button', { name: /Save/u }))
        await waitFor(() => {
            expect(screen.queryByTestId('new-draft-comment')).toBeNull()
        })
        expect(writes()).toEqual([
            {
                method: 'POST',
                path: '/api/reviews/5/draft/comments',
                body: { path: 'api/upstream.py', line: 3, text: 'Why random?' },
            },
        ])
    })

    it('offers no new comment once the draft is published', async () => {
        await renderRouted(
            <ReviewDiffPanels
                run={5}
                diff={diff}
                placed={placeFindings([], true)}
                draft={reviewDraft({ status: 'published' })}
            />,
        )
        expect(screen.queryByRole('button', { name: /^Comment on /u })).toBeNull()
        expect(screen.queryByRole('button', { name: 'edit' })).toBeNull()
    })
})
