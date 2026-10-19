import { describe, expect, it } from 'vitest'

import { draft, pullRequestThreads, reviewThread } from '@/api/mocks'

import { draftAnchor, draftChars, listDrafts, movedHead, open, placeThreads, threadWhere, waiting } from './drafts'

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
        for (const status of [
            'refused',
            'superseded',
            'dropped',
            'sending',
            'unconfirmed',
            'staged',
            'sent',
        ] as const) {
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

describe('listDrafts', () => {
    it('lists every draft in the order the page shows its card, with where it is and the file it sits on', () => {
        const threads = pullRequestThreads({
            diff: { files: [], truncated: false },
            pr_drafts: [draft({ kind: 'pr', number: 5, stance: null, comment_id: null })],
            threads: [
                reviewThread({ id: 'late', line: 40, diff_line: 40, drafts: [draft({ number: 1 })] }),
                reviewThread({ id: 'off', path: 'README.md', line: 2, file: null, drafts: [draft({ number: 2 })] }),
                reviewThread({ id: 'early', line: 9, diff_line: 9, drafts: [draft({ number: 3 })] }),
                reviewThread({ id: 'first', path: 'a.ts', file: 0, diff_line: null, drafts: [draft({ number: 4 })] }),
                reviewThread({ id: 'none', drafts: [] }),
            ],
            unplaced: [draft({ run: 46, number: 1, comment_id: 99, thread_id: null })],
        })
        expect(
            listDrafts(threads, placeThreads(threads)).map(({ draft: d, where, file }) => [d.number, where, file]),
        ).toEqual([
            [5, "the review's body", null],
            [4, 'a.ts:16', 0],
            [3, 'src/search/useSearch.ts:9', 1],
            [1, 'src/search/useSearch.ts:40', 1],
            [2, 'README.md:2', null],
            [1, 'not on a thread', null],
        ])
    })
})

describe('threadWhere', () => {
    it("names a thread's file and line, its file alone, or nothing", () => {
        expect(threadWhere({ path: 'a.ts', line: 3 })).toBe('a.ts:3')
        expect(threadWhere({ path: 'a.ts', line: null })).toBe('a.ts')
        expect(threadWhere({ path: null, line: null })).toBeNull()
    })
})

describe('draftAnchor', () => {
    it('names a draft by its run and number, which name it alone', () => {
        expect(draftAnchor(draft({ run: 46, number: 2 }))).toBe('draft-46-2')
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
