import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { cleanup, fireEvent, render, screen, within } from '@testing-library/react'
import type { Middleware } from 'openapi-fetch'
import { afterEach, beforeEach, describe, expect, it } from 'vitest'

import { api } from '@/api/client'
import type { Limit } from '@/api/types'

import { GrantLimits } from './grant-limits'

const PR = 'https://github.com/acme/web/pull/88'
const IMPLEMENT: Limit = { kind: 'implement', repo: 'web', pr_url: null, runs: 3, granted: 0, limit: 3 }
const FIX_CI: Limit = { kind: 'fix-ci', repo: 'api', pr_url: null, runs: 1, granted: 1, limit: 2 }
const REVIEW: Limit = { kind: 'review', repo: 'web', pr_url: PR, runs: 2, granted: 0, limit: 2 }

// Every grant the buttons send, and what the server stand-in answers each.
let sent: { path: string; url: string | null; body: unknown }[] = []
let answer: Response | undefined

const server: Middleware = {
    async onRequest({ request }) {
        const text = await request.text()
        const url = new URL(request.url)
        sent.push({
            path: url.pathname,
            url: url.searchParams.get('url'),
            body: text ? (JSON.parse(text) as unknown) : undefined,
        })
        return answer ?? Response.json({ kind: 'implement', repo: 'web', runs: 3, limit: 4 })
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

function renderLimits(limits: Limit[], ticketKey: string | null = 'ABC-1', ownPr?: string) {
    const client = new QueryClient()
    const ui = (shown: Limit[]) => (
        <QueryClientProvider client={client}>
            <GrantLimits limits={shown} ticketKey={ticketKey} ownPr={ownPr} />
        </QueryClientProvider>
    )
    const result = render(ui(limits))
    return { ...result, rerenderWith: (shown: Limit[]) => result.rerender(ui(shown)) }
}

// Each row shown: its label and its count, without the button.
function rows(): string[] {
    return screen.getAllByRole('listitem').map((row) => row.textContent.replace('Allow one more', ''))
}

describe('GrantLimits', () => {
    it('shows nothing while nothing is at its limit', () => {
        const { container } = renderLimits([{ ...IMPLEMENT, runs: 2 }, FIX_CI])
        expect(container.childElementCount).toBe(0)
    })

    it('lists a row for each limit reached, and none for those still under', () => {
        renderLimits([IMPLEMENT, FIX_CI, { ...FIX_CI, repo: 'web', runs: 2, granted: 1 }])
        expect(screen.getByText(/^At its limit\./u)).toBeDefined()
        expect(rows()).toEqual(['implement in web3 of 3 runs', 'fix-ci in web2 of 2 runs, 1 granted'])
    })

    it('names the CLI command for the same grant on hover', () => {
        renderLimits([IMPLEMENT, { ...IMPLEMENT, kind: 'resume', repo: null }, REVIEW])
        const titles = screen.getAllByRole('button', { name: 'Allow one more' }).map((button) => button.title)
        expect(titles).toEqual([
            'canopy grant ABC-1 implement --repo web',
            'canopy grant ABC-1 resume',
            `canopy grant ${PR} review`,
        ])
    })

    it('grants a unit one more run, says so as the CLI does, and still says so once nothing is stuck', async () => {
        const { rerenderWith } = renderLimits([IMPLEMENT])
        fireEvent.click(screen.getByRole('button', { name: 'Allow one more' }))

        expect((await screen.findByRole('status')).textContent).toBe(
            'ABC-1 in web has had 3 implement runs, and may now have 4. The next tick decides whether to dispatch it.',
        )
        expect(sent).toEqual([
            { path: '/api/tickets/ABC-1/grants', url: null, body: { kind: 'implement', repo: 'web' } },
        ])

        rerenderWith([{ ...IMPLEMENT, granted: 1, limit: 4 }])
        expect(screen.queryByRole('listitem')).toBeNull()
        expect(screen.getByRole('status').textContent).toMatch(/^ABC-1 in web has had 3 implement runs/u)
    })

    it("grants a PR's review on its own page, where the limit is just its reviews", async () => {
        answer = Response.json({ kind: 'review', repo: 'web', runs: 2, limit: 3 })
        renderLimits([REVIEW], null, PR)
        const row = screen.getByRole('listitem')
        expect(within(row).getByText('reviews')).toBeDefined()

        fireEvent.click(within(row).getByRole('button', { name: 'Allow one more' }))
        expect((await screen.findByRole('status')).textContent).toBe(
            `${PR} has had 2 review runs, and may now have 3. The next tick decides whether to review it.`,
        )
        expect(sent).toEqual([{ path: '/api/pull-request/grants', url: PR, body: undefined }])
    })

    it('names the guard that refused a grant', async () => {
        answer = Response.json(
            { detail: { guard: 'not_at_limit', reason: 'ABC-1 is under its limit' } },
            { status: 409 },
        )
        renderLimits([IMPLEMENT])
        fireEvent.click(screen.getByRole('button', { name: 'Allow one more' }))
        expect((await screen.findByRole('alert')).textContent).toBe('refused (not_at_limit): ABC-1 is under its limit')
    })
})
