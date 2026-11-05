import type { EpicStanding, EpicSummary, RunState } from '@/api/types'

/** Where an epic stands as the epics list shows it: the run state it is colored as, its word, and what it means. */
export interface EpicLook {
    /** The run state whose dot and color it wears. */
    state: RunState
    /** What the row says, in the operator's words. */
    word: string
    /** What it means, in a line: its word's tip says it under the CLI's spelling. */
    meaning: string
}

/**
 * Each standing's look, written out so a new standing fails the type check until it has one, mapped to a run state
 * by what it means, as a task's are (`TASK_LOOK`): a queued epic waits on a tick, not on the operator, so it is muted;
 * its plan run working is `running`; a proposed plan waits on the operator, `waiting on you` in the blocked color, as
 * a ticket's plan does; an approved one is settled, `done`'s color; and an epic whose plan runs ended without a plan is
 * stuck until the operator replies, in `failed`'s, as a run that left no result is.
 */
export const EPIC_LOOK: Record<EpicStanding, EpicLook> = {
    queued: { state: 'stopped', word: 'queued', meaning: 'The next tick starts its plan run.' },
    planning: { state: 'running', word: 'planning', meaning: 'Its plan run is working.' },
    proposed: {
        state: 'blocked',
        word: 'waiting on you',
        meaning: 'Its plan waits on you: approve it, or reply with what to change.',
    },
    approved: {
        state: 'done',
        word: 'approved',
        meaning: 'You approved its plan: file its tickets and add them as members.',
    },
    unplanned: {
        state: 'failed',
        word: 'unplanned',
        meaning: 'Its plan runs ended without a plan: a reply starts another, until policy.max_plan_attempts is used.',
    },
}

/** An epic's name in a list: the first line of its goal that holds anything, or the goal whole. */
export function epicTitle(text: string): string {
    return (
        text
            .split('\n')
            .map((line) => line.trim())
            .find((line) => line !== '') ?? text
    )
}

/**
 * How much of an epic's breakdown has members, as its row reads it: `2 of 4 entries filed`. With no breakdown to count,
 * an epic whose plan is proposed or approved has one canopy cannot read (its ids repeat or will not parse), and says
 * `breakdown unreadable`; any other has no plan yet, `no breakdown`.
 */
export function entriesFiled(epic: Pick<EpicSummary, 'entries' | 'entries_with_members' | 'standing'>): string {
    if (epic.entries === null) {
        return epic.standing === 'proposed' || epic.standing === 'approved' ? 'breakdown unreadable' : 'no breakdown'
    }
    const noun = epic.entries === 1 ? 'entry' : 'entries'
    return `${String(epic.entries_with_members)} of ${String(epic.entries)} ${noun} filed`
}
