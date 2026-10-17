import type { CSSProperties } from 'react'

/** The narrowest the free column gets, in rem: it holds a row's name, which never vanishes. */
const FLOOR_REM = 8

/** The free column: whatever width the fixed ones leave, never under the floor, and its text cut to fit. */
const FREE = `minmax(${FLOOR_REM}rem,1fr)`

/**
 * The container sizes a column can show from (Tailwind's, in rem), narrowest first. A list's width picks one, so a row
 * fits the panel it is in, wherever the panel sits: half a monitor, beside a ticket's thread.
 */
export const ROW_TIERS = [
    ['sm', 24],
    ['md', 28],
    ['lg', 32],
    ['xl', 36],
    ['2xl', 42],
    ['3xl', 48],
    ['4xl', 56],
] as const

/** A container size a column shows from. */
export type RowTier = (typeof ROW_TIERS)[number][0]

/** Every list's age column: room for the longest an age reads, `ended 12h ago`, so ages line up from list to list. */
const AGE = '6rem'

/** Every list's cost column: room for `$12.34`, so costs line up from list to list. */
const COST = '4rem'

/** The room a column needs, in rem, to show at any width, under the first tier as well. */
const BASE_REM = 22

// A row's own room beside its columns: the gap between two (`gap-x-3`) and its padding (`px-3`).
const GAP_REM = 0.75
const PADDING_REM = 1.5

/**
 * Every list's columns, by kind, each a named grid line and a width. Every column but one is fixed, so each row of a
 * list lines up with the others whatever its cells hold; the free one takes the rest, and never less than the floor.
 * What goes under a row's head line starts at a named column (`RowLine`), never at a hand-computed indent.
 *
 * A row reads in one order in every kind (`ui/DESIGN.md`, "Lists are rows in a panel"): its state, where it has one,
 * so the left edge of a list is a column of dots; its own id; what it belongs to; the chips that describe it; the
 * free column; then only readouts, right-aligned, age last.
 *
 * A column with a third entry gives way on a narrow list, in that order: 1 goes first. It shows only where the list
 * has room for it, every column that gives way after it, and the ones that never do (`rowTiers`).
 */
