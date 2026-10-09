import { describe, expect, it } from 'vitest'

import type { Pool } from '@/api/types'

import { overSize, slotsRoot } from './worktree-state'

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

const at = (name: string, path: string) => ({ ...slot, name, path }) as unknown as Pool['worktrees'][number]

describe('slotsRoot', () => {
    it("is the directory every slot's own sits in, when they share one", () => {
        const slots = [at('1', '.treehouse/web-3f9c2a1b/1/web'), at('2', '.treehouse/web-3f9c2a1b/2/web')]
        expect(slotsRoot(slots)).toBe('.treehouse/web-3f9c2a1b')
    })

    it('is null when the slots live apart, or a path does not name its slot', () => {
        expect(slotsRoot([at('1', '/a/1/web'), at('2', '/b/2/web')])).toBeNull()
        expect(slotsRoot([at('1', '/elsewhere/web')])).toBeNull()
        expect(slotsRoot([])).toBeNull()
    })
})
