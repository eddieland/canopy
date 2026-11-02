import { cleanup, fireEvent, render, screen, within } from '@testing-library/react'
import type { ComponentProps } from 'react'
import { afterEach, describe, expect, it, vi } from 'vitest'

import { COMMENT_LABELS } from '@/lib/plan-comment-labels'
import { changeRequest } from '@/lib/plan-threads'
import type { PlanThread } from '@/lib/plan-threads'

import { AskForChanges, PlanThreads, ThreadCard } from './plan-threads'
import type { ThreadActions } from './plan-threads'

afterEach(() => {
    cleanup()
})

const AT = '2026-10-08T11:00:00Z'

function thread(id: string, quote: string, fields: Partial<PlanThread> = {}): PlanThread {
    return {
        id,
        anchor: { quote, prefix: '', suffix: '' },
        body: `About ${quote}.`,
        at: AT,
        resolved: false,
        replies: [],
        ...fields,
    }
}

// What the operator did, each action a spy.
function actions() {
    return {
        onActivate: vi.fn<ThreadActions['onActivate']>(),
        onOpen: vi.fn<ThreadActions['onOpen']>(),
        onReply: vi.fn<ThreadActions['onReply']>(),
        onResolve: vi.fn<ThreadActions['onResolve']>(),
        onDelete: vi.fn<ThreadActions['onDelete']>(),
        onEdit: vi.fn<ThreadActions['onEdit']>(),
        onBack: vi.fn<ThreadActions['onBack']>(),
    }
}

type ListProps = ComponentProps<typeof PlanThreads>

function renderList(props: Partial<ListProps>) {
    const all: ListProps = {
        ...actions(),
        threads: [],
        found: new Set<string>(),
        active: undefined,
        draft: undefined,
        draftAt: 0,
        editable: true,
        onDraftChange: vi.fn<ListProps['onDraftChange']>(),
        onDraftSubmit: vi.fn<ListProps['onDraftSubmit']>(),
        onDraftCancel: vi.fn<ListProps['onDraftCancel']>(),
        onDraftLeave: vi.fn<ListProps['onDraftLeave']>(),
        onResolveGone: vi.fn<ListProps['onResolveGone']>(),
        ...props,
    }
    render(<PlanThreads {...all} />)
    return all
}

function renderCard(card: Partial<ComponentProps<typeof ThreadCard>> = {}) {
    const did = actions()
    render(<ThreadCard thread={thread('t1', 'the cache')} lost={false} active editable {...did} {...card} />)
    return did
}

function cards(): string[] {
    return screen.queryAllByRole('article').map((article) => article.getAttribute('aria-label') ?? '')
}

function field(name: string): HTMLTextAreaElement {
    return screen.getByRole<HTMLTextAreaElement>('textbox', { name })
}

