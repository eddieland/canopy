import { QueryClient } from '@tanstack/react-query'
import { cleanup, screen } from '@testing-library/react'
import { afterEach, describe, expect, it } from 'vitest'

import { draft, unsentDrafts } from '@/api/mocks'
import { keys } from '@/api/queries'
import type { UnsentDrafts } from '@/api/types'
import { renderRouted, tipOf } from '@/test-utils'

import { UnsentDraftsChip } from './unsent-drafts-chip'

afterEach(cleanup)

const PR = 'https://github.com/acme/web/pull/88'

// The chip over the drafts the test seeds, as a read would have left them: nothing is fetched.
function renderChip(groups: UnsentDrafts[], props: { url?: string; ticketKey?: string }) {
    const client = new QueryClient()
    client.setQueryDefaults(keys.unsentDrafts, { enabled: false })
    client.setQueryData(keys.unsentDrafts, groups)
    return renderRouted(<UnsentDraftsChip {...props} />, { client })
}

describe('UnsentDraftsChip', () => {
    it("counts a PR's drafts that wait, and opens its page at its list of them", async () => {
        await renderChip([unsentDrafts({ drafts: [draft(), draft({ number: 2 })] })], { url: PR })
        const link = screen.getByRole('link', { name: '2 drafts' })
        expect(tipOf(link)).toBe('2 drafts wait on you to send')
        expect(link.getAttribute('href')).toBe(`/pull-requests/pr?url=${encodeURIComponent(PR)}#drafts`)
    })

    it("counts a ticket's own drafts with its PRs', and opens the drafts page at the ticket", async () => {
        const groups = [unsentDrafts(), unsentDrafts({ pr_url: null, drafts: [draft({ kind: 'ticket' })] })]
        await renderChip(groups, { ticketKey: 'ABC-099' })
        expect(screen.getByRole('link', { name: '2 drafts' }).getAttribute('href')).toBe(
            '/pull-requests/drafts#drafts-ABC-099',
        )
    })

    it('says one draft waits, in the singular', async () => {
        await renderChip([unsentDrafts()], { url: PR })
        expect(tipOf(screen.getByRole('link', { name: '1 draft' }))).toBe('1 draft waits on you to send')
    })

    it('is nothing for a PR or a ticket no draft waits for', async () => {
        await renderChip([unsentDrafts()], { url: 'https://github.com/acme/web/pull/1' })
        expect(screen.queryByRole('link')).toBeNull()
    })
})
