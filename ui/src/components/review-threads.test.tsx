import { cleanup, fireEvent, screen, within } from '@testing-library/react'
import type { Middleware } from 'openapi-fetch'
import type { ReactNode } from 'react'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

import { api } from '@/api/client'
import { draft, pullRequestThreads, reviewThread } from '@/api/mocks'
import { ToastContext } from '@/hooks/use-toast'
import type { NewToast } from '@/lib/toasts'
import { renderRouted } from '@/test-utils'

import { DraftCard, ReviewThreads, ThreadCard } from './review-threads'

const PR = 'https://github.com/acme/web/pull/88'

// Every request sent, by its method and path, with its body, and what the server stand-in answers each.
let sent: { method: string; path: string; body: unknown }[] = []
let answer: (path: string) => Response | Promise<Response>
// What the cards call once a verb is done, to read again what shows them.
const changed = vi.fn<() => void>()
// Every toast the cards showed.
let toasts: NewToast[] = []

const server: Middleware = {
    async onRequest({ request }) {
        const url = new URL(request.url)
        const text = request.method === 'GET' ? '' : await request.text()
        sent.push({ method: request.method, path: url.pathname, body: text ? JSON.parse(text) : null })
        return answer(url.pathname)
    },
}

beforeEach(() => {
    sent = []
    toasts = []
    changed.mockClear()
    answer = () => Response.json(pullRequestThreads())
    api.use(server)
})

afterEach(() => {
    api.eject(server)
    cleanup()
})

// The node, under a toast stand-in that keeps what each toast said.
function toasting(node: ReactNode) {
    return (
        <ToastContext
            value={(toast) => {
                toasts.push(toast)
            }}
        >
            {node}
        </ToastContext>
    )
}

function writes() {
    return sent.filter((s) => s.method === 'POST')
}

describe('ThreadCard', () => {
    it('shows where the thread is, its comments as text, and the drafts answering it', async () => {
        // A zero-width space, U+200B, written by its code point so the source shows it.
        const body = `Rename${String.fromCodePoint(8203)}this.`
        const [comment] = reviewThread().comments
        const hidden = reviewThread({
            outdated: true,
            resolved: true,
            comments: comment === undefined ? [] : [{ ...comment, body, operator_sent: true }],
        })
        await renderRouted(<ThreadCard thread={hidden} onChange={changed} />)
        const card = screen.getByTestId('review-thread')
        expect(within(card).getByText('src/search/useSearch.ts:16')).toBeTruthy()
        expect(within(card).getByText('outdated')).toBeTruthy()
        expect(within(card).getByText('resolved')).toBeTruthy()
        expect(within(card).getByText('sent by you')).toBeTruthy()
        // A hidden character is named, never kept hidden.
        expect(within(card).getByText('<U+200B>')).toBeTruthy()
        expect(within(card).getByRole('link', { name: 'The comment on its host' }).getAttribute('href')).toBe(
            `${PR}#discussion_r2468013579`,
        )
        expect(within(card).getByTestId('draft').dataset['status']).toBe('waiting')
    })

    it("shows a comment's and a draft's paragraphs as their lines, not as named characters", async () => {
        const [comment] = reviewThread().comments
        const thread = reviewThread({
            comments: comment === undefined ? [] : [{ ...comment, body: 'Rename this.\r\n\r\nIt reads better.' }],
            drafts: [draft({ text: 'Renamed.\n\nThanks.' })],
        })
        await renderRouted(<ThreadCard thread={thread} onChange={changed} />)
        const card = screen.getByTestId('review-thread')
        expect(within(card).getByTestId('thread-comment').textContent).toContain('Rename this.\n\nIt reads better.')
        expect(within(card).getByTestId('draft').textContent).toContain('Renamed.\n\nThanks.')
        expect(card.textContent).not.toContain('<U+')
    })
})

