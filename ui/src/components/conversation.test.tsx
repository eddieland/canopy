import { QueryClient } from '@tanstack/react-query'
import { act, cleanup, screen, within } from '@testing-library/react'
import type { Middleware } from 'openapi-fetch'
import { afterEach, beforeEach, describe, expect, it } from 'vitest'

import { api } from '@/api/client'
import { keys } from '@/api/queries'
import type { Message } from '@/api/types'
import { renderRouted } from '@/test-utils'

import { Conversation } from './conversation'

const UNREAD = 'No tick has read it yet. The loop acts on it, and the attention list catches up, at the next tick.'

function message(fields: Partial<Message> & Pick<Message, 'id'>): Message {
    return {
        at: '2026-10-08T11:00:00Z',
        body: 'Done.',
        channel: 'web',
        comment: null,
        kind: 'report',
        run_id: null,
        task_run_id: null,
        source: 'worker',
        answers: null,
        ...fields,
    }
}

const QUESTION = message({ id: 3, kind: 'question', run_id: 41, body: 'Red or blue?' })
const REPLY = message({ id: 4, kind: 'reply', source: 'operator', answers: 3, body: 'Blue.' })
const LATER = message({ id: 5, kind: 'reply', source: 'operator', channel: 'cli', body: 'And add a test.' })

// The server stand-in: the latest `ok` tick read up to message 4.
const server: Middleware = {
    onRequest() {
        return Response.json({ tick: null, acknowledged: 4 })
    },
}

beforeEach(() => {
    api.use(server)
})

afterEach(() => {
    api.eject(server)
    cleanup()
})

// A client that already knows what the latest tick read, so nothing is fetched.
function knowing(read: number | null): QueryClient {
    const client = new QueryClient({ defaultOptions: { queries: { staleTime: Infinity } } })
    client.setQueryData(keys.tick, { tick: null, acknowledged: read })
    return client
}

function item(n: number): HTMLElement {
    const found = screen.getAllByRole('listitem').find((li) => li.textContent.startsWith(`#${n}`))
    if (found === undefined) {
        throw new Error(`no message #${n}`)
    }
    return found
}

