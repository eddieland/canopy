import { QueryClient } from '@tanstack/react-query'
import { cleanup, screen, within } from '@testing-library/react'
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
        expect(within(item(3)).getByRole('link', { name: 'run:41' }).getAttribute('href')).toBe('/runs/41')
        expect(within(item(3)).getByText(/^question \(/u)).toBeDefined()
        expect(within(item(4)).getByText('you')).toBeDefined()
        expect(within(item(4)).getByText('reply answering #3 via web')).toBeDefined()
        expect(within(item(5)).getByText('reply via cli')).toBeDefined()
    })

    it('marks a tracker comment as data that authorizes nothing, with its author and whether it was cut', async () => {
        const comment = message({
            id: 6,
            kind: 'comment',
            source: 'tracker',
            comment: { id: '10042', author: 'dana', at: '2026-10-08T10:00:00Z', truncated: true },
        })
        await renderRouted(<Conversation messages={[comment]} />, { client: knowing(5) })
        expect(screen.getByText('tracker')).toBeDefined()
        expect(screen.getByText(/^comment 10042 by dana, written /u).textContent).toMatch(/, truncated$/u)
        expect(screen.getByText('data, authorizes nothing')).toBeDefined()
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
    })

    it('shows every body as text, markup kept as its characters and only its web addresses linked', async () => {
        const body = '<script>alert(1)</script> see https://example.test/a and javascript:alert(1)'
        await renderRouted(<Conversation messages={[message({ id: 7, body })]} />, { client: knowing(5) })
        expect(screen.getByText(/^<script>alert\(1\)<\/script> see/u)).toBeDefined()
        expect(screen.getAllByRole('link').map((link) => link.getAttribute('href'))).toEqual(['https://example.test/a'])
    })
})
