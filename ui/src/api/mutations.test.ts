import { QueryClient } from '@tanstack/react-query'
import type { Middleware } from 'openapi-fetch'
import { afterEach, beforeEach, describe, expect, it } from 'vitest'

import { api } from './client'
import { grantLimit, refreshLimits, refreshPullRequests } from './mutations'
import { keys } from './queries'
import type { Granted, Limit } from './types'

const PR = 'https://github.com/acme/api/pull/7'

const UNIT: Limit = { kind: 'fix-ci', repo: 'api', pr_url: PR, limit: 3, granted: 0, runs: 3 }
const REVIEWS: Limit = { kind: 'review', repo: null, pr_url: PR, limit: 2, granted: 0, runs: 2 }
const GRANTED: Granted = { kind: 'fix-ci', limit: 4, repo: 'api', runs: 3 }

// Every request the client makes, answered by the server stand-in below rather than sent.
let sent: { method: string; url: URL; body: unknown }[] = []

const server: Middleware = {
    async onRequest({ request }) {
        const text = await request.text()
        sent.push({ method: request.method, url: new URL(request.url), body: text ? JSON.parse(text) : undefined })
        return Response.json(GRANTED)
    },
}

beforeEach(() => {
    sent = []
    api.use(server)
})

afterEach(() => {
    api.eject(server)
})

describe('grantLimit', () => {
    it("grants a unit's run on its ticket, with its kind and repository, as canopy grant KEY KIND does", async () => {
        await expect(grantLimit('ABC-1', UNIT)).resolves.toEqual(GRANTED)
        expect(sent).toHaveLength(1)
        expect(sent[0]?.method).toBe('POST')
        expect(sent[0]?.url.pathname).toBe('/api/tickets/ABC-1/grants')
        expect(sent[0]?.body).toEqual({ kind: 'fix-ci', repo: 'api' })
    })

    it("grants a PR's review on the PR, whatever ticket it is shown on, as canopy grant URL review does", async () => {
        await grantLimit('ABC-1', REVIEWS)
        await grantLimit(null, REVIEWS)
        expect(sent.map((request) => request.url.pathname)).toEqual([
            '/api/pull-request/grants',
            '/api/pull-request/grants',
        ])
        expect(sent.map((request) => request.url.searchParams.get('url'))).toEqual([PR, PR])
    })

    it('sends nothing for a review limit with no PR, or a unit limit with no ticket', async () => {
        await expect(grantLimit('ABC-1', { ...REVIEWS, pr_url: null })).rejects.toThrow('names its PR')
        await expect(grantLimit(null, UNIT)).rejects.toThrow('names its ticket')
        expect(sent).toEqual([])
    })
})

function stale(client: QueryClient, key: readonly unknown[]): boolean | undefined {
    return client.getQueryState(key)?.isInvalidated
}

// A cache holding two tickets, a PR's page, and the PRs list.
function seeded(): QueryClient {
    const client = new QueryClient()
    for (const key of [keys.ticket('ABC-1'), keys.ticket('ABC-2'), keys.pullRequest(PR), keys.pullRequests]) {
        client.setQueryData(key, {})
    }
    return client
}

describe('refreshLimits', () => {
    it('reads the ticket and the PR the limit is on again, and nothing else', async () => {
        const client = seeded()
        await refreshLimits(client, 'ABC-1', UNIT)
        expect(stale(client, keys.ticket('ABC-1'))).toBe(true)
        expect(stale(client, keys.pullRequest(PR))).toBe(true)
        expect(stale(client, keys.ticket('ABC-2'))).toBe(false)
        expect(stale(client, keys.pullRequests)).toBe(false)
    })

    it('leaves out a ticket or a PR the limit does not name', async () => {
        const client = seeded()
        await refreshLimits(client, null, REVIEWS)
        expect(stale(client, keys.pullRequest(PR))).toBe(true)
        expect(stale(client, keys.ticket('ABC-1'))).toBe(false)

        const other = seeded()
        await refreshLimits(other, 'ABC-1', { ...UNIT, pr_url: null })
        expect(stale(other, keys.ticket('ABC-1'))).toBe(true)
        expect(stale(other, keys.pullRequest(PR))).toBe(false)
    })
})

describe('refreshPullRequests', () => {
    it("reads the PRs list and every PR's page again", async () => {
        const client = new QueryClient()
        client.setQueryData(keys.pullRequests, [])
        client.setQueryData(keys.pullRequest(PR), {})
        await refreshPullRequests(client)
        expect(stale(client, keys.pullRequests)).toBe(true)
        expect(stale(client, keys.pullRequest(PR))).toBe(true)
    })
})