describe('PlanThreads', () => {
    it('lists the open threads in the plan’s order with the comment being written in its place, then the lost', () => {
        const threads = [
            thread('a', 'the cache'),
            thread('b', 'the queue'),
            thread('gone', 'an old step'),
            thread('done', 'the schema', { resolved: true }),
        ]
        renderList({
            threads,
            found: new Set(['a', 'b', 'done']),
            draft: { quote: 'the retry', body: '', opened: 1 },
            draftAt: 1,
        })
        expect(cards()).toEqual(['Comment on “the cache”', 'Comment on “the queue”', 'Comment on “an old step”'])
        const draft = screen.getByRole('form', { name: 'Comment' })
        const [first, second] = screen.getAllByRole('article') as [HTMLElement, HTMLElement]
        expect(first.compareDocumentPosition(draft) & Node.DOCUMENT_POSITION_FOLLOWING).toBeTruthy()
        expect(draft.compareDocumentPosition(second) & Node.DOCUMENT_POSITION_FOLLOWING).toBeTruthy()
        expect(
            within(screen.getByRole('article', { name: 'Comment on “an old step”' })).getByText('passage gone'),
        ).toBeDefined()

        // The resolved ones are folded until asked for.
        fireEvent.click(screen.getByRole('button', { name: 'Show 1 resolved' }))
        expect(
            within(screen.getByRole('article', { name: 'Comment on “the schema”' })).getByText('resolved'),
        ).toBeDefined()
    })

    it('says there are no open comments, and how to add one when the operator can', () => {
        renderList({ threads: [thread('done', 'the schema', { resolved: true })], found: new Set(['done']) })
        expect(screen.getByText('no open comments yet: select text in the plan, then Comment')).toBeDefined()
        cleanup()
        renderList({ editable: false })
        expect(screen.getByText('no open comments now')).toBeDefined()
    })

    it('resolves together the threads whose passages a new plan took away, when there are more than one', () => {
        const lost = [thread('x', 'step one'), thread('y', 'step two')]
        const props = renderList({ threads: lost })
        expect(screen.getByText('2 on passages gone from the plan')).toBeDefined()
        fireEvent.click(screen.getByRole('button', { name: 'resolve all 2' }))
        expect(props.onResolveGone).toHaveBeenCalledOnce()
        cleanup()

        renderList({ threads: lost.slice(0, 1) })
        expect(screen.queryByRole('button', { name: /resolve all/u })).toBeNull()
        cleanup()
        renderList({ threads: lost, editable: false })
        expect(screen.queryByRole('button', { name: /resolve all/u })).toBeNull()
    })

    it('leaves out the thread shown at its passage instead', () => {
        renderList({
            threads: [thread('a', 'the cache'), thread('b', 'the queue')],
            found: new Set(['a', 'b']),
            hidden: 'a',
        })
        expect(cards()).toEqual(['Comment on “the queue”'])
    })

    it('drops the comment being written on Escape while empty, and leaves it open once it holds words', () => {
        const props = renderList({ draft: { quote: 'the retry', body: '', opened: 1 } })
        expect(screen.getByRole<HTMLButtonElement>('button', { name: 'Comment' }).disabled).toBe(true)
        fireEvent.keyDown(field('Comment'), { key: 'Escape' })
        expect(props.onDraftCancel).toHaveBeenCalledOnce()
        cleanup()

        const typed = renderList({ draft: { quote: 'the retry', body: 'Retry twice.', opened: 1 } })
        fireEvent.keyDown(field('Comment'), { key: 'Escape' })
        expect(typed.onDraftLeave).toHaveBeenCalledOnce()
        expect(typed.onDraftCancel).not.toHaveBeenCalled()
        fireEvent.keyDown(field('Comment'), { key: 'Enter' })
        expect(typed.onDraftSubmit).toHaveBeenCalledWith('Retry twice.')
    })

    it('offers labels on a comment being written, each leading it with its instruction, the cursor after it', () => {
        const props = renderList({ draft: { quote: 'the retry', body: '', opened: 1 } })
        const labels = within(screen.getByRole('group', { name: 'Labels' })).getAllByRole('button')
        expect(labels.map((button) => button.textContent)).toEqual(COMMENT_LABELS.map((label) => label.name))
        fireEvent.click(screen.getByRole('button', { name: 'Verify this' }))
        expect(props.onDraftChange).toHaveBeenCalledWith(expect.stringMatching(/^Verify this: .+\.\n\n$/su))
        expect(document.activeElement).toBe(field('Comment'))
        cleanup()

        // What the operator wrote already follows it.
        const typed = renderList({ draft: { quote: 'the retry', body: 'Retry twice.', opened: 1 } })
        fireEvent.click(screen.getByRole('button', { name: 'Needs tests' }))
        expect(typed.onDraftChange).toHaveBeenCalledWith(expect.stringMatching(/^Needs tests: .+\n\nRetry twice\.$/su))
    })
})

