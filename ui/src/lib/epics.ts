import type { EpicEntry, EpicMember, EpicStanding, EpicSummary, RunState } from '@/api/types'

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
 * an epic whose plan is proposed or approved has one canopy cannot read (its file, or its ids), and says
 * `breakdown unreadable`; any other has no plan yet, `no breakdown`.
 */
export function entriesFiled(epic: Pick<EpicSummary, 'entries' | 'entries_with_members' | 'standing'>): string {
    if (epic.entries === null) {
        return epic.standing === 'proposed' || epic.standing === 'approved' ? 'breakdown unreadable' : 'no breakdown'
    }
    const noun = epic.entries === 1 ? 'entry' : 'entries'
    return `${String(epic.entries_with_members)} of ${String(epic.entries)} ${noun} filed`
}

// An epic's id as its page's path holds it: a whole number, as `canopy show epic:N` reads one.
const EPIC_ID = /^[1-9]\d*$/u

/**
 * The epic a page's path names, or undefined for anything that is not a whole number, which names no epic, and for one
 * past what a number here holds exactly, which would read as another epic's id.
 */
export function epicId(text: string): number | undefined {
    const id = EPIC_ID.test(text) ? Number(text) : undefined
    return id !== undefined && Number.isSafeInteger(id) ? id : undefined
}

/** Whether `entry` cites `id`: covers it (an `R`), provides or uses it (a `C`), or is it or comes after it (a `B`). */
export function cites(entry: Pick<EpicEntry, 'id' | 'covers' | 'provides' | 'uses' | 'after'>, id: string): boolean {
    return (
        entry.id === id ||
        entry.covers.includes(id) ||
        entry.provides.includes(id) ||
        entry.uses.includes(id) ||
        entry.after.includes(id)
    )
}

/**
 * Who in the breakdown cites an id, in words, read the other way from the board: the entries that cover a requirement,
 * that provide and use a contract, or that come after an entry. An id no entry cites says so, since a requirement no
 * entry covers is a gap in the plan.
 */
export function citedBy(entries: readonly EpicEntry[], id: string): string {
    const ids = (pick: (entry: EpicEntry) => readonly string[]) =>
        entries.filter((entry) => pick(entry).includes(id)).map((entry) => entry.id)
    if (id.startsWith('R')) {
        return `covered by ${named(ids((entry) => entry.covers))}`
    }
    if (id.startsWith('C')) {
        return `provided by ${named(ids((entry) => entry.provides))} · used by ${named(ids((entry) => entry.uses))}`
    }
    const after = ids((entry) => entry.after)
    if (after.length === 0) {
        return 'nothing comes after it'
    }
    return `${after.join(', ')} ${after.length === 1 ? 'comes' : 'come'} after it`
}

/** Entries' ids as a list in words, or `no entry`. */
function named(ids: readonly string[]): string {
    return ids.length === 0 ? 'no entry' : ids.join(', ')
}

/**
 * The members the board has no row for: those of no entry, those registered against entries since dropped, and, while
 * the board has no rows to place them on, those registered against its entries.
 */
export interface Unplaced {
    /** The members registered against no entry: tickets the breakdown did not foresee. */
    none: EpicMember[]
    /** The members registered against an entry the approved plan no longer holds, whatever else they fulfil. */
    dropped: EpicMember[]
    /** The members registered against entries the board cannot show, with no plan it can read; else none. */
    registered: EpicMember[]
}

/**
 * The members the breakdown does not place, as the board lists them under it: a member of no entry is one with neither
 * an entry nor a dropped one; a member with a dropped entry is listed for it, whether or not it fulfils others. While
 * the board has no rows (`rows` false: no plan yet, or one that does not read), a member registered against entries is
 * listed too, so no member goes missing from the page.
 */
export function unplaced(members: readonly EpicMember[], rows = true): Unplaced {
    return {
        none: members.filter((member) => member.entries.length === 0 && member.dropped.length === 0),
        dropped: members.filter((member) => member.dropped.length > 0),
        registered: rows ? [] : members.filter((member) => member.entries.length > 0),
    }
}
