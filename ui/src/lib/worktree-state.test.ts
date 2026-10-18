import { describe, expect, it } from 'vitest'

import type { Pool, WorktreeState } from '@/api/types'

import { heldBy, needsLook, overSize, poolsLine, poolShown, slotGroups, slotsRoot } from './worktree-state'

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

// A pool's slots from one letter each, `i` idle and `w` working, named from 1.
function lettered(states: string): Pool['worktrees'] {
    return states.split('').map((letter, i) => {
        const state = letter === 'i' ? 'idle' : 'working'
        return Object.assign(at(String(i + 1), `.treehouse/web-3f9c2a1b/${i + 1}/web`), { state })
    })
}

// Each group by its slots' names: a slot alone, or a run of idle ones joined by `-`.
function shape(states: string, state?: WorktreeState): string[] {
    return slotGroups(lettered(states), state).map((g) =>
        g.kind === 'slot' ? g.worktree.name : g.worktrees.map((w) => w.name).join('-'),
    )
}

describe('slotGroups', () => {
    it('folds three or more idle slots in a row into one group, in slot order', () => {
        expect(shape('wiiiw')).toEqual(['1', '2-3-4', '5'])
        expect(shape('iiiiiiii')).toEqual(['1-2-3-4-5-6-7-8'])
        expect(shape('wwiii')).toEqual(['1', '2', '3-4-5'])
    })

    it('keeps one or two idle slots in a row as they are', () => {
        expect(shape('iwiiw')).toEqual(['1', '2', '3', '4', '5'])
        expect(shape('ii')).toEqual(['1', '2'])
        expect(shape('')).toEqual([])
    })
})

describe('slotGroups by state', () => {
    it('keeps the groups in the state, idle ones folded as they lie in the whole pool', () => {
        expect(shape('iiwiwiii', 'idle')).toEqual(['1', '2', '4', '6-7-8'])
        expect(shape('iiwiwiii', 'working')).toEqual(['3', '5'])
        expect(shape('iiwiwiii', 'dirty')).toEqual([])
    })
})

describe('poolShown', () => {
    const slots = lettered('wi')

    it('shows every pool with no filter, and one with a slot in the state with one', () => {
        expect(poolShown(pool(2, 0), undefined)).toBe(true)
        expect(poolShown({ ...pool(2, 0), worktrees: slots }, 'working')).toBe(true)
        expect(poolShown({ ...pool(2, 0), worktrees: slots }, 'held')).toBe(false)
    })

    it('shows a pool treehouse could not read under broken alone', () => {
        const unread = { ...pool(2, 0), error: 'treehouse status failed' }
        expect(poolShown(unread, 'broken')).toBe(true)
        expect(poolShown(unread, 'idle')).toBe(false)
    })
})

// A slot in `state`, held by `holder` when it has one.
function inState(state: WorktreeState, holder: string | null = null): Pool['worktrees'][number] {
    return { ...at('1', '.treehouse/web-3f9c2a1b/1/web'), state, holder }
}

describe('poolsLine', () => {
    const now = Date.parse('2026-10-08T12:00:04Z')

    it('counts the pools and their slots, and says how long ago they were read', () => {
        const pools = [pool(4, 5), pool(2, 2), { ...pool(2, 0), error: 'no clone' }]
        expect(poolsLine(pools, Date.parse('2026-10-08T12:00:00Z'), now)).toBe('3 pools · 7 slots · read 4s ago')
        expect(poolsLine([pool(1, 1)], now, now)).toBe('1 pool · 1 slot · read 0s ago')
        expect(poolsLine([], now, now)).toBe('no pools · no slots · read 0s ago')
    })
})

describe('needsLook', () => {
    it('counts dirty and broken slots and unread pools, and names only the parts there are', () => {
        const web = { ...pool(4, 0), worktrees: [inState('working'), inState('dirty'), inState('idle')] }
        const unread = { ...pool(2, 0), error: 'no clone' }
        expect(needsLook([web, unread])).toEqual({ count: 2, text: '1 dirty · 1 pool unread' })
        const broken = { ...pool(2, 0), worktrees: [inState('broken'), inState('broken')] }
        expect(needsLook([broken, unread, unread])).toEqual({ count: 4, text: '2 broken · 2 pools unread' })
    })

    it('says nothing needs a look when nothing does', () => {
        expect(needsLook([pool(2, 2)])).toEqual({ count: 0, text: 'nothing' })
    })
})

describe('heldBy', () => {
    it('names what holds the held slots, most first, a slot with no lease in use', () => {
        const slots = [
            inState('held'),
            inState('working', 'canopy:ABC-101'),
            inState('held', 'canopy-sync'),
            inState('held', 'canopy-sync'),
            inState('dirty'),
        ]
        expect(heldBy(slots)).toBe('2 canopy-sync · 1 in use')
        expect(heldBy([inState('held'), inState('held', 'canopy-sync')])).toBe('1 in use · 1 canopy-sync')
    })

    it('says nothing holds one when none is held', () => {
        expect(heldBy([inState('idle'), inState('working', 'canopy:ABC-101')])).toBe('nothing')
    })
})
