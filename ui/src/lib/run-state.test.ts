import { describe, expect, it } from 'vitest'

import { mockRuns } from '@/api/mocks'
import type { Run } from '@/api/types'

import { workingOn } from './run-state'

const running = mockRuns[0] as Run

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