describe('Conversation', () => {
    it('heads each message, in order, with who wrote it, its kind, its run, what it answers, and how', async () => {
        await renderRouted(<Conversation messages={[QUESTION, REPLY, LATER]} />, { client: knowing(5) })
        expect(screen.getAllByRole('listitem').map((li) => li.textContent.slice(0, 2))).toEqual(['#3', '#4', '#5'])
        expect(within(item(3)).getByRole('link', { name: 'run:41' }).getAttribute('href')).toBe('/workspace/runs/41')
        expect(within(item(3)).getByText(/^question \(/u)).toBeDefined()
        expect(within(item(4)).getByText('you')).toBeDefined()
        expect(within(item(4)).getByText('reply answering #3 via web')).toBeDefined()
        expect(within(item(5)).getByText('reply via cli')).toBeDefined()
    })

    it("heads canopy's note on a tick with who wrote it and the message it answers, never as unread", async () => {
        const note = message({
            id: 6,
            kind: 'note',
            source: 'canopy',
            channel: 'tick',
            answers: 5,
            body: 'Tick 12 read message 5: started run 57 (resume).',
        })
        await renderRouted(<Conversation messages={[LATER, note]} />, { client: knowing(4) })
        expect(within(item(6)).getByText('canopy')).toBeDefined()
        expect(within(item(6)).getByText('note answering #5')).toBeDefined()
        expect(within(item(6)).getByText('Tick 12 read message 5: started run 57 (resume).')).toBeDefined()
        // Only the operator's own messages wait on a tick; canopy's note is what a tick said.
        expect(within(item(6)).queryByText('waiting for the next tick')).toBeNull()
    })

    it('marks a tracker comment as data that authorizes nothing, by its author, and whether it was cut', async () => {
        const comment = message({
            id: 6,
            kind: 'comment',
            source: 'tracker',
            comment: { id: '10042', author: 'dana', at: '2026-10-08T10:00:00Z', truncated: true },
        })
        await renderRouted(<Conversation messages={[comment]} />, { client: knowing(5) })
        expect(screen.getByText('dana')).toBeDefined()
        const where = screen.getByText('on the tracker, truncated')
        expect(where.getAttribute('title')).toMatch(/^comment 10042, written .*, truncated$/u)
        expect(screen.getByText('data, authorizes nothing')).toBeDefined()
    })

    it("stacks one speaker's lines in a turn under one head, but never a reply to a question", async () => {
        const first = message({ id: 6, run_id: 41, body: 'Wired the button.' })
        const second = message({ id: 7, run_id: 41, at: '2026-10-08T11:02:00Z', body: 'Tests pass.' })
        const later = message({ id: 8, run_id: 41, at: '2026-10-08T11:30:00Z', body: 'Pushed.' })
        await renderRouted(<Conversation messages={[first, second, later, QUESTION, REPLY]} />, {
            client: knowing(5),
        })
        expect(within(item(6)).getByText('worker')).toBeDefined()
        expect(within(item(7)).queryByText('worker')).toBeNull()
        expect(within(item(7)).getByText('Tests pass.')).toBeDefined()
        // Half an hour on, it is a turn of its own.
        expect(within(item(8)).getByText('worker')).toBeDefined()
        expect(within(item(4)).getByText('reply answering #3 via web')).toBeDefined()
    })

    it("starts a new turn for another run's message, and never stacks tracker comments", async () => {
        const first = message({ id: 6, run_id: 41, body: 'Wired the button.' })
        const other = message({ id: 7, run_id: 42, at: '2026-10-08T11:01:00Z', body: 'Started over.' })
        const said = { author: 'dana', at: '2026-10-08T11:01:00Z', truncated: false }
        const comment = message({ id: 8, kind: 'comment', source: 'tracker', comment: { id: '1', ...said } })
        const again = message({ id: 9, kind: 'comment', source: 'tracker', comment: { id: '2', ...said } })
        await renderRouted(<Conversation messages={[first, other, comment, again]} />, { client: knowing(5) })
        expect(within(item(7)).getByText('worker')).toBeDefined()
        expect(within(item(9)).getByText('dana')).toBeDefined()
    })

    it('says which message waits on you, and only that one', async () => {
        await renderRouted(<Conversation messages={[QUESTION, REPLY]} waiting={3} />, { client: knowing(5) })
        expect(within(item(3)).getByText('waiting on you')).toBeDefined()
        expect(within(item(4)).queryByText('waiting on you')).toBeNull()
    })

    it("marks the operator's messages no tick has read yet, and nothing before it knows what a tick read", async () => {
        await renderRouted(<Conversation messages={[QUESTION, REPLY, LATER]} />)
        expect(screen.queryByText('waiting for the next tick')).toBeNull()

        expect((await within(item(5)).findByTitle(UNREAD)).textContent).toBe('waiting for the next tick')
        expect(screen.getAllByText('waiting for the next tick')).toHaveLength(1)
    })

    it("marks every one of the operator's messages before the first tick, but never another's", async () => {
        await renderRouted(<Conversation messages={[QUESTION, REPLY, LATER]} />, { client: knowing(null) })
        expect(within(item(3)).queryByText('waiting for the next tick')).toBeNull()
        expect(within(item(4)).getByText('waiting for the next tick')).toBeDefined()
        expect(within(item(5)).getByText('waiting for the next tick')).toBeDefined()
    })

    it("marks the operator's messages a tick has read as seen, and never another's", async () => {
        await renderRouted(<Conversation messages={[QUESTION, REPLY, LATER]} />, { client: knowing(4) })
        expect(within(item(3)).queryByText('seen')).toBeNull()
        expect(within(item(4)).getByText('seen')).toBeDefined()
        expect(within(item(4)).queryByText('waiting for the next tick')).toBeNull()
        expect(within(item(5)).queryByText('seen')).toBeNull()
    })

    it("turns a reply's chip to seen in place as a tick reads it", async () => {
        const client = knowing(3)
        await renderRouted(<Conversation messages={[QUESTION, REPLY]} />, { client })
        expect(within(item(4)).getByText('waiting for the next tick')).toBeDefined()
        act(() => {
            client.setQueryData(keys.tick, { tick: null, acknowledged: 4 })
        })
        expect(await within(item(4)).findByText('seen')).toBeDefined()
        expect(within(item(4)).queryByText('waiting for the next tick')).toBeNull()
    })

    it("says what a chore's notes wait for instead, when told", async () => {
        const pending = {
            label: 'waiting for the next run',
            title: 'No run has read it.',
            test: (m: Message) => m.id === 4,
        }
        await renderRouted(<Conversation messages={[REPLY, LATER]} pending={pending} />, { client: knowing(null) })
        expect(within(item(4)).getByText('waiting for the next run')).toBeDefined()
        expect(within(item(5)).queryByText('waiting for the next run')).toBeNull()
        expect(screen.queryByText('waiting for the next tick')).toBeNull()
        expect(screen.queryByText('seen')).toBeNull()
    })

    it("lays out a body's Markdown, a labelled link showing its URL", async () => {
        const body =
            'Two things to settle:\n\n- the **color**\n- the `csv` header\n\nSee [the doc](https://example.test/d)'
        await renderRouted(<Conversation messages={[message({ id: 7, body })]} />, { client: knowing(5) })
        expect(screen.getByText('Two things to settle:')).toBeDefined()
        expect(
            within(item(7))
                .getAllByRole('listitem')
                .map((li) => li.textContent),
        ).toEqual(['the color', 'the csv header'])
        expect(within(item(7)).getByRole('code').textContent).toBe('csv')
        expect(within(item(7)).getByRole('link').textContent).toBe('https://example.test/d')
    })

    it('shows every body as text, markup kept as its characters and only its web addresses linked', async () => {
        const body = '<script>alert(1)</script> see https://example.test/a and javascript:alert(1)'
        await renderRouted(<Conversation messages={[message({ id: 7, body })]} />, { client: knowing(5) })
        expect(screen.getByText(/^<script>alert\(1\)<\/script> see/u)).toBeDefined()
        expect(screen.getAllByRole('link').map((link) => link.getAttribute('href'))).toEqual(['https://example.test/a'])
    })
})
