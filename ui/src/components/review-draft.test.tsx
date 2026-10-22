import { cleanup, fireEvent, screen, waitFor, within } from '@testing-library/react'
import type { Middleware } from 'openapi-fetch'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

import { api } from '@/api/client'
import { reviewDraft } from '@/api/mocks'
import type { DiffLine, ReviewDiff, ReviewDraft } from '@/api/types'
import { ToastContext } from '@/hooks/use-toast'
import { placeFindings } from '@/lib/reviews'
import type { NewToast } from '@/lib/toasts'
import { renderRouted, tipOf } from '@/test-utils'

import { ReviewDiffPanels } from './review-diff'
import { DraftCommentCard, ReviewDraftPanel, ReviewDraftState } from './review-draft'

const PR = 'https://github.com/acme/api/pull/14'
const SHA = `a61f7c08${'4'.repeat(32)}`

// Every request sent, by its method and path, with its body, and what the server stand-in answers each.
let sent: { method: string; path: string; body: unknown }[] = []
let answer: (path: string, body: unknown) => Response
// What the panel calls when a link to a comment's card is followed.
const followed = vi.fn<(file: number) => void>()
// Every toast the panel showed.
let toasts: NewToast[] = []

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
    toasts = []
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
        <ToastContext
            value={(toast) => {
                toasts.push(toast)
            }}
        >
            <ReviewDraftPanel run={5} prUrl={PR} sha={SHA} draft={draft} hasDiff={hasDiff} onFollow={followed} />
        </ToastContext>,
    )
    return screen.getByTestId('review-draft')
}

