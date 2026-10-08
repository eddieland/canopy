import { describe, expect, it } from 'vitest'

import type { Pool } from '@/api/types'

import { overSize } from './worktree-state'

const slot = { name: '1', path: '.treehouse/web-3f9c2a1b/1/web', status: 'available', state: 'idle' } as const
const pool = (size: number | null, slots: number): Pool =>
    ({ repo: 'web', size, error: null, worktrees: Array.from({ length: slots }, () => slot) }) as unknown as Pool

describe('overSize', () => {
    it('counts slots past the declared size, and none without one', () => {
        expect(overSize(pool(4, 5))).toBe(1)
        expect(overSize(pool(4, 4))).toBe(0)
        expect(overSize(pool(4, 2))).toBe(0)
        expect(overSize(pool(0, 2))).toBe(2)
        expect(overSize(pool(null, 9))).toBe(0)
    })
})
