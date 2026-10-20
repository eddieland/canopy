import { describe, expect, it } from 'vitest'

import { mockChores, mockReviews, mockRuns } from '@/api/mocks'
import type { ChoreSummary, ReviewSummary, Run } from '@/api/types'

import { busy, byTicket, railWork, runsListed, subjectRuns, workingOn } from './run-state'
import type { RailItem, SubjectRuns } from './run-state'

const running = mockRuns[0] as Run

function at(id: number, state: Run['state'], started_at: string, ticket_key = `T-${id}`): Run {
    return { ...running, id, state, started_at, ticket_key }
}

describe('byTicket', () => {
    it("makes one entry per ticket, its latest run over the earlier ones, in the order of each ticket's latest", () => {
        const runs = [
            at(5, 'running', '2026-10-08T12:00:00Z', 'A'),
            at(4, 'blocked', '2026-10-08T11:00:00Z', 'B'),
            at(3, 'blocked', '2026-10-08T10:00:00Z', 'A'),
            at(2, 'blocked', '2026-10-08T09:00:00Z', 'B'),
            at(1, 'done', '2026-10-08T08:00:00Z', 'C'),
        ]
        const groups = byTicket(runs).map((g) => [g.latest.id, g.earlier.map((r) => r.id)])
        expect(groups).toEqual([
            [5, [3]],
            [4, [2]],
            [1, []],
        ])
    })
})

describe('workingOn', () => {
    it("lists the ticket's running runs, oldest first", () => {
        const later = { ...running, id: 50, started_at: '2026-10-08T12:05:00Z' }
        expect(workingOn([later, ...mockRuns], 'ABC-101').map((r) => r.id)).toEqual([41, 50])
    })

    it("leaves out another ticket's runs, and the ticket's runs that have ended", () => {
        const ended = { ...running, id: 51, status: 'done', state: 'done' as const, ended_at: '2026-10-08T12:10:00Z' }
        expect(workingOn([ended, ...mockRuns], 'ABC-101').map((r) => r.id)).toEqual([41])
        expect(workingOn(mockRuns, 'ABC-102')).toEqual([])
    })
})

// Each row as its kind and id, for comparing an order.
function ids(items: RailItem[]): string[] {
    return items.map((item) => `${item.kind}:${item.kind === 'review' ? item.review.id : item.run.id}`)
}

function review(id: number, state: ReviewSummary['state'], started_at: string): ReviewSummary {
    return { ...(mockReviews[0] as ReviewSummary), id, state, started_at }
}

function chore(name: string, id: number | null, started_at = '2026-10-08T12:00:00Z'): ChoreSummary {
    const base = mockChores[0] as ChoreSummary
    const run = id === null ? null : { ...(base.latest as NonNullable<ChoreSummary['latest']>), id, started_at }
    return { ...base, name, running: run === null ? null : { ...run, status: 'running', state: 'running' } }
}

