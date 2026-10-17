import { cleanup, screen } from '@testing-library/react'
import { afterEach, describe, expect, it } from 'vitest'

import type { ChoreFinding, ChoreRunFinding } from '@/api/types'
import { renderRouted } from '@/test-utils'

import { ChoreFindingRow, ChoreFindingText } from './chore-finding'

afterEach(() => {
    cleanup()
})

const OPEN: ChoreFinding = {
    id: 'lodash-advisory',
    title: 'lodash 4.17.20 has a prototype pollution advisory',
    detail: 'Fixed upstream in https://github.com/acme/web/pull/88, see https://example.test/notes.',
    link: 'https://github.com/advisories/GHSA-35jh-r3h4-6jhm',
    since: '2026-10-08T08:00:00Z',
    dismissed: false,
}

const FROM_RUN: ChoreRunFinding = { id: OPEN.id, title: OPEN.title, detail: '', link: null }

describe('ChoreFindingRow', () => {
    it('offers to dismiss an open finding given its chore, and says it was dismissed once it is', async () => {
        const { unmount } = await renderRouted(<ChoreFindingRow finding={OPEN} chore="deps" />)
        expect(screen.getByRole('button', { name: 'dismiss' })).toBeDefined()
        expect(screen.queryByText('dismissed')).toBeNull()
        unmount()

        await renderRouted(<ChoreFindingRow finding={{ ...OPEN, dismissed: true }} chore="deps" />)
        expect(screen.getByText('dismissed')).toBeDefined()
        expect(screen.getByRole('button', { name: 'undo' })).toBeDefined()
    })

    it('offers nothing to act on for a finding without its chore, or one from a past run', async () => {
        const { unmount } = await renderRouted(<ChoreFindingRow finding={OPEN} />)
        expect(screen.queryByRole('button')).toBeNull()
        unmount()

        await renderRouted(<ChoreFindingRow finding={FROM_RUN} chore="deps" />)
        expect(screen.queryByRole('button')).toBeNull()
        expect(screen.queryByRole('link')).toBeNull()
    })

    it("links the URLs in the agent's detail, naming a PR as anywhere, and its link by its address", async () => {
        await renderRouted(<ChoreFindingRow finding={OPEN} chore="deps" />)
        const pr = screen.getByRole('link', { name: 'acme/web#88' })
        expect(pr.getAttribute('href')).toBe(
            `/pull-requests/pr?url=${encodeURIComponent('https://github.com/acme/web/pull/88')}`,
        )
        expect(screen.getByRole('link', { name: 'https://example.test/notes' }).getAttribute('rel')).toBe(
            'noreferrer noopener',
        )
        const out = screen.getByRole('link', { name: 'github.com/advisories/GHSA-35jh-r3h4-6jhm' })
        expect(out.getAttribute('href')).toBe(OPEN.link)
        expect(out.getAttribute('target')).toBe('_blank')
        expect(out.getAttribute('rel')).toBe('noreferrer noopener')
    })

    it("keeps markup in the agent's text as its characters", async () => {
        await renderRouted(<ChoreFindingRow finding={{ ...FROM_RUN, title: '<b>bold</b>', detail: '<img src=x>' }} />)
        expect(screen.getByText('<b>bold</b>')).toBeDefined()
        expect(screen.getByText('<img src=x>')).toBeDefined()
        expect(screen.queryByRole('img')).toBeNull()
    })
})

describe('ChoreFindingText', () => {
    it('names a PR link as the PR, opening its page in canopy, with the PR itself one click out', async () => {
        await renderRouted(
            <ChoreFindingText finding={{ ...OPEN, detail: '', link: 'https://github.com/acme/web/pull/88' }} />,
        )
        expect(screen.getByText(OPEN.title)).toBeDefined()
        expect(screen.getByRole('link', { name: 'acme/web#88' })).toBeDefined()
        expect(screen.getByRole('link', { name: 'acme/web#88 on GitHub' }).getAttribute('href')).toBe(
            'https://github.com/acme/web/pull/88',
        )
    })
})