describe('DraftCard', () => {
    it('offers Send, Edit, and Drop on a waiting draft, with the CLI commands on hover', async () => {
        await renderRouted(<DraftCard draft={draft()} onChange={changed} />)
        expect(screen.getByRole<HTMLButtonElement>('button', { name: 'Send' }).title).toBe(
            'canopy draft send run:45 1@cb496d375e04',
        )
        expect(screen.getByRole<HTMLButtonElement>('button', { name: 'Edit' }).title).toBe(
            'canopy draft edit run:45 1 --text TEXT --react NAME',
        )
        expect(screen.getByRole<HTMLButtonElement>('button', { name: 'Drop' }).title).toBe('canopy draft drop run:45 1')
        expect(screen.getByText('changed')).toBeTruthy()
    })

    it('sends the draft named by the hash of the text shown, and says what the send did', async () => {
        let post: ((response: Response) => void) | undefined
        const posted = new Promise<Response>((resolve) => {
            post = resolve
        })
        answer = () => posted
        await renderRouted(toasting(<DraftCard draft={draft()} onChange={changed} />))
        fireEvent.click(screen.getByRole('button', { name: 'Send' }))
        // Until the post returns, the button says it is sending.
        const sending = await screen.findByRole<HTMLButtonElement>('button', { name: 'Sending…' })
        expect(sending.disabled).toBe(true)
        expect(toasts).toEqual([])
        post?.(
            Response.json({
                posted: [draft({ status: 'sent', sent_url: `${PR}#discussion_r9` })],
                already: [],
                failed: [],
                unconfirmed: [],
                staged: [],
            }),
        )
        expect((await screen.findByRole('status')).textContent).toBe(`Sent run 45's draft 1: ${PR}#discussion_r9.`)
        expect(toasts).toEqual([{ title: "Sent run 45's draft 1", detail: `${PR}#discussion_r9`, tone: 'done' }])
        expect(changed).toHaveBeenCalledOnce()
        expect(writes()).toEqual([
            {
                method: 'POST',
                path: '/api/drafts/send',
                body: { drafts: [{ run: 45, number: 1, hash: 'cb496d375e04' }] },
            },
        ])
    })

    it('names the guard of a refused send, as the CLI does', async () => {
        answer = () =>
            Response.json({ detail: { guard: 'stale', reason: "run 45's draft 1 changed since" } }, { status: 409 })
        await renderRouted(toasting(<DraftCard draft={draft()} onChange={changed} />))
        fireEvent.click(screen.getByRole('button', { name: 'Send' }))
        expect((await screen.findByRole('alert')).textContent).toBe("refused (stale): run 45's draft 1 changed since")
        // A refusal is the card's alone, never a toast.
        expect(toasts).toEqual([])
    })

    it("edits the text as plain text, within the bound, and saves it as the operator's", async () => {
        answer = () => Response.json(draft({ text: 'Mine.', edited: true, hash: 'aaaaaaaaaaaa' }))
        await renderRouted(<DraftCard draft={draft()} onChange={changed} />)
        fireEvent.click(screen.getByRole('button', { name: 'Edit' }))
        const field = screen.getByRole('textbox', { name: 'In your words' })
        const save = screen.getByRole<HTMLButtonElement>('button', { name: 'Save' })
        fireEvent.change(field, { target: { value: 'x'.repeat(4001) } })
        expect(save.disabled).toBe(true)
        expect(screen.getByText('4001 of 4000')).toBeTruthy()
        fireEvent.change(field, { target: { value: 'Mine.' } })
        fireEvent.click(save)
        expect((await screen.findByRole('status')).textContent).toBe(
            "Run 45's draft 1 is in your words now, hash aaaaaaaaaaaa.",
        )
        expect(writes()).toEqual([
            { method: 'POST', path: '/api/runs/45/drafts/1/edit', body: { text: 'Mine.', reaction: null } },
        ])
    })

    it('saves an edit on the key Settings names, as a reply does', async () => {
        answer = () => Response.json(draft({ text: 'Mine.', edited: true, hash: 'aaaaaaaaaaaa' }))
        await renderRouted(<DraftCard draft={draft()} onChange={changed} />)
        fireEvent.click(screen.getByRole('button', { name: 'Edit' }))
        expect(screen.getByRole('button', { name: 'Save' }).getAttribute('aria-keyshortcuts')).toBe('Enter')
        const field = screen.getByRole('textbox', { name: 'In your words' })
        fireEvent.change(field, { target: { value: 'Mine.' } })
        fireEvent.keyDown(field, { key: 'Enter', shiftKey: true })
        expect(writes()).toEqual([])
        fireEvent.keyDown(field, { key: 'Enter' })
        await screen.findByRole('status')
        expect(writes()).toEqual([
            { method: 'POST', path: '/api/runs/45/drafts/1/edit', body: { text: 'Mine.', reaction: null } },
        ])
    })

    it('shows the reaction a draft stages, beside its text or alone', async () => {
        await renderRouted(<DraftCard draft={draft({ reaction: 'rocket' })} onChange={changed} />)
        expect(screen.getByTestId('draft-reaction').textContent).toContain('Rocket on the comment it answers, with')
        expect(screen.getByText('Moved it into a `finally`.')).toBeTruthy()
        cleanup()
        await renderRouted(<DraftCard draft={draft({ text: '', reaction: '+1' })} onChange={changed} />)
        expect(screen.getByTestId('draft-reaction').textContent).toContain('Thumbs up on the comment it answers, alone')
        expect(screen.queryByTestId('draft-reacted')).toBeNull()
    })

    it('names a reaction an earlier send added though nothing else posted', async () => {
        await renderRouted(<DraftCard draft={draft({ reaction: '+1', reacted: '+1' })} onChange={changed} />)
        expect(screen.getByTestId('draft-reacted').textContent).toContain('Thumbs up is on the comment already')
        cleanup()
        await renderRouted(<DraftCard draft={draft({ status: 'sent', reacted: '+1' })} onChange={changed} />)
        expect(screen.queryByTestId('draft-reacted')).toBeNull()
    })

    it("picks a thread's reaction, or none, and saves a reaction alone with no text", async () => {
        answer = () => Response.json(draft({ text: '', reaction: 'heart', edited: true, hash: 'bbbbbbbbbbbb' }))
        await renderRouted(<DraftCard draft={draft()} onChange={changed} />)
        fireEvent.click(screen.getByRole('button', { name: 'Edit' }))
        const save = screen.getByRole<HTMLButtonElement>('button', { name: 'Save' })
        fireEvent.change(screen.getByRole('textbox', { name: 'In your words' }), { target: { value: '' } })
        expect(save.disabled).toBe(true)
        const group = screen.getByRole('radiogroup', { name: 'Reaction' })
        expect(
            within(group)
                .getAllByRole('radio')
                .map((r) => r.getAttribute('aria-label')),
        ).toEqual(['Thumbs up', 'Thumbs down', 'Laugh', 'Hooray', 'Confused', 'Heart', 'Rocket', 'Eyes'])
        fireEvent.click(within(group).getByRole('radio', { name: 'Heart' }))
        expect(save.disabled).toBe(false)
        fireEvent.click(save)
        expect((await screen.findByRole('status')).textContent).toBe(
            "Run 45's draft 1 is in your words now, hash bbbbbbbbbbbb.",
        )
        expect(writes()).toEqual([
            { method: 'POST', path: '/api/runs/45/drafts/1/edit', body: { text: '', reaction: 'heart' } },
        ])
    })

    it("offers no reaction on a draft for a PR's own comment", async () => {
        await renderRouted(
            <DraftCard draft={draft({ kind: 'pr', stance: null, comment_id: null })} onChange={changed} />,
        )
        expect(screen.getByRole<HTMLButtonElement>('button', { name: 'Edit' }).title).toBe(
            'canopy draft edit run:45 1 --text TEXT',
        )
        fireEvent.click(screen.getByRole('button', { name: 'Edit' }))
        expect(screen.queryByRole('radiogroup', { name: 'Reaction' })).toBeNull()
    })

    it('drops a draft, and takes a drop back', async () => {
        answer = () => Response.json(draft({ status: 'waiting' }))
        await renderRouted(<DraftCard draft={draft({ status: 'dropped' })} onChange={changed} />)
        expect(screen.queryByRole('button', { name: 'Send' })).toBeNull()
        fireEvent.click(screen.getByRole('button', { name: 'Undo' }))
        expect((await screen.findByRole('status')).textContent).toBe("Run 45's draft 1 is waiting.")
        expect(writes()).toEqual([{ method: 'POST', path: '/api/runs/45/drafts/1/drop', body: { undo: true } }])
    })

    it('offers nothing to send on a draft no read has checked, and warns of edits a newer draft dropped', async () => {
        await renderRouted(
            <DraftCard draft={draft({ status: 'unchecked', supersedes_edited: true })} onChange={changed} />,
        )
        expect(screen.queryByRole('button', { name: 'Send' })).toBeNull()
        expect(screen.getByRole('button', { name: 'Edit' })).toBeTruthy()
        expect(screen.getByText('It is sent once canopy has read its thread.')).toBeTruthy()
        expect(screen.getByTestId('supersedes-edited')).toBeTruthy()
    })

    it('says why a draft was refused, and offers no verb on it', async () => {
        await renderRouted(
            <DraftCard
                draft={draft({ status: 'refused', why: 'unknown_thread: no such comment' })}
                onChange={changed}
            />,
        )
        expect(screen.getByText('unknown_thread: no such comment')).toBeTruthy()
        expect(screen.queryAllByRole('button')).toEqual([])
    })
})