describe('ThreadCard', () => {
    it('offers reply on the open card, or one whose passage is gone, and nothing to do when read only', () => {
        renderCard({ active: false })
        expect(screen.queryByRole('button', { name: 'reply' })).toBeNull()
        expect(screen.getByRole('button', { name: 'resolve' })).toBeDefined()
        cleanup()
        renderCard({ active: false, lost: true })
        expect(screen.getByRole('button', { name: 'reply' })).toBeDefined()
        cleanup()
        renderCard({ editable: false })
        expect(screen.queryAllByRole('button').map((button) => button.textContent)).toEqual(['the cache'])
    })

    it('opens its thread on a click, and shows its passage from the quote, unless the passage is gone', () => {
        const did = renderCard({ active: false })
        fireEvent.click(screen.getByText('About the cache.'))
        expect(did.onOpen).toHaveBeenCalledWith('t1')
        fireEvent.click(screen.getByRole('button', { name: 'the cache' }))
        expect(did.onActivate).toHaveBeenCalledWith('t1')
        cleanup()

        const lost = renderCard({ active: false, lost: true })
        fireEvent.click(screen.getByText('About the cache.'))
        expect(lost.onOpen).not.toHaveBeenCalled()
        expect(screen.queryByRole('button', { name: 'the cache' })).toBeNull()
    })

    it('says each of its actions in words, as a row does, never by an icon alone', () => {
        renderCard({ thread: thread('t1', 'the cache', { replies: [{ id: 'r1', body: 'Agreed.', at: AT }] }) })
        const words = screen.getAllByRole('button').map((button) => button.textContent)
        expect(words).toEqual(['the cache', 'resolve', 'delete', 'edit', 'edit', 'reply'])
    })

    it('resolves an open thread, and reopens a resolved one', () => {
        const did = renderCard()
        fireEvent.click(screen.getByRole('button', { name: 'resolve' }))
        expect(did.onResolve).toHaveBeenCalledWith('t1', true)
        cleanup()
        const resolved = renderCard({ thread: thread('t1', 'the cache', { resolved: true }), active: false })
        fireEvent.click(screen.getByRole('button', { name: 'reopen' }))
        expect(resolved.onResolve).toHaveBeenCalledWith('t1', false)
        expect(screen.queryByRole('button', { name: 'Edit comment' })).toBeNull()
    })

    it('asks before deleting, its focus on Keep, and gives the focus back to delete when kept', () => {
        const replies = [{ id: 'r1', body: 'Agreed.', at: AT }]
        const did = renderCard({ thread: thread('t1', 'the cache', { replies }) })
        fireEvent.click(screen.getByRole('button', { name: 'delete' }))
        expect(screen.getByRole('group', { name: 'Delete this comment and its replies?' })).toBeDefined()
        const keep = screen.getByRole('button', { name: 'Keep' })
        expect(document.activeElement).toBe(keep)

        fireEvent.keyDown(keep, { key: 'Escape' })
        expect(screen.queryByRole('button', { name: 'Keep' })).toBeNull()
        expect(document.activeElement).toBe(screen.getByRole('button', { name: 'delete' }))
        expect(did.onDelete).not.toHaveBeenCalled()

        fireEvent.click(screen.getByRole('button', { name: 'delete' }))
        fireEvent.click(screen.getByRole('button', { name: 'Delete' }))
        expect(did.onDelete).toHaveBeenCalledWith('t1')
    })

    it('edits the comment or a reply in place, and goes back to the plan when the edit is cancelled', () => {
        const replies = [{ id: 'r1', body: 'Agreed.', at: AT }]
        const did = renderCard({ thread: thread('t1', 'the cache', { replies }) })

        fireEvent.click(screen.getByRole('button', { name: 'Edit comment' }))
        expect(field('Edit comment').value).toBe('About the cache.')
        // While one edit is open, nothing else in the card can be.
        expect(screen.queryByRole('button', { name: 'Edit reply' })).toBeNull()
        fireEvent.change(field('Edit comment'), { target: { value: '  Use a bounded cache.  ' } })
        fireEvent.click(screen.getByRole('button', { name: 'Save' }))
        expect(did.onEdit).toHaveBeenCalledWith('t1', 'Use a bounded cache.')

        fireEvent.click(screen.getByRole('button', { name: 'Edit reply' }))
        fireEvent.change(field('Edit reply'), { target: { value: 'Agreed, with a limit.' } })
        fireEvent.click(screen.getByRole('button', { name: 'Save' }))
        expect(did.onEdit).toHaveBeenLastCalledWith('t1', 'Agreed, with a limit.', 'r1')

        fireEvent.click(screen.getByRole('button', { name: 'Edit comment' }))
        fireEvent.click(screen.getByRole('button', { name: 'Cancel' }))
        expect(screen.queryByRole('form', { name: 'Edit comment' })).toBeNull()
        expect(did.onBack).toHaveBeenCalledWith('t1')
    })

    it('replies on the send key, and keeps the words when Escape leaves the reply for the plan', () => {
        const did = renderCard()
        fireEvent.click(screen.getByRole('button', { name: 'reply' }))
        expect(document.activeElement).toBe(field('Reply'))

        fireEvent.change(field('Reply'), { target: { value: 'Half a thought' } })
        fireEvent.keyDown(field('Reply'), { key: 'Escape' })
        expect(did.onBack).toHaveBeenCalledWith('t1')
        expect(field('Reply').value).toBe('Half a thought')

        // Shift+Enter is a new line; Enter sends.
        fireEvent.keyDown(field('Reply'), { key: 'Enter', shiftKey: true })
        expect(did.onReply).not.toHaveBeenCalled()
        fireEvent.keyDown(field('Reply'), { key: 'Enter' })
        expect(did.onReply).toHaveBeenCalledWith('t1', 'Half a thought')
        expect(screen.queryByRole('form', { name: 'Reply' })).toBeNull()
    })

    it('offers the labels on a new comment alone, not on a reply or an edit', () => {
        renderCard()
        fireEvent.click(screen.getByRole('button', { name: 'reply' }))
        expect(screen.queryByRole('group', { name: 'Labels' })).toBeNull()
        fireEvent.click(screen.getByRole('button', { name: 'Cancel' }))
        fireEvent.click(screen.getByRole('button', { name: 'Edit comment' }))
        expect(screen.queryByRole('group', { name: 'Labels' })).toBeNull()
    })

    it('keeps a comment as text, linking only its web addresses', () => {
        const body = 'See https://example.com/doc and <img src=x onerror="alert(1)">'
        renderCard({ thread: thread('t1', 'the cache', { body }) })
        expect(screen.getByRole('link', { name: 'https://example.com/doc' }).getAttribute('href')).toBe(
            'https://example.com/doc',
        )
        expect(screen.queryByRole('img')).toBeNull()
        expect(screen.getByText(/<img src=x onerror="alert\(1\)">/u)).toBeDefined()
    })

    it('draws a comment in the Markdown the conversation draws, as it was written in its field', () => {
        const body = 'Keep **one** cache:\n- per `repo`\n- not per run'
        renderCard({ thread: thread('t1', 'the cache', { body }) })
        expect(screen.getByText('one').tagName).toBe('STRONG')
        expect(screen.getByText('repo').tagName).toBe('CODE')
        expect(screen.getAllByRole('listitem').map((item) => item.textContent)).toEqual(['per repo', 'not per run'])
    })
})

