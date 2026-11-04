import { createContext, use } from 'react'

import type { RunWorktree } from '@/api/types'

// What a transcript is read against outside a run's page: no worktrees, so every directory stays whole.
const NONE: readonly RunWorktree[] = []

/**
 * The worktrees of the run whose transcript a `TranscriptPanel` shows, set by the panel for the rows under it. A
 * tick's, a chore run's, a review's, and a task run's transcripts leave it empty.
 */
export const RunWorktreesContext = createContext<readonly RunWorktree[]>(NONE)

/** The worktrees a shell call's directory is read against (`summary`): the run's, or none outside a run's page. */
export function useRunWorktrees(): readonly RunWorktree[] {
    return use(RunWorktreesContext)
}
