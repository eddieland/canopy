import { describe, expect, it } from 'vitest'

import { draft, pullRequestThreads, reviewThread } from '@/api/mocks'

import { draftChars, movedHead, open, placeThreads, waiting } from './drafts'

describe('waiting', () => {
    it("takes the review's body first, then each thread's, and only what waits", () => {
        const body = draft({ kind: 'pr', number: 3, stance: null, comment_id: null })
        const threads = pullRequestThreads({
            pr_drafts: [body],
            threads: [
                reviewThread({ drafts: [draft(), draft({ number: 2, status: 'dropped' })] }),
                reviewThread({ id: 'PRRT_2', drafts: [draft({ number: 4, status: 'unchecked' })] }),
            ],
        })
        expect(waiting(threads).map((d) => d.number)).toEqual([3, 1])
    })
})

describe('open', () => {
    it('lets the operator edit or drop only a draft waiting or not yet checked', () => {
        expect(open(draft())).toBe(true)
        expect(open(draft({ status: 'unchecked' }))).toBe(true)
        for (const status of ['refused', 'superseded', 'dropped', 'sending', 'unconfirmed', 'sent'] as const) {
            expect(open(draft({ status }))).toBe(false)
        }
    })
})

describe('placeThreads', () => {
    it('puts a thread at its line, under its file without one, and elsewhere off the diff', () => {
        const at = reviewThread()
        const outdated = reviewThread({ id: 'PRRT_2', outdated: true, line: null, diff_line: null })
        const off = reviewThread({ id: 'PRRT_3', file: null, diff_line: null })
        const diff = { files: [], truncated: false }
        const placed = placeThreads(pullRequestThreads({ diff, threads: [at, outdated, off] }))
        expect(placed.lines.get(1)?.get(16)).toEqual([at])
        expect(placed.files.get(1)).toEqual([outdated])
        expect(placed.elsewhere).toEqual([off])
    })

    it('lists every thread elsewhere when no run kept a diff', () => {
        const placed = placeThreads(pullRequestThreads())
        expect(placed.elsewhere.map((t) => t.id)).toEqual(['PRRT_1'])
        expect(placed.lines.size).toBe(0)
    })
})

describe('movedHead', () => {
    it("names the PR's head only when it is known and past the kept diff's", () => {
        expect(movedHead({ head_sha: 'b', diff_head: 'a' })).toBe('b')
        expect(movedHead({ head_sha: 'a', diff_head: 'a' })).toBeNull()
        expect(movedHead({ head_sha: null, diff_head: 'a' })).toBeNull()
        expect(movedHead({ head_sha: 'b', diff_head: null })).toBeNull()
    })
})

describe('draftChars', () => {
    it('counts code points, as the bound does', () => {
        expect(draftChars('a😀b')).toBe(3)
    })
})
