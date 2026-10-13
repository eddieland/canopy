import { describe, expect, it } from 'vitest'

import { mockRuns } from '@/api/mocks'
import type { Run } from '@/api/types'

import { railRuns, workingOn } from './run-state'

const running = mockRuns[0] as Run

function at(id: number, state: Run['state'], started_at: string): Run {
    return { ...running, id, state, started_at }
}

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

describe('railRuns', () => {
    it('puts the running runs first, then the ones waiting on an answer, each oldest first', () => {
        const runs = [
            at(1, 'running', '2026-10-08T12:10:00Z'),
            at(2, 'blocked', '2026-10-08T12:20:00Z'),
            at(3, 'running', '2026-10-08T12:00:00Z'),
            at(4, 'blocked', '2026-10-08T11:00:00Z'),
        ]
        expect(railRuns(runs, 10).shown.map((r) => r.id)).toEqual([3, 1, 4, 2])
    })

    it('leaves out the runs that ended', () => {
        const runs = [at(1, 'done', '2026-10-08T12:00:00Z'), at(2, 'failed', '2026-10-08T12:00:00Z')]
        expect(railRuns([...runs, ...mockRuns], 10).shown.map((r) => r.id)).toEqual([41, 42])
    })

    it('counts the runs past the limit', () => {
        const runs = Array.from({ length: 6 }, (_, i) => at(i, 'running', `2026-10-08T12:0${i}:00Z`))
        expect(railRuns(runs, 4)).toEqual({ shown: runs.slice(0, 4), more: 2 })
        expect(railRuns(runs.slice(0, 2), 4).more).toBe(0)
    })
})
