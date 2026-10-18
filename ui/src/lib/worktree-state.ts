import type { Pool, Worktree, WorktreeState } from '@/api/types'
import { counted } from '@/lib/descriptions'
import { age } from '@/lib/time'

// Full class names, written out, so Tailwind finds them. One entry per state; the types make a missing one an error.
// An idle slot is a hollow ring: nothing holds it, and no status color claims it.

/** Each worktree state's dot: its status color as a fill, or a hollow ring when idle. */
export const WORKTREE_DOT: Record<WorktreeState, string> = {
    working: 'bg-status-running',
    held: 'bg-status-stopped',
    dirty: 'bg-status-blocked',
    idle: 'border border-muted-foreground',
    broken: 'bg-status-failed',
}

/** Each worktree state's text color. */
export const WORKTREE_TEXT: Record<WorktreeState, string> = {
    working: 'text-status-running',
    held: 'text-status-stopped',
    dirty: 'text-status-blocked',
    idle: 'text-muted-foreground',
    broken: 'text-status-failed',
}

/**
 * The worktrees page's description, its state: how many pools and slots, and how long ago the pools were read, as
 * `3 pools · 7 slots · read 4s ago`. `readAt` is when, in milliseconds.
 */
export function poolsLine(pools: readonly Pool[], readAt: number, now: number): string {
    const slots = pools.reduce((n, p) => n + p.worktrees.length, 0)
    const read = `read ${age(new Date(readAt).toISOString(), now)} ago`
    return [counted(pools.length, 'pool'), counted(slots, 'slot'), read].join(' · ')
}

/** What the Needs a look counter counts, and its line. */
export interface NeedsLook {
    /** Dirty slots, broken slots, and pools that could not be read, together. */
    count: number
    /** Its parts in words, each only when there is one, as `1 dirty · 1 pool unread`, or `nothing`. */
    text: string
}

/**
 * Every slot and pool that needs a look: a dirty slot, which the pool never reuses and counts as busy; a broken one;
 * and a pool that could not be read, whose slots nobody knows.
 */
export function needsLook(pools: readonly Pool[]): NeedsLook {
    const slots = pools.flatMap((p) => p.worktrees)
    const dirty = slots.filter((w) => w.state === 'dirty').length
    const broken = slots.filter((w) => w.state === 'broken').length
    const unread = pools.filter((p) => p.error !== null).length
    const parts = [
        [dirty, 'dirty'],
        [broken, 'broken'],
        [unread, unread === 1 ? 'pool unread' : 'pools unread'],
    ] as const
    return { count: dirty + broken + unread, text: joined(parts) }
}

/**
 * What holds the held slots, most first: each lease's holder as the pool names it, and `in use` for a slot with no
 * lease but a process in it, as `1 in use · 1 canopy-sync`, or `nothing`.
 */
export function heldBy(slots: readonly Worktree[]): string {
    const counts = new Map<string, number>()
    for (const w of slots) {
        if (w.state === 'held') {
            const holder = w.holder ?? 'in use'
            counts.set(holder, (counts.get(holder) ?? 0) + 1)
        }
    }
    // A stable sort: holders of as many slots keep the order of their first slot.
    return joined([...counts].map(([holder, n]) => [n, holder] as const).toSorted(([a], [b]) => b - a))
}

/**
 * How many slots a pool holds past the size `capacity` declares for it, 0 when it has none declared or is within it.
 * `canopy workspace sync` removes idle ones; a slot with work in it stays until it has none (DESIGN §18).
 */
export function overSize(pool: Pool): number {
    return pool.size === null ? 0 : Math.max(0, pool.worktrees.length - pool.size)
}

/**
 * Where a pool's slots live, when every slot's path is the same but for its own directory: shown once, in the pool's
 * header, instead of on every row. Null when they differ, and each row shows its own.
 */
export function slotsRoot(worktrees: Worktree[]): string | null {
    const roots = new Set(
        worktrees.map((w) => {
            const at = w.path.lastIndexOf(`/${w.name}/`)
            return at < 0 ? null : w.path.slice(0, at)
        }),
    )
    const [root] = roots
    return roots.size === 1 && root !== null && root !== undefined ? root : null
}

/** The fewest idle slots in a row that fold into one line on the worktrees page: two show as they are. */
export const IDLE_RUN = 3

/** A pool's slots as the worktrees page lists them: a slot on its own line, or a run of idle ones folded into one. */
export type SlotGroup = { kind: 'slot'; worktree: Worktree } | { kind: 'idle'; worktrees: Worktree[] }

/**
 * A pool's slots in slot order, each run of `IDLE_RUN` or more idle slots in a row folded into one group. A pool of
 * many slots is mostly idle ones, which say nothing but their number: folded, the slots with work in them stay in
 * reach. With a `state`, only the groups in it: idle ones are folded as they lie in the whole pool, so a group never
 * spans a slot in another state.
 */
export function slotGroups(worktrees: readonly Worktree[], state?: WorktreeState): SlotGroup[] {
    const groups = folded(worktrees)
    if (state === undefined) {
        return groups
    }
    return groups.filter((g) => (g.kind === 'idle' ? state === 'idle' : g.worktree.state === state))
}

/**
 * Whether a pool shows under the worktrees page's filter by `state`: with no filter, every pool; with one, a pool with
 * a slot in that state, or under `broken` one that could not be read, which the Needs a look counter counts too.
 */
export function poolShown(pool: Pool, state: WorktreeState | undefined): boolean {
    if (state === undefined) {
        return true
    }
    return pool.worktrees.some((w) => w.state === state) || (state === 'broken' && pool.error !== null)
}

function joined(parts: readonly (readonly [number, string])[]): string {
    const shown = parts.filter(([n]) => n > 0)
    return shown.length === 0 ? 'nothing' : shown.map(([n, label]) => `${n} ${label}`).join(' · ')
}

function folded(worktrees: readonly Worktree[]): SlotGroup[] {
    const groups: SlotGroup[] = []
    let idle: Worktree[] = []
    const flush = () => {
        if (idle.length >= IDLE_RUN) {
            groups.push({ kind: 'idle', worktrees: idle })
        } else {
            groups.push(...idle.map((worktree) => ({ kind: 'slot', worktree }) as const))
        }
        idle = []
    }
    for (const worktree of worktrees) {
        if (worktree.state === 'idle') {
            idle.push(worktree)
            continue
        }
        flush()
        groups.push({ kind: 'slot', worktree })
    }
    flush()
    return groups
}
