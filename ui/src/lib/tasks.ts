import type { RunState, TaskRun, TaskStanding, TaskSummary } from '@/api/types'
import { taskRef } from '@/lib/refs'
import { inRepos } from '@/lib/repo-filter'

/** Where a task stands as the tasks list shows it: the run state it is colored as, and the word it reads. */
export interface TaskLook {
    /** The run state whose dot and color it wears. */
    state: RunState
    /** What the row says, in the operator's words. */
    word: string
}

/**
 * Each standing's look, written out so a new standing fails the type check until it has one. A task waiting on the
 * operator's reply reads `waiting on you` in the blocked color, as a ticket's question does; a queued one waits on a
 * tick, not on the operator, so it is muted, as an open ticket is; every ending a human must look at is `failed`'s
 * color, in its own word.
 */
export const TASK_LOOK: Record<TaskStanding, TaskLook> = {
    queued: { state: 'stopped', word: 'queued' },
    running: { state: 'running', word: 'running' },
    awaiting_reply: { state: 'blocked', word: 'waiting on you' },
    blocked: { state: 'blocked', word: 'blocked' },
    done: { state: 'done', word: 'done' },
    failed: { state: 'failed', word: 'failed' },
    unknown: { state: 'failed', word: 'unknown' },
    unpushed: { state: 'failed', word: 'unpushed' },
    crashed: { state: 'failed', word: 'crashed' },
    timeout: { state: 'failed', word: 'timeout' },
    stopped: { state: 'stopped', word: 'stopped' },
}

/** A task's name in a list: the first line of the operator's text that holds anything, or the text whole. */
export function taskTitle(text: string): string {
    return (
        text
            .split('\n')
            .map((line) => line.trim())
            .find((line) => line !== '') ?? text
    )
}

/**
 * The tasks the list shows, in its order: those in a repository `repo` chooses (every one while it is undefined), the
 * ones waiting on the operator's reply first, then the rest as the server sends them, the newest first. The sort is
 * stable, so the waiting ones keep that order among themselves too.
 */
export function tasksShown(tasks: readonly TaskSummary[], repo: string | undefined): TaskSummary[] {
    return tasks.filter((task) => inRepos(task.repo, repo)).toSorted((a, b) => Number(waits(b)) - Number(waits(a)))
}

/** Whether a task waits on the operator: its latest run asked a question no reply has followed. */
export function waits(task: Pick<TaskSummary, 'standing'>): boolean {
    return task.standing === 'awaiting_reply'
}

/** The run whose report a task's page shows: its newest that left one, as `canopy show task:N` prints it. */
export function reportRun(runs: readonly TaskRun[]): TaskRun | undefined {
    return runs.findLast((run) => run.reported)
}

/** Why a task's page has no report to show, as one `Empty` clause: what comes next, or that no run left one. */
export function noReport(task: Pick<TaskSummary, 'standing'>, runs: readonly TaskRun[]): string {
    if (runs.length === 0) {
        return task.standing === 'stopped'
            ? 'no report: it was stopped before its first run'
            : 'no report yet: the next tick starts its first run'
    }
    if (runs.at(-1)?.status === 'running') {
        return 'no report yet: its run is working'
    }
    return runs.length === 1 ? 'no report: its run left none' : 'no report: none of its runs left one'
}

/** The PRs a task's runs named, each once, in the order they first named them. */
export function taskPrs(runs: readonly TaskRun[]): string[] {
    return [...new Set(runs.flatMap((run) => run.prs))]
}

/** The command that answers a task from the shell, until the page has a reply box: `canopy reply task:4`. */
export function replyCommand(id: number): string {
    return `canopy reply ${taskRef(id)}`
}
