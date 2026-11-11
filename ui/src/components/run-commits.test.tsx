import { cleanup, screen, within } from '@testing-library/react'
import { afterEach, describe, expect, it } from 'vitest'

import type { RunCommit } from '@/api/types'
import { CO_AUTHOR, NO_TRAILER, PUSHED_BY_CANOPY } from '@/lib/run-changes'
import { renderRouted, tipOf } from '@/test-utils'

import { RunCommits } from './run-commits'

afterEach(() => {
    cleanup()
})

const PR = 'https://github.com/acme/web/pull/88'
const MINE = '9b2f4c61aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa'
const AROUND = '3f7a0d52bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb'

function commit(sha: string, subject: string, fields: Partial<RunCommit> = {}): RunCommit {
    return {
        sha,
        subject,
        canopy_trailer: true,
        prefixed: null,
        runtime_trailer: false,
        harness_pushed: false,
        ...fields,
    }
}

const COMMITS = [
    commit(MINE, 'ABC-099: debounce the fetch <img src=x onerror=alert(1)>'),
    commit(AROUND, 'wip', { canopy_trailer: false, runtime_trailer: true, harness_pushed: true }),
]

describe('RunCommits', () => {
    it('lists each commit oldest first, its subject as text and its id opening its page through the PR', async () => {
        await renderRouted(<RunCommits commits={COMMITS} prUrl={PR} onOrigin leftOut="and 2 older commits" />)
        const rows = screen.getAllByTestId('run-commit')
        expect(rows.map((row) => row.textContent)).toEqual([
            '9b2f4c6ABC-099: debounce the fetch <img src=x onerror=alert(1)>',
            '3f7a0d5wipno trailerco-authorpushed by canopy',
        ])
        expect(screen.queryByRole('img')).toBeNull()
        const link = screen.getByRole('link', { name: '9b2f4c6' })
        expect(link.getAttribute('href')).toBe(`${PR}/commits/${MINE}`)
        expect(link.getAttribute('target')).toBe('_blank')
        expect(screen.getByText('and 2 older commits')).toBeDefined()
    })

    it('says on each chip what its mark means', async () => {
        await renderRouted(<RunCommits commits={COMMITS} prUrl={PR} onOrigin />)
        const around = screen.getAllByTestId('run-commit')[1]
        if (around === undefined) {
            throw new Error('no second commit')
        }
        expect(tipOf(within(around).getByText('no trailer'))).toContain(NO_TRAILER)
        expect(tipOf(within(around).getByText('co-author'))).toContain(CO_AUTHOR)
        expect(tipOf(within(around).getByText('pushed by canopy'))).toContain(PUSHED_BY_CANOPY)
    })

    it('links no commit left unpushed, nor one whose PR is not on GitHub', async () => {
        const { unmount } = await renderRouted(<RunCommits commits={COMMITS} prUrl={PR} onOrigin={false} />)
        expect(screen.queryAllByRole('link')).toEqual([])
        unmount()
        await renderRouted(<RunCommits commits={COMMITS} prUrl="https://git.example.test/a/b/pull/3" onOrigin />)
        expect(screen.queryAllByRole('link')).toEqual([])
        expect(screen.getAllByTestId('run-commit')).toHaveLength(2)
    })

    it('ends with the kick canopy pushed after the run, and shows nothing with neither', async () => {
        const kick = { from_head: AROUND, to_head: `c0ffee11${'c'.repeat(32)}`, kicked_at: '2026-10-08T11:00:00Z' }
        const { unmount } = await renderRouted(<RunCommits commits={COMMITS} prUrl={PR} onOrigin kick={kick} />)
        expect(screen.getByTestId('run-kick').textContent).toMatch(/^kicked 3f7a0d5 → c0ffee1/u)
        unmount()
        await renderRouted(<RunCommits commits={[]} prUrl={PR} onOrigin />)
        expect(screen.queryByTestId('run-commits')).toBeNull()
    })
})