describe('railWork', () => {
    it('puts the running runs first, then the ones waiting on an answer, each oldest first', () => {
        const runs = [
            at(1, 'running', '2026-10-08T12:10:00Z'),
            at(2, 'blocked', '2026-10-08T12:20:00Z'),
            at(3, 'running', '2026-10-08T12:00:00Z'),
            at(4, 'blocked', '2026-10-08T11:00:00Z'),
        ]
        expect(ids(railWork({ runs }, 10).shown)).toEqual(['run:3', 'run:1', 'run:4', 'run:2'])
    })

    it('lists the reviews and chore runs running among the running runs, by when each started', () => {
        const runs = [at(1, 'running', '2026-10-08T12:10:00Z'), at(2, 'blocked', '2026-10-08T11:00:00Z')]
        const reviews = [review(7, 'running', '2026-10-08T12:05:00Z'), review(6, 'done', '2026-10-08T11:00:00Z')]
        const chores = [chore('deps', 3, '2026-10-08T12:15:00Z'), chore('idle', null)]
        expect(ids(railWork({ runs, reviews, chores }, 10).shown)).toEqual(['review:7', 'run:1', 'chore:3', 'run:2'])
    })

    it('leaves out the runs that ended', () => {
        const runs = [at(1, 'done', '2026-10-08T12:00:00Z'), at(2, 'failed', '2026-10-08T12:00:00Z')]
        expect(ids(railWork({ runs: [...runs, ...mockRuns] }, 10).shown)).toEqual(['run:41', 'run:42'])
    })

    it("leaves out a blocked run a later run of its ticket followed, and lists each ticket's latest once", () => {
        const runs = [
            at(3, 'running', '2026-10-08T12:00:00Z', 'A'),
            at(2, 'blocked', '2026-10-08T11:00:00Z', 'A'),
            at(4, 'blocked', '2026-10-08T10:30:00Z', 'B'),
            at(1, 'blocked', '2026-10-08T10:00:00Z', 'B'),
        ]
        expect(ids(railWork({ runs }, 10).shown)).toEqual(['run:3', 'run:4'])
    })

    it('leaves out a blocked run whose ticket the operator stopped, and keeps a running one, which still works', () => {
        const runs = [
            { ...at(1, 'running', '2026-10-08T12:00:00Z'), ticket_stopped: true },
            { ...at(2, 'blocked', '2026-10-08T11:00:00Z'), ticket_stopped: true },
            at(3, 'blocked', '2026-10-08T10:00:00Z'),
        ]
        expect(ids(railWork({ runs }, 10).shown)).toEqual(['run:1', 'run:3'])
    })

    it('counts the rows past the limit, and opens the page of their kind, or the runs page for a mix', () => {
        const runs = Array.from({ length: 6 }, (_, i) => at(i, 'running', `2026-10-08T12:0${i}:00Z`))
        expect(railWork({ runs }, 4)).toEqual({
            shown: runs.slice(0, 4).map((run) => ({ kind: 'run', run })),
            more: 2,
            moreAt: '/runs',
        })
        expect(railWork({ runs: runs.slice(0, 2) }, 4).more).toBe(0)

        const reviews = [review(8, 'running', '2026-10-08T13:00:00Z'), review(9, 'running', '2026-10-08T13:01:00Z')]
        expect(railWork({ runs: runs.slice(0, 4), reviews }, 4).moreAt).toBe('/reviews')
        const chores = [chore('deps', 3, '2026-10-08T13:00:00Z')]
        expect(railWork({ runs: runs.slice(0, 4), chores }, 4).moreAt).toBe('/chores')
        expect(railWork({ runs: runs.slice(0, 4), reviews, chores }, 4).moreAt).toBe('/runs')
    })
})

// Each subject as its kind, its latest run's id, and its earlier runs' ids, for comparing an order.
function subjects(groups: SubjectRuns[]): [string, number, number[]][] {
    return groups.map((g) => [g.of, g.latest.id, g.earlier.map((r) => r.id)])
}

function finished<T extends Run | ReviewSummary>(item: T, endedAt: string): T {
    return { ...item, status: 'done', state: 'done', ended_at: endedAt }
}

describe('subjectRuns', () => {
    it('lists the running runs of every kind first, the first to start leading, then the rest by their end', () => {
        const runs = [
            at(9, 'running', '2026-10-08T12:10:00Z', 'A'),
            finished(at(8, 'done', '2026-10-08T09:00:00Z', 'B'), '2026-10-08T10:00:00Z'),
        ]
        const reviews = [
            review(7, 'running', '2026-10-08T12:05:00Z'),
            finished(
                { ...review(6, 'done', '2026-10-08T10:30:00Z'), pr_url: 'https://github.com/acme/api/pull/3' },
                '2026-10-08T11:00:00Z',
            ),
        ]
        const chores = [chore('deps', 3, '2026-10-08T12:15:00Z'), { ...chore('idle', null), latest: null }]
        expect(subjects(subjectRuns({ runs, reviews, chores }))).toEqual([
            ['review', 7, []],
            ['worker', 9, []],
            ['chore', 3, [2]],
            ['review', 6, []],
            ['worker', 8, []],
        ])
    })

    it("folds a PR's earlier reviews under its latest, and lists a chore by its latest run when none runs", () => {
        const reviews = [review(7, 'done', '2026-10-08T12:05:00Z'), review(4, 'failed', '2026-10-08T10:00:00Z')]
        const groups = subjectRuns({ runs: [], reviews, chores: mockChores })
        expect(subjects(groups)).toEqual([
            ['review', 7, [4]],
            ['chore', 2, []],
        ])
        expect(runsListed(groups)).toBe(3)
    })
})

describe('busy', () => {
    it('counts the reviews among the workers, as max_workers does, and the chores apart', () => {
        const runs = [at(1, 'running', '2026-10-08T12:00:00Z'), at(2, 'blocked', '2026-10-08T11:00:00Z')]
        const reviews = [review(7, 'running', '2026-10-08T12:05:00Z'), review(6, 'done', '2026-10-08T11:00:00Z')]
        const chores = [chore('deps', 3), chore('idle', null)]
        expect(busy({ runs, reviews, chores })).toEqual({ workers: 2, reviews: 1, chores: 1 })
        expect(busy({ runs })).toEqual({ workers: 1, reviews: 0, chores: 0 })
    })
})
