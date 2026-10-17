import { QueryClient } from '@tanstack/react-query'
import { cleanup, screen, within } from '@testing-library/react'
import { afterEach, describe, expect, it } from 'vitest'

import { keys } from '@/api/queries'
import type { Decision } from '@/api/types'
import { renderRouted } from '@/test-utils'

import { Decisions } from './decisions'

afterEach(() => {
    cleanup()
})

const PR = 'https://github.com/acme/web/pull/88'

function decision(fields: Partial<Decision>): Decision {
    return {
        id: 1,
        tick_id: 3,
        at: '2026-10-08T12:00:00Z',
        action: 'wait',
        subject: 'ABC-1',
        ticket_key: null,
        chore: null,
        repo: null,
        pr: null,
        rationale: 'Nothing to do yet.',
        ...fields,
    }
}

function renderDecisions(decisions: Decision[], props: { byTick?: boolean; ownPr?: string } = {}) {
    const client = new QueryClient()
    // No tracker URL: a ticket's key links in alone.
    client.setQueryDefaults(keys.meta, { enabled: false })
    return renderRouted(<Decisions decisions={decisions} {...props} />, { client })
}

// One decision's row.
function row(id: number) {
    return within(screen.getByTestId(`decision-${id}`))
}

describe('Decisions', () => {
    it('names what each was about: a chore, a ticket in its repo, a PR no ticket owns, or the subject', async () => {
        await renderDecisions([
            decision({ id: 1, subject: 'chore:deps', chore: 'deps' }),
            decision({ id: 2, ticket_key: 'ABC-1', repo: 'web' }),
            decision({ id: 3, subject: PR, pr: PR, action: 'review' }),
            decision({ id: 4, subject: 'repo web', repo: 'web', action: 'reconcile' }),
        ])
        expect(row(1).getByRole('link', { name: 'chore:deps' }).getAttribute('href')).toBe('/chores/deps')
        expect(row(2).getByRole('link', { name: 'ABC-1' }).getAttribute('href')).toBe('/tickets/ABC-1')
        expect(row(2).getByText('(web)', { exact: false })).toBeDefined()
        // A PR that is the subject is named once, not again beside the action.
        expect(row(3).getAllByRole('link', { name: 'acme/web#88' })).toHaveLength(1)
        expect(row(4).getByTitle('repo web').textContent).toBe('repo web')
        expect(row(4).queryByRole('link')).toBeNull()
    })

    it("names a decision's PR beside its action, but not on that PR's own page", async () => {
        const { unmount } = await renderDecisions([decision({ ticket_key: 'ABC-1', pr: PR, action: 'implement' })])
        expect(row(1).getByRole('link', { name: 'acme/web#88' })).toBeDefined()
        unmount()

        await renderDecisions([decision({ ticket_key: 'ABC-1', pr: PR })], { ownPr: PR })
        expect(row(1).queryByRole('link', { name: 'acme/web#88' })).toBeNull()
    })

    it("on a subject's page names the tick for the subject, and a PR it was about beside the action", async () => {
        await renderDecisions([decision({ subject: PR, pr: PR, action: 'review' })], { byTick: true })
        expect(row(1).getByRole('link', { name: 'tick:3' }).getAttribute('href')).toBe('/ticks/3')
        expect(row(1).getByRole('link', { name: 'acme/web#88' })).toBeDefined()
    })

    it("reads the action as words with the CLI's spelling on hover, and the rationale as written", async () => {
        const rationale = 'Needs a **reviewer**: <img src=x> [see](javascript:alert(1))'
        await renderDecisions([decision({ action: 'attention:needs_reviewer', rationale })])
        expect(row(1).getByTitle('attention:needs_reviewer').textContent).toBe('attention: needs reviewer')
        expect(row(1).getByText(/^Needs a/u).textContent).toBe(
            'Needs a reviewer: <img src=x> [see](javascript:alert(1))',
        )
        expect(row(1).queryByRole('img')).toBeNull()
        expect(row(1).queryByRole('link')).toBeNull()
    })
})