describe('ReviewThreads', () => {
    it('sends every waiting draft together, the review body first', async () => {
        const body = draft({ kind: 'pr', number: 2, stance: null, comment_id: null, hash: 'bbbbbbbbbbbb' })
        const threads = pullRequestThreads({ pr_drafts: [body] })
        const outcome = { posted: [draft({ status: 'sent' })], already: [], failed: [], unconfirmed: [], staged: [] }
        answer = (path) => Response.json(path === '/api/drafts/send' ? outcome : threads)
        await renderRouted(toasting(<ReviewThreads url={PR} />))
        fireEvent.click(await screen.findByRole('button', { name: 'Send 2 waiting' }))
        await screen.findByRole('status')
        expect(toasts).toEqual([{ title: "Sent run 45's draft 1", tone: 'done' }])
        expect(writes()).toEqual([
            {
                method: 'POST',
                path: '/api/drafts/send',
                body: {
                    drafts: [
                        { run: 45, number: 2, hash: 'bbbbbbbbbbbb' },
                        { run: 45, number: 1, hash: 'cb496d375e04' },
                    ],
                },
            },
        ])
        // With no diff kept, the threads are listed whole.
        expect(within(screen.getByTestId('threads-elsewhere')).getByText('Threads')).toBeTruthy()
    })

    it('stages every waiting draft in a review on GitHub, and says reactions go on their comments now', async () => {
        const body = draft({ kind: 'pr', number: 2, stance: null, comment_id: null, hash: 'bbbbbbbbbbbb' })
        const reacts = draft({ run: 46, text: '', reaction: '+1', hash: 'cccccccccccc' })
        const threads = pullRequestThreads({
            pr_drafts: [body],
            threads: [reviewThread({ drafts: [draft(), reacts] })],
        })
        const held = [draft({ status: 'staged' }), { ...body, status: 'staged' as const }]
        const staged = {
            posted: [{ ...reacts, status: 'sent' as const, reacted: '+1' as const }],
            already: [],
            failed: [],
            unconfirmed: [],
            staged: held,
        }
        answer = (path) => Response.json(path === '/api/drafts/stage' ? staged : threads)
        await renderRouted(toasting(<ReviewThreads url={PR} />))
        const start = await screen.findByRole<HTMLButtonElement>('button', { name: 'Start a review on GitHub' })
        expect(start.title).toBe('canopy draft stage run:45 2@bbbbbbbbbbbb 1@cb496d375e04 run:46 1@cccccccccccc')
        expect(screen.getByTestId('review-replies').textContent).toContain(
            "its reactions go on their comments now, since GitHub can't keep one pending.",
        )
        fireEvent.click(start)
        expect((await screen.findByRole('status')).textContent).toContain(
            "Run 46's draft 1 put thumbs up on its comment now, not in the review: GitHub can't keep a reaction " +
                'pending.',
        )
        expect(toasts).toEqual([
            {
                title: 'Staged 2 drafts in a review on GitHub, and added 1 reaction now',
                detail: `${PR}/files`,
                tone: 'done',
            },
        ])
        expect(writes()).toEqual([
            {
                method: 'POST',
                path: '/api/drafts/stage',
                body: {
                    drafts: [
                        { run: 45, number: 2, hash: 'bbbbbbbbbbbb' },
                        { run: 45, number: 1, hash: 'cb496d375e04' },
                        { run: 46, number: 1, hash: 'cccccccccccc' },
                    ],
                },
            },
        ])
    })

    it('offers no send while the PR holds a staged review, and says where to finish it', async () => {
        const body = draft({ kind: 'pr', number: 2, stance: null, comment_id: null, status: 'staged' })
        answer = () => Response.json(pullRequestThreads({ pr_drafts: [body] }))
        await renderRouted(<ReviewThreads url={PR} />)
        const held = await screen.findByTestId('staged-review')
        expect(held.textContent).toContain('1 draft waits in the review you staged.')
        expect(within(held).getByRole<HTMLAnchorElement>('link', { name: 'on GitHub' }).href).toBe(`${PR}/files`)
        expect(screen.queryByRole('button', { name: 'Send 1 waiting' })).toBeNull()
        expect(screen.queryByRole('button', { name: 'Start a review on GitHub' })).toBeNull()
        expect(screen.getAllByText('It is in the review you staged, for you to submit on GitHub.')).toHaveLength(1)
    })

    it('lists every draft with a link to its card, in the order the cards show', async () => {
        const body = draft({ kind: 'pr', number: 2, stance: null, comment_id: null, text: '\nThanks, all.\nMore.' })
        const loose = draft({ run: 46, number: 1, status: 'unchecked', text: 'On the cache.' })
        answer = () => Response.json(pullRequestThreads({ pr_drafts: [body], unplaced: [loose] }))
        await renderRouted(<ReviewThreads url={PR} />)
        const list = await screen.findByTestId('draft-list')
        const rows = within(list).getAllByRole('listitem')
        expect(rows.map((row) => row.textContent)).toEqual([
            "waitingrun:45 2Thanks, all.the review's body",
            'waitingrun:45 1Moved it into a `finally`.src/search/useSearch.ts:16',
            'uncheckedrun:46 1On the cache.not on a thread',
        ])
        for (const [name, anchor] of [
            ['Thanks, all.', 'draft-45-2'],
            ['Moved it into a `finally`.', 'draft-45-1'],
            ['On the cache.', 'draft-46-1'],
        ] as const) {
            const link = within(list).getByRole('link', { name })
            expect(link.getAttribute('href')).toMatch(new RegExp(`^/pull-requests/pr\\?url=.+#${anchor}$`, 'u'))
            expect(document.querySelector<HTMLElement>(`#${anchor}`)?.dataset['testid']).toBe('draft')
        }
    })

    it('names a reaction sent alone by its reaction in the list, so its link is never empty', async () => {
        const alone = draft({ run: 46, number: 1, status: 'unchecked', text: '', reaction: '+1' })
        answer = () => Response.json(pullRequestThreads({ unplaced: [alone] }))
        await renderRouted(<ReviewThreads url={PR} />)
        const list = await screen.findByTestId('draft-list')
        const link = within(list).getByRole('link', { name: 'Thumbs up, alone' })
        expect(link.getAttribute('href')).toMatch(/#draft-46-1$/u)
    })

    it("says when the PR's head is past the diff the page shows", async () => {
        answer = () =>
            Response.json(
                pullRequestThreads({ diff_run: 45, diff_head: 'aaaaaaa1', diff: { files: [], truncated: false } }),
            )
        await renderRouted(<ReviewThreads url={PR} />)
        expect((await screen.findByTestId('head-moved')).textContent).toContain('past the diff run:45 kept at aaaaaaa')
    })
})
