import type { TicketSummary } from '@/api/types'

/**
 * The tickets page's board (`?view=board`, DESIGN.md, the tickets board): a column for each stage on a ticket's way
 * to merged, left to right, and each ticket in the one column of the stage it is at. The stage is read from where the
 * ticket stands: done, a run working it now, else the phase the overseer last recorded (DESIGN §7), which is for
 * display, as the board is.
 */

/** The board's columns, left to right, in the order a ticket moves through them. */
export const BOARD_COLUMNS = ['todo', 'plan', 'working', 'ci', 'review', 'approved', 'done'] as const

/** One of `BOARD_COLUMNS`. */
export type BoardColumn = (typeof BOARD_COLUMNS)[number]

/** Each column's name in its header. */
export const BOARD_COLUMN_LABEL: Record<BoardColumn, string> = {
    todo: 'to do',
    plan: 'plan',
    working: 'working',
    ci: 'CI',
    review: 'review',
    approved: 'approved',
    done: 'done',
}

/** What each column holds, on its header's hover, in the phases' CLI spelling. */
export const BOARD_COLUMN_HELP: Record<BoardColumn, string> = {
    todo: 'Not started, or waiting to be: ready, blocked, needs_human, human_replied, or not seen by a tick yet',
    plan: 'A plan waits on your approval: plan_proposed',
    working: 'A run is on it now, or its branch is pushed with no PR yet: running, pushed_no_pr',
    ci: 'Its PR waits on its checks or its base: ci_running, ci_red, conflicted',
    review:
        'Its PR waits on a review or on fixes for one: review_pending, review_findings, changes_requested, ' +
        'untrusted_review, green_unreviewed',
    approved: 'Approved, waiting for you to merge: approved',
    done: 'Merged or marked done',
}

/** How many tickets the done column shows, the most recent; the rest are a link to the done list. */
export const DONE_SHOWN = 8

/** The tickets of each column, in the order they were given. */
export type Board = Record<BoardColumn, TicketSummary[]>

/** The tickets on the board, each in its column (`boardColumn`), in the order given. */
export function boardOf(tickets: Iterable<TicketSummary>): Board {
    const board: Board = { todo: [], plan: [], working: [], ci: [], review: [], approved: [], done: [] }
    for (const ticket of tickets) {
        board[boardColumn(ticket)].push(ticket)
    }
    return board
}

/**
 * The column a ticket stands in: `done` once done, `working` while a run is on it, whatever the phase it was in when
 * the run started, else its phase's column. A phase the board does not know, or none, is `todo`, so every ticket has a
 * column.
 */
export function boardColumn(ticket: Pick<TicketSummary, 'done' | 'running_run' | 'phase'>): BoardColumn {
    if (ticket.done) {
        return 'done'
    }
    if (ticket.running_run !== null) {
        return 'working'
    }
    return (ticket.phase === null ? undefined : PHASE_COLUMN[ticket.phase]) ?? 'todo'
}

// The phase table's phases (DESIGN §7, `Phase` in canopy/core/vocab.py), each in the stage it is at. `merged` is done
// before the overseer marks the ticket so; `split` is retired and reads as not started.
const PHASE_COLUMN: Readonly<Record<string, BoardColumn>> = {
    ready: 'todo',
    blocked: 'todo',
    needs_human: 'todo',
    human_replied: 'todo',
    split: 'todo',
    plan_proposed: 'plan',
    running: 'working',
    pushed_no_pr: 'working',
    conflicted: 'ci',
    ci_running: 'ci',
    ci_red: 'ci',
    review_pending: 'review',
    review_findings: 'review',
    changes_requested: 'review',
    untrusted_review: 'review',
    green_unreviewed: 'review',
    approved: 'approved',
    merged: 'done',
}