export const ROW_COLUMNS = {
    /** A run with its ticket, on the runs page: the state, the run's id, the ticket, the run's chips, the title. */
    run: [
        ['state', '5rem'],
        ['run', '4rem', 4],
        ['key', '6rem'],
        // Its chips go before its age: they describe the run, where the age says whether it is current.
        ['kind', '10rem', 2],
        ['title', FREE],
        ['cost', COST, 1],
        ['age', AGE, 3],
    ],
    /**
     * A run under its subject (a ticket's, a PR's, a chore's): the state, then the run's id at a fixed width and its
     * chips, the order a run's row has on the runs page.
     */
    'own-run': [
        ['state', '5rem'],
        ['facts', FREE],
        ['cost', COST, 1],
        ['age', AGE, 2],
    ],
    /**
     * A tick: its status, its id, a dry run's chip, how many decisions, its overseer's cost, tokens, and peak context,
     * and when. The token counts give way before the cost, which says the same in dollars.
     */
    tick: [
        // A long status (`overseer failed`) is cut to fit: a wider column would leave the free one under its floor.
        ['state', '6rem'],
        ['id', '5rem'],
        ['facts', FREE],
        ['decisions', '6rem', 4],
        ['cost', COST, 3],
        ['tokens', '6rem', 1],
        ['peak', '5rem', 2],
        ['age', AGE, 5],
    ],
    /**
     * A chore: its name, its line in `canopy status`'s words, and its open findings, whose column holds
     * `12 open findings · 10 dismissed` on one line.
     */
    chore: [
        ['name', '10rem'],
        ['state', FREE],
        ['findings', '14rem', 1],
    ],
    /** A review run on the reviews page: its verdict, id, ticket, impact, PR and commit, cost, and when. */
    review: [
        // `3 findings, 1 blocking` on one line, with its dot.
        ['verdict', '12rem', 5],
        ['id', '5rem'],
        ['key', '6rem', 3],
        ['impact', '7rem', 2],
        ['pr', FREE],
        ['cost', COST, 1],
        ['age', AGE, 4],
    ],
    /** A review run on its PR's page: as on the reviews page, without the ticket and the PR. */
    'own-review': [
        ['verdict', '12rem', 4],
        ['id', '5rem'],
        ['impact', '7rem', 2],
        ['commit', FREE],
        ['cost', COST, 1],
        ['age', AGE, 3],
    ],
    /**
     * A PR: its state (the run working it, else its latest review), the PR, its unit's phase, its ticket and title, and
     * its age. The ticket shares the free column with its title: a column of its own beside the review's would not fit
     * a list in a 1280px window.
     */
    'pull-request': [
        // `review:4 3 findings, 1 blocking` on one line, with its dot.
        ['state', '16rem', 3],
        ['pr', '11rem'],
        // Room for the longest phase's chip, `changes requested`.
        ['phase', '9rem', 1],
        ['title', FREE],
        ['age', AGE, 2],
    ],
    /**
     * A ticket: where it stands (its run, `waiting on you`, `done`, or `open`), its key, its phase, public or private,
     * its title, and its age.
     */
    ticket: [
        ['run', '8rem', 4],
        ['key', '6rem'],
        ['phase', '10rem', 2],
        ['access', '9rem', 1],
        ['title', FREE],
        ['age', AGE, 3],
    ],
    /** A worktree slot: its state, its number, what holds it, its branch and processes, and for how long. */
    worktree: [
        ['state', '5rem'],
        ['slot', '3.5rem'],
        ['holder', '13rem', 2],
        ['branch', FREE],
        ['age', AGE, 1],
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
        ['age', AGE],
    ],
    /**
     * A chore's finding: its id, its title, and what it says of itself at the end. Ids differ in length: a short one
     * takes its own width, and a long one (up to 200 characters) wraps rather than squeeze the title to its floor.
     */
    finding: [
        ['id', 'fit-content(12rem)'],
        ['title', FREE],
        ['facts', 'auto'],
    ],
    /** A review's finding in its list: its number and its box to send it, its severity, its title, and where it is. */
    'review-finding': [
        ['id', '2.5rem'],
        ['severity', '4rem'],
        ['title', FREE],
        ['facts', 'auto'],
    ],
    /** A search hit: where it opens, its label, the snippet, and its age. */
    'search-hit': [
        ['subject', '9rem'],
        ['label', '8rem', 2],
        ['text', FREE],
        ['age', AGE, 1],
    ],
    /**
     * A note, proposal, or lesson (DESIGN §28): where it stands, its id, its key, how runs used it, and when it was
     * written. What it says goes under its key.
     */
    memory: [
        ['state', '6rem'],
        ['id', '5rem'],
        ['key', FREE],
        ['use', '11rem', 1],
        ['age', AGE, 2],
    ],
    /** A transcript's row: its time, its mark, and its text, under which a tool call's body opens. */
    transcript: [
        ['time', '3.5rem'],
        ['mark', '0.5rem'],
        ['text', FREE],
    ],
} as const satisfies Record<string, readonly (readonly [string, string] | readonly [string, string, number])[]>

/** A kind of list, by the columns its rows share. */
export type RowKind = keyof typeof ROW_COLUMNS

/** A column a line under a row's head can start at: any list's. */
export type RowColumn = (typeof ROW_COLUMNS)[RowKind][number][0]

/**
 * A kind's `grid-template-columns` on a list at least `tier` wide, or under the first tier when there is none: each
 * column it shows, its name before its width, and `end` after the last. A column it leaves out lends its name to the
 * next one shown, so a line under the row that starts there still has a place.
 */
export function rowTemplate(kind: RowKind, tier?: RowTier): string {
    const tiers = rowTiers(kind)
    const parts: string[] = []
    let names: string[] = []
    for (const [name, width] of ROW_COLUMNS[kind]) {
        names.push(name)
        if (shownAt(tiers.get(name), tier)) {
            parts.push(`[${names.join(' ')}] ${width}`)
            names = []
        }
    }
    parts.push(`[${[...names, 'end'].join(' ')}]`)
    return parts.join(' ')
}

