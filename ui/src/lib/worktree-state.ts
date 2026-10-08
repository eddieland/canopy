import type { WorktreeState } from '@/api/types'

// Full class names, written out, so Tailwind finds them. One entry per state; the types make a missing one an error.
// An idle slot is a hollow ring: nothing holds it, and no status color claims it.

export const WORKTREE_DOT: Record<WorktreeState, string> = {
    working: 'bg-status-running',
    held: 'bg-status-stopped',
    dirty: 'bg-status-blocked',
    idle: 'border border-muted-foreground',
    broken: 'bg-status-failed',
}

export const WORKTREE_TEXT: Record<WorktreeState, string> = {
    working: 'text-status-running',
    held: 'text-status-stopped',
    dirty: 'text-status-blocked',
    idle: 'text-muted-foreground',
    broken: 'text-status-failed',
}