describe('ReviewDraftPanel', () => {
    it('shows what would post word for word, its comments and versions, every hidden character named', async () => {
        const hidden = `Retry${String.fromCodePoint(8203)}s.`
        const found = await panel(reviewDraft({ body: hidden }))
        // The page's description says its status; what made the version, and its hash, are on the version's hover.
        expect(within(found).queryByText('waiting')).toBeNull()
        expect(within(found).queryByText(/3f9a1c27b0de/u, { selector: 'p' })).toBeNull()
        expect(tipOf(within(found).getByTestId('draft-version'))).toBe(
            "Version 1: made from review run 5's summary and findings, by the reviewer. " +
                'A publish carries its hash, 3f9a1c27b0de.',
        )
        expect(within(found).getByText('<U+200B>')).toBeTruthy()
        const comments = within(found).getByTestId('draft-comments')
        expect(within(comments).getByText('1 of at most 30')).toBeTruthy()
        expect(within(comments).getByText('finding 1')).toBeTruthy()
        expect(within(comments).getByText('api/upstream.py:15')).toBeTruthy()
        expect(within(found).getByTestId('draft-versions').textContent).toContain(
            "1 3f9a1c27b0de by the reviewer: made from review run 5's summary and findings",
        )
    })

    it('says what would post, as whom, on whose PR, and on which commit', async () => {
        const found = await panel()
        expect(within(found).getByTestId('draft-posts').textContent).toBe(
            "Publish posts the body and 1 comment as your comment review, unmarked, on carol's PR, at a61f7c0: it " +
                'approves nothing. A review started on GitHub holds the same, seen by you alone until you submit it ' +
                'there.',
        )
        cleanup()
        const unread = await panel(reviewDraft({ body: '', pr_author: null }))
        expect(within(unread).getByTestId('draft-posts').textContent).toMatch(
            /^Publish posts 1 comment, no body, as your comment review, unmarked, on the PR, at a61f7c0:/u,
        )
    })

    it('publishes the version shown, or starts the review on GitHub, as canopy review publish does', async () => {
        const url = `${PR}#pullrequestreview-9`
        answer = () =>
            Response.json({
                draft: reviewDraft({ status: 'published', published_url: url }),
                published: 1,
                failed: null,
            })
        const found = await panel()
        const publish = within(found).getByRole('button', { name: 'Publish version 1' })
        expect(publish.getAttribute('title')).toBe('canopy review publish 5 3f9a1c27b0de --submit')
        fireEvent.click(publish)
        await waitFor(() => {
            expect(toasts).toEqual([
                { title: "Published version 1 of review run 5's draft", detail: url, tone: 'done' },
            ])
        })
        expect(writes()).toEqual([
            { method: 'POST', path: '/api/reviews/5/draft/publish', body: { hash: '3f9a1c27b0de', submit: true } },
        ])
        // The draft's own linked line says it once the draft shows published; the raw URL is the toast's alone.
        expect(within(found).queryByRole('status')).toBeNull()
        // Posting it drops a leaf, as approving a plan does.
        expect(within(found).getByTestId('leaf')).toBeTruthy()

        cleanup()
        sent = []
        toasts = []
        answer = () => Response.json({ draft: reviewDraft({ status: 'staged' }), published: 1, failed: null })
        const again = await panel()
        const stage = within(again).getByRole('button', { name: 'Start the review on GitHub' })
        expect(stage.getAttribute('title')).toBe('canopy review publish 5 3f9a1c27b0de')
        fireEvent.click(stage)
        await waitFor(() => {
            expect(toasts).toEqual([
                {
                    title: "Staged version 1 of review run 5's draft in a review on GitHub",
                    detail: `${PR}/files`,
                    tone: 'done',
                },
            ])
        })
        expect(writes()[0]?.body).toEqual({ hash: '3f9a1c27b0de', submit: false })
        // Staging posts nothing anyone sees yet, so it drops no leaf.
        expect(within(again).queryByTestId('leaf')).toBeNull()
    })

    it('says why a publish posted nothing, with a cross', async () => {
        answer = () =>
            Response.json({ draft: reviewDraft({ status: 'waiting' }), published: 1, failed: 'the post failed: 502' })
        const found = await panel()
        fireEvent.click(within(found).getByRole('button', { name: 'Publish version 1' }))
        expect(
            await within(found).findByText("Version 1 of review run 5's draft was not published: the post failed: 502"),
        ).toBeTruthy()
        expect(toasts).toEqual([{ title: "Version 1 of review run 5's draft was not published", tone: 'failed' }])
        expect(within(found).queryByTestId('leaf')).toBeNull()
    })

    it('offers nothing to publish while the draft is empty', async () => {
        const found = await panel(reviewDraft({ body: '', comments: [] }))
        expect(within(found).getByRole('button', { name: 'Publish version 1' }).hasAttribute('disabled')).toBe(true)
        expect(within(found).getByTestId('draft-posts').textContent).toBe(
            'Nothing to post yet: it needs a body or a comment.',
        )
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
        expect(within(found).queryByRole('button', { name: /^edit$/iu })).toBeNull()
        expect(within(found).queryByRole('button', { name: 'Start the review on GitHub' })).toBeNull()
        expect(within(found).getByTestId('draft-published').textContent).toContain('Published version 1 as your review')
        expect(within(found).getByRole('link', { name: 'on GitHub' }).getAttribute('href')).toBe(url)
        // Published before the page opened: nothing was just done here, so no leaf.
        expect(within(found).queryByTestId('leaf')).toBeNull()
    })

    it('says where to finish a staged review', async () => {
        const found = await panel(reviewDraft({ status: 'staged' }))
        expect(within(found).getByTestId('draft-staged').textContent).toContain(
            'Version 1 waits in the review you staged.',
        )
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
        fireEvent.click(within(card).getByRole('button', { name: 'Edit' }))
        fireEvent.change(within(card).getByRole('textbox'), { target: { value: 'Raise once it gives up.' } })
        fireEvent.click(within(card).getByRole('button', { name: /Save/u }))
        await waitFor(() => {
            expect(writes()).toHaveLength(1)
        })
        fireEvent.click(await within(card).findByRole('button', { name: 'Drop' }))
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
        expect(screen.queryByRole('button', { name: /^edit$/iu })).toBeNull()
    })
})

describe('ReviewDraftState', () => {
    it("says the draft's status, its version, and what the status means, for the page's description", async () => {
        await renderRouted(<ReviewDraftState draft={reviewDraft({ status: 'staged', version: 3 })} />)
        const state = screen.getByTestId('draft-state')
        expect(within(state).getByText('staged')).toBeTruthy()
        expect(state.textContent).toBe('stagedversion 3 · pending on GitHub, for you to submit there')
    })
})