describe('AskForChanges', () => {
    const starts = new Map([['a', 0]])

    it('asks with nothing only once there is an open comment or a note, and sends them as one message', () => {
        const onAsk = vi.fn<(message: string) => void>()
        const { rerender } = render(<AskForChanges threads={[]} starts={starts} edited={false} onAsk={onAsk} />)
        const ask = screen.getByRole<HTMLButtonElement>('button', { name: 'Ask for changes' })
        expect(ask.disabled).toBe(true)
        expect(screen.queryByText(/go(es)? with Ask for changes/u)).toBeNull()

        const threads = [thread('a', 'the cache')]
        rerender(<AskForChanges threads={threads} starts={starts} edited note="Approving sends none." onAsk={onAsk} />)
        expect(screen.getByText('1 open comment goes with Ask for changes. Approving sends none.')).toBeDefined()
        const note = screen.getByRole<HTMLTextAreaElement>('textbox', { name: 'On the whole plan' })
        fireEvent.change(note, { target: { value: 'Keep it short.' } })
        fireEvent.click(ask)
        expect(onAsk).toHaveBeenCalledWith(changeRequest(threads, starts, 'Keep it short.', true))
        expect(note.value).toBe('')
    })

    it('says how far over a reply’s bound the message is, rather than cut it', () => {
        const onAsk = vi.fn<(message: string) => void>()
        const long = [thread('a', 'the cache', { body: 'x'.repeat(4000) })]
        render(<AskForChanges threads={long} starts={starts} edited={false} onAsk={onAsk} />)
        const over = changeRequest(long, starts).length - 4000
        expect(screen.getByText(`${over} characters over a reply's bound: resolve or shorten some.`)).toBeDefined()
        expect(screen.getByRole<HTMLButtonElement>('button', { name: 'Ask for changes' }).disabled).toBe(true)
    })
})
