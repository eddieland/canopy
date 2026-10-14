/** The free column: whatever width the fixed ones leave, and never less than nothing, so its text is cut to fit. */
const FREE = 'minmax(0,1fr)'

/**
 * Every list's columns, by kind, each a named grid line and a width. Every column but one is fixed, so each row of a
 * list lines up with the others whatever its cells hold; the free one takes the rest. What goes under a row's head
 * line starts at a named column (`RowLine`), never at a hand-computed indent.
 */
export const ROW_COLUMNS = {
    /** A run with its ticket, on the runs page: the state, the ticket and its title, the run's id and chips. */
    run: [
        ['state', '5rem'],
        ['key', '6rem'],
        ['title', FREE],
        ['facts', '14rem'],
        ['cost', '4rem'],
        ['age', '6rem'],
    ],
    /** A run under its subject (a ticket's, a PR's, a chore's): the state, then the run's id and chips. */
    'own-run': [
        ['state', '5rem'],
        ['facts', FREE],
        ['cost', '4rem'],
        ['age', '6rem'],
    ],
    /** A tick: its id, its status, how many decisions, its cost, and when. */
    tick: [
        ['id', '5rem'],
        ['state', FREE],
        ['decisions', '6rem'],
        ['cost', '4rem'],
        ['age', '6rem'],
    ],
    /** A chore: its name, its line in `canopy status`'s words, and its open findings. */
    chore: [
        ['name', '10rem'],
        ['state', FREE],
        ['findings', '8rem'],
    ],
    /** A review run on the reviews page: its id, verdict, ticket, PR and commit, impact, cost, and when. */
    review: [
        ['id', '5rem'],
        ['verdict', '7rem'],
        ['key', '6rem'],
        ['pr', FREE],
        ['impact', '7rem'],
        ['cost', '3.5rem'],
        ['age', '6rem'],
    ],
    /** A review run on its PR's page: as on the reviews page, without the ticket and the PR. */
    'own-review': [
        ['id', '5rem'],
        ['verdict', '7rem'],
        ['commit', FREE],
        ['impact', '7rem'],
        ['cost', '3.5rem'],
        ['age', '6rem'],
    ],
    /** A PR: the PR, its ticket and title and phase, the run working it, its latest review, and its age. */
    'pull-request': [
        ['pr', '16rem'],
        ['key', FREE],
        ['run', '5rem'],
        ['review', '11rem'],
        ['age', '5rem'],
    ],
    /** A ticket: its key, its title, public or private, its phase, its run or `waiting on you`, and its age. */
    ticket: [
        ['key', '6rem'],
        ['title', FREE],
        ['access', '9rem'],
        ['phase', '10rem'],
        ['run', '8rem'],
        ['age', '4rem'],
    ],
    /** A worktree slot: its state, its number, what holds it, its branch and processes, and for how long. */
    worktree: [
        ['state', '5rem'],
        ['slot', '3.5rem'],
        ['holder', '13rem'],
        ['branch', FREE],
        ['age', '5rem'],
    ],
    /** A decision in a tick: its subject, then its action and PR. */
    decision: [
        ['subject', '9rem'],
        ['action', FREE],
    ],
    /** A decision on its subject's page: the tick that made it, its action and PR, and its age. */
    'own-decision': [
        ['id', '4rem'],
        ['action', FREE],
        ['age', '4rem'],
    ],
    /** A chore's finding: its id, its title, and what it says of itself at the end. Ids differ in length. */
    finding: [
        ['id', 'auto'],
        ['title', FREE],
        ['facts', 'auto'],
    ],
    /** A review's finding in its list: its number, its severity, its title, and where it sits. */
    'review-finding': [
        ['id', '1rem'],
        ['severity', '4rem'],
        ['title', FREE],
        ['facts', 'auto'],
    ],
    /** A search hit: where it opens, its label, the snippet, and its age. */
    'search-hit': [
        ['subject', '9rem'],
        ['label', '8rem'],
        ['text', FREE],
        ['age', '5rem'],
    ],
    /** A transcript's row: its time, its mark, and its text, under which a tool call's body opens. */
    transcript: [
        ['time', '3.5rem'],
        ['mark', '0.5rem'],
        ['text', FREE],
    ],
} as const satisfies Record<string, readonly (readonly [string, string])[]>

/** A kind of list, by the columns its rows share. */
export type RowKind = keyof typeof ROW_COLUMNS

/** A column a line under a row's head can start at: any list's. */
export type RowColumn = (typeof ROW_COLUMNS)[RowKind][number][0]

/** A kind's `grid-template-columns`: each column's name before its width, and `end` after the last. */
export function rowTemplate(kind: RowKind): string {
    return [...ROW_COLUMNS[kind].map(([name, width]) => `[${name}] ${width}`), '[end]'].join(' ')
}

// Written out so Tailwind finds them: from the column's line to the row's end.
const FROM: Record<RowColumn, string> = {
    access: 'col-[access/end]',
    action: 'col-[action/end]',
    age: 'col-[age/end]',
    branch: 'col-[branch/end]',
    commit: 'col-[commit/end]',
    cost: 'col-[cost/end]',
    decisions: 'col-[decisions/end]',
    facts: 'col-[facts/end]',
    findings: 'col-[findings/end]',
    holder: 'col-[holder/end]',
    id: 'col-[id/end]',
    impact: 'col-[impact/end]',
    key: 'col-[key/end]',
    label: 'col-[label/end]',
    mark: 'col-[mark/end]',
    name: 'col-[name/end]',
    phase: 'col-[phase/end]',
    pr: 'col-[pr/end]',
    review: 'col-[review/end]',
    run: 'col-[run/end]',
    severity: 'col-[severity/end]',
    slot: 'col-[slot/end]',
    state: 'col-[state/end]',
    subject: 'col-[subject/end]',
    text: 'col-[text/end]',
    time: 'col-[time/end]',
    title: 'col-[title/end]',
    verdict: 'col-[verdict/end]',
}

/** The classes that place any element as a `RowLine` is placed, for one that is not a `div` (a nested list). */
export function rowLineFrom(from: RowColumn): string {
    return FROM[from]
}