/**
 * The tier from which each column that gives way shows: the narrowest with room for it, every column that gives way
 * after it, and those that never do, at their least width. A column with room for it under the first tier is not in
 * the map: it shows at any width, as a column that never gives way does.
 *
 * @throws {Error} When a column needs more room than the widest tier, or the kind's widths cannot be summed.
 */
export function rowTiers(kind: RowKind): Map<string, RowTier> {
    const columns: readonly (readonly [string, string, number?])[] = ROW_COLUMNS[kind]
    const tiers = new Map<string, RowTier>()
    for (const [name, , order] of columns) {
        if (order === undefined) {
            continue
        }
        const kept = columns.filter(([, , other]) => other === undefined || other >= order)
        const need = kept.reduce((sum, [, width]) => sum + leastRem(width), PADDING_REM + GAP_REM * (kept.length - 1))
        if (need <= BASE_REM) {
            continue
        }
        const tier = ROW_TIERS.find(([, rem]) => rem >= need)
        if (tier === undefined) {
            throw new Error(`${kind}'s ${name} column needs ${need}rem, more than any tier`)
        }
        tiers.set(name, tier[0])
    }
    return tiers
}

/**
 * What lays a row of `kind` out: its columns' template at each tier, as custom properties, and the classes that pick
 * one by the width of the list it is in (the nearest `@container`, a `Panel`) and hide the cells of the columns it
 * leaves out. The classes are built here, so `index.css` lists them for Tailwind (`@source inline`).
 */
export function rowLayout(kind: RowKind): { className: string; style: CSSProperties } {
    const tiers = rowTiers(kind)
    const used = ROW_TIERS.filter(([tier]) => [...tiers.values()].includes(tier)).map(([tier]) => tier)
    const style: Record<string, string> = { '--row': rowTemplate(kind) }
    const classes = ['grid-cols-(--row)']
    for (const tier of used) {
        style[`--row-${tier}`] = rowTemplate(kind, tier)
        classes.push(`@${tier}:grid-cols-(--row-${tier})`)
    }
    // A cell fills the column of its place among the row's children: the head line's come first.
    ROW_COLUMNS[kind].forEach(([name], i) => {
        const tier = tiers.get(name)
        if (tier !== undefined) {
            classes.push(`@max-${tier}:[&>:nth-child(${i + 1})]:hidden`)
        }
    })
    return { className: classes.join(' '), style }
}

/** Whether a column that shows from `from` (any width when undefined) shows on a list at least `tier` wide. */
function shownAt(from: RowTier | undefined, tier: RowTier | undefined): boolean {
    if (from === undefined) {
        return true
    }
    return tier !== undefined && tierIndex(tier) >= tierIndex(from)
}

function tierIndex(tier: RowTier): number {
    return ROW_TIERS.findIndex(([name]) => name === tier)
}

/**
 * The least a column's width can be, in rem: a fixed width or the free column's floor.
 *
 * @throws {Error} When the width is not in rem, as `auto` is not: a kind whose columns give way cannot have one.
 */
function leastRem(width: string): number {
    const match = /^(?:minmax\()?([\d.]+)rem\b/u.exec(width)
    if (match?.[1] === undefined) {
        throw new Error(`no least width in rem for ${width}`)
    }
    return Number(match[1])
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
    kind: 'col-[kind/end]',
    label: 'col-[label/end]',
    mark: 'col-[mark/end]',
    name: 'col-[name/end]',
    peak: 'col-[peak/end]',
    phase: 'col-[phase/end]',
    pr: 'col-[pr/end]',
    run: 'col-[run/end]',
    severity: 'col-[severity/end]',
    slot: 'col-[slot/end]',
    state: 'col-[state/end]',
    subject: 'col-[subject/end]',
    text: 'col-[text/end]',
    time: 'col-[time/end]',
    title: 'col-[title/end]',
    tokens: 'col-[tokens/end]',
    use: 'col-[use/end]',
    verdict: 'col-[verdict/end]',
}

/** The classes that place any element as a `RowLine` is placed, for one that is not a `div` (a nested list). */
export function rowLineFrom(from: RowColumn): string {
    return FROM[from]
}
