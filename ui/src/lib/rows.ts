import type { CSSProperties } from 'react'

/** The narrowest the free column gets, in rem: it holds a row's name, which never vanishes. */
const FLOOR_REM = 8

/** The free column: whatever width the others leave, never under the floor, and its text cut to fit. */
const FREE = free(FLOOR_REM)

/**
 * The container sizes a column can show from (Tailwind's, in rem), narrowest first. A list's width picks one, so a row
 * fits the panel it is in, wherever the panel sits: a narrow window, beside a ticket's thread.
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

/**
 * Every list's age column, fixed rather than fitted, so ages line up from list to list: `ended 12h ago`, the longest
 * an age reads, fits it.
 */
const AGE = '6rem'

/** Every list's cost column, fixed rather than fitted, so costs line up from list to list. */
const COST = '4rem'

/** The room a column needs, in rem, to show at any width, under the first tier as well. */
const BASE_REM = 22

// A row's own room beside its columns: the gap between two (`gap-x-3`) and its padding (`px-3`), each side's half.
const GAP_REM = 0.75
const PADDING_REM = 1.5

/**
 * A row's padding on each side, in rem, which a subgrid lays inside the list's first and last columns: the list's
 * template widens those two by it, so a fixed column there keeps its width.
 */
const INSET_REM = PADDING_REM / 2

/**
 * The free column with a floor of its own, `floor` rem, for a kind whose name needs more than the usual floor to be
 * read: whatever width the others leave, and its text cut to fit.
 */
function free(floor: number): string {
    return `minmax(${floor}rem,1fr)`
}

/**
 * A column as wide as the widest of its cells in its list, up to `most` rem, past which a cell is cut: every row of the
 * list shares it, so they line up, and what it leaves goes to the free column. A column's tier counts it at `least`,
 * its most unless it says less: on a list just wide enough for that, its cells are cut to it rather than the free
 * column under its floor. The least is the first length of a `max()` the browser reads as the most.
 */
function fit(most: number, least = most): string {
    return least === most ? `fit-content(${most}rem)` : `fit-content(max(${least}rem,${most}rem))`
}

/**
 * Every list's columns, by kind, each a named grid line and a width. The list sets them, and its rows share them as
 * subgrids (`ListRow`), so each column is as wide as its widest cell in that list, up to its most (`fit`), and every
 * row lines up whatever its cells hold; the free one takes the rest, and never less than its floor. The age and the
 * cost are fixed, so they line up from list to list too, and so are a kind's whose lists must line up with each other.
 * What goes under a row's head line starts at a named column (`RowLine`), never at a hand-computed indent.
 *
 * A row reads in one order in every kind (`ui/DESIGN.md`, "Lists are rows in a panel"): its state, where it has one,
 * so the left edge of a list is a column of dots; its own id; what it belongs to; the chips that describe it; the
 * free column; then only readouts, right-aligned, age last.
 *
 * A column with a third entry gives way on a narrow list, in that order: 1 goes first. It shows only where the list
 * has room for it, every column that gives way after it, and the ones that never do, each at its least (`rowTiers`).
 */
export const ROW_COLUMNS = {
    /**
     * A run on the runs page: the state, the run's id, what it works for (a ticket, a review's ticket, a chore), its
     * chips, then its ticket's title, or a review's PR and what it found.
     */
    run: [
        ['state', fit(5)],
        ['run', fit(8, 5), 4],
        // A chore's name is longer than a ticket's key: the list widens to it when it holds one.
        ['key', fit(14, 6)],
        // Its chips go before its age: they describe the run, where the age says whether it is current.
        ['kind', fit(16, 10), 2],
        ['title', FREE],
        ['cost', COST, 1],
        ['age', AGE, 3],
    ],
    /**
     * A run under its subject (a ticket's, a PR's, a chore's): the state, then the run's id at a fixed width and its
     * chips, the order a run's row has on the runs page.
     */
    'own-run': [
        ['state', fit(5)],
        ['facts', FREE],
        ['cost', COST, 1],
        ['age', AGE, 2],
    ],
    /**
     * A tick: its status, its id, a dry run's chip, how many decisions, its overseer's cost, tokens, and peak context,
     * and when. The token counts give way before the cost, which says the same in dollars.
     */
    tick: [
        // A long status (`overseer failed`) wraps: a wider column would leave the free one under its floor.
        ['state', fit(6)],
        ['id', fit(5)],
        ['facts', FREE],
        ['decisions', fit(6), 4],
        ['cost', COST, 3],
        ['tokens', fit(6), 1],
        ['peak', fit(5), 2],
        ['age', AGE, 5],
    ],
    /**
     * A failed run on the health page: how it ended, its own id (a tick's, a worker's or a plan's run, a chore's run, a
     * review, a task's run), what it was about, its sort, its note, its cost, and when it started.
     */
    failure: [
        // A long status (`overseer failed`) wraps, as a tick's does.
        ['state', fit(6)],
        ['id', fit(7)],
        ['subject', fit(9), 3],
        ['kind', fit(7), 2],
        ['title', FREE],
        ['cost', COST, 1],
        ['age', AGE, 4],
    ],
    /**
     * A chore: its name, its line in `canopy status`'s words, and its open findings, on one line however many.
     */
    chore: [
        ['name', fit(20, 10)],
        ['state', FREE],
        ['findings', fit(14), 1],
    ],
    /** A review run on the reviews page: its verdict, id, ticket, impact, PR, commit, and persona, cost, and when. */
    review: [
        // A verdict on one line, with its dot and its draft's chip, which a longer verdict is cut beside.
        ['verdict', fit(14), 5],
        ['id', fit(5)],
        ['key', fit(6), 3],
        ['impact', fit(7), 2],
        ['pr', FREE],
        ['cost', COST, 1],
        ['age', AGE, 4],
    ],
    /** A review run on its PR's page: as on the reviews page, without the ticket and the PR. */
    'own-review': [
        ['verdict', fit(14), 4],
        ['id', fit(6)],
        ['impact', fit(7), 2],
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
        // A verdict on one line, with its dot. Beside a draft's chip it is cut, its whole on hover: any wider and the
        // title is cut to a word in a narrow window.
        ['state', fit(14), 3],
        ['pr', fit(11)],
        // It goes first, before the title is cut to a word.
        ['phase', fit(9), 1],
        ['title', FREE],
        ['age', AGE, 2],
    ],
    /**
     * A ticket: where it stands (its run, `waiting on you`, `done`, or `open`), its key, its phase, public or private,
     * its title, and its age.
     */
    ticket: [
        ['run', fit(8), 4],
        ['key', fit(6)],
        ['phase', fit(10), 2],
        ['access', fit(9), 1],
        ['title', FREE],
        ['age', AGE, 3],
    ],
    /**
     * A task: where it stands (`waiting on you`, its latest run's status, `queued`, or `stopped`), its id, its
     * repository, the first line of its text, and when it was submitted. Its latest run's summary goes under its text.
     */
    task: [
        ['state', fit(8), 3],
        ['id', fit(5.5)],
        ['repo', fit(6), 1],
        ['title', FREE],
        ['age', AGE, 2],
    ],
    /**
     * An epic: where it stands (`waiting on you`, `planning`, `approved`, ...), its id, its repositories, its goal's
     * first line, how many of its breakdown's entries are filed, and when it was submitted.
     */
    epic: [
        ['state', fit(8), 4],
        ['id', fit(5.5)],
        ['repo', fit(10), 1],
        ['title', FREE],
        ['entries', fit(10), 3],
        ['age', AGE, 2],
    ],
    /**
     * A worktree slot: its state, its number, what holds it, its branch and processes, and for how long. The branch
     * names the slot, so it never gets under its floor, and what holds it goes first: the branch names its ticket too.
     */
    worktree: [
        ['state', fit(5)],
        ['slot', fit(3.5)],
        ['holder', fit(24, 13), 1],
        ['branch', free(12)],
        ['age', AGE, 2],
    ],
    /** A decision in a tick: its subject, then its action and PR. */
    decision: [
        ['subject', fit(9)],
        ['action', FREE],
    ],
    /** A decision on its subject's page: the tick that made it, its action and PR, and its age. */
    'own-decision': [
        ['id', fit(4)],
        ['action', FREE],
        ['age', AGE],
    ],
    /**
     * A chore's finding: its id, its title, and what it says of itself at the end. Ids differ in length: a short one
     * takes its own width, and a long one (up to 200 characters) wraps rather than squeeze the title to its floor.
     */
    finding: [
        ['id', fit(12)],
        ['title', FREE],
        ['facts', 'auto'],
    ],
    /** A review's finding in its list: its number and its box to send it, its severity, its title, and where it is. */
    'review-finding': [
        ['id', fit(2.5)],
        ['severity', fit(4)],
        ['title', FREE],
        ['facts', 'auto'],
    ],
    /** A comment in a review's draft: its number, what it came from (`yours` or `finding N`), its line, and where. */
    'draft-comment': [
        ['id', fit(2.5)],
        ['from', fit(5.5)],
        ['title', FREE],
        ['facts', 'auto'],
    ],
    /** A PR's draft in its threads' head: where it stands, its run and number, its text, and where its card is. */
    'thread-draft': [
        ['state', fit(6)],
        ['id', fit(5)],
        ['title', FREE],
        ['facts', 'auto'],
    ],
    /** A search hit: where it opens, its label, the snippet, and its age. */
    'search-hit': [
        ['subject', fit(9)],
        ['label', fit(8), 2],
        ['text', FREE],
        ['age', AGE, 1],
    ],
    /**
     * A note, proposal, or lesson (DESIGN §28): where it stands, its id, its repository, its key, how many runs relied
     * on it, and when it was written. What it says goes under its key.
     */
    memory: [
        ['state', fit(6)],
        ['id', fit(7)],
        ['repo', fit(5), 3],
        ['key', FREE],
        ['use', fit(8), 1],
        ['age', AGE, 2],
    ],
    /**
     * Memories across tickets, the proposals, the lessons, and a ticket's notes on the memory page: a memory's columns,
     * with its ticket after its id. They are fixed rather than fitted, as the age is, since each panel of that page is
     * a list of its own, and its keys and text line up down the page, a ticket's opened notes with the lessons.
     */
    'memory-across': [
        ['state', '6rem'],
        ['id', '6rem'],
        ['ticket', '6rem', 4],
        ['repo', '5rem', 3],
        ['key', FREE],
        ['use', '8rem', 1],
        ['age', AGE, 2],
    ],
    /**
     * A ticket with notes in force, on the memory page: its key, what opens its notes under it, the ticket's title, how
     * runs used them, and when the newest was written.
     */
    'memory-ticket': [
        ['key', fit(6)],
        ['notes', fit(7)],
        ['title', FREE],
        ['use', fit(9), 1],
        ['age', AGE, 2],
    ],
    /**
     * An item of a run's checklist, on the run's page: what the run answered, as a chip, then the item's id. A held
     * item's reason goes under its id.
     */
    'checklist-answer': [
        ['state', fit(5.5)],
        ['item', FREE],
    ],
    /**
     * A comment on a ticket's PR its review cursors passed with no worker: why it was left first, as a state leads a
     * row, so the left edge says whether any of it is risky; who wrote it and its first line, in the free column;
     * where it is, linking out to it; the tick that left it; and its button to send it to a worker. Beside a ticket's
     * thread in a 1720px window the list is about 36rem wide, too narrow for the author in a column of its own, so it
     * leads the free one; the tick goes first, then where it is, which the button's name still says.
     */
    'left-feedback': [
        ['reason', fit(9.5)],
        ['title', FREE],
        // A file's name and line, and its icon; its whole path is on hover.
        ['where', fit(7), 2],
        ['tick', fit(4), 1],
        ['send', fit(1.5)],
    ],
    /**
     * A transcript's row: its time, its mark, and its text, under which a tool call's body opens. Its head line is not
     * cells in these columns but a line of its own, its time and mark at these widths, so they stay fixed: a call's
     * body lines up with it as a grid of its own (`RowGrid`'s `alone`).
     */
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
 * next one shown, so a line under the row that starts there still has a place. The first and last columns shown are
 * `inset` rem wider, the room a row's padding takes inside them as its list's subgrid (`ListRow`); a grid of its own
 * (`RowGrid`'s `alone`) pads outside its columns, so it passes 0.
 */
export function rowTemplate(kind: RowKind, tier?: RowTier, inset = INSET_REM): string {
    const tiers = rowTiers(kind)
    const shown: [string[], string][] = []
    let names: string[] = []
    for (const [name, width] of ROW_COLUMNS[kind]) {
        names.push(name)
        if (shownAt(tiers.get(name), tier)) {
            shown.push([names, width])
            names = []
        }
    }
    const last = shown.length - 1
    const parts = shown.map(
        ([lines, width], i) => `[${lines.join(' ')}] ${i === 0 || i === last ? widen(width, inset) : width}`,
    )
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
 * What lays a list of rows of `kind` out: its columns' template at each tier, as custom properties, and the classes
 * that pick one by the list's width (the nearest `@container`, a `Panel`). Its rows share the columns as subgrids
 * (`ListRow`), so the browser sizes each to its widest cell in the list. `inset` is as `rowTemplate` takes it. The
 * classes are built here, so `index.css` lists them for Tailwind (`@source inline`).
 */
export function rowLayout(kind: RowKind, inset = INSET_REM): { className: string; style: CSSProperties } {
    const tiers = rowTiers(kind)
    const used = ROW_TIERS.filter(([tier]) => [...tiers.values()].includes(tier)).map(([tier]) => tier)
    const style: Record<string, string> = { '--row': rowTemplate(kind, undefined, inset) }
    const classes = ['grid-cols-(--row)']
    for (const tier of used) {
        style[`--row-${tier}`] = rowTemplate(kind, tier, inset)
        classes.push(`@${tier}:grid-cols-(--row-${tier})`)
    }
    return { className: classes.join(' '), style }
}

/**
 * What makes an element a subgrid of the list of rows it is in, across all of its columns: a row, and anything between
 * the list and a row, such as the earlier runs a row opens under it, so their cells still line up with the list's.
 */
export const ROW_SUBGRID = 'col-span-full grid grid-cols-subgrid'

/**
 * The classes that hide a row's cells in the columns its list leaves out at its width, by their place among the row's
 * children, where the head line's come first. Built here, so `index.css` lists them for Tailwind (`@source inline`).
 */
export function rowHidden(kind: RowKind): string {
    const tiers = rowTiers(kind)
    return ROW_COLUMNS[kind]
        .flatMap(([name], i) => {
            const tier = tiers.get(name)
            return tier === undefined ? [] : [`@max-${tier}:[&>:nth-child(${i + 1})]:hidden`]
        })
        .join(' ')
}

/**
 * The classes that hold each cell of a row's head line of `kind` to its column, its first cells, one per column: no
 * wider than the column (`min-w-0`, where a grid's item is as wide as its content), and what still overflows it, a
 * word with nowhere to break, cut with an ellipsis rather than drawn over the next column. A cell's text wraps as it
 * did, and one that cuts itself to one line (`Clipped`) gives the whole in its tip. The classes are built here, so
 * `index.css` lists them for Tailwind (`@source inline`).
 */
export function rowCells(kind: RowKind): string {
    const head = `[&>:nth-child(-n+${ROW_COLUMNS[kind].length})]`
    return `${head}:min-w-0 ${head}:overflow-x-clip ${head}:text-ellipsis`
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

/** A column's width `inset` rem wider: its first length in rem, a fixed width, a most, or a floor; `auto` as it is. */
function widen(width: string, inset: number): string {
    if (inset === 0) {
        return width
    }
    return width.replaceAll(/([\d.]+)rem/gu, (_, rem: string) => `${Number(rem) + inset}rem`)
}

/**
 * The least a column's width can be, in rem, for its tier: a fixed width, a fitted column's most (it may be any width
 * to it), or the free column's floor.
 *
 * @throws {Error} When the width is not in rem, as `auto` is not: a kind whose columns give way cannot have one.
 */
function leastRem(width: string): number {
    const match = /^(?:minmax\(|fit-content\((?:max\()?)?([\d.]+)rem\b/u.exec(width)
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
    entries: 'col-[entries/end]',
    facts: 'col-[facts/end]',
    findings: 'col-[findings/end]',
    from: 'col-[from/end]',
    holder: 'col-[holder/end]',
    id: 'col-[id/end]',
    impact: 'col-[impact/end]',
    item: 'col-[item/end]',
    key: 'col-[key/end]',
    kind: 'col-[kind/end]',
    label: 'col-[label/end]',
    mark: 'col-[mark/end]',
    name: 'col-[name/end]',
    notes: 'col-[notes/end]',
    peak: 'col-[peak/end]',
    phase: 'col-[phase/end]',
    reason: 'col-[reason/end]',
    pr: 'col-[pr/end]',
    repo: 'col-[repo/end]',
    run: 'col-[run/end]',
    send: 'col-[send/end]',
    severity: 'col-[severity/end]',
    slot: 'col-[slot/end]',
    state: 'col-[state/end]',
    subject: 'col-[subject/end]',
    text: 'col-[text/end]',
    tick: 'col-[tick/end]',
    ticket: 'col-[ticket/end]',
    time: 'col-[time/end]',
    title: 'col-[title/end]',
    tokens: 'col-[tokens/end]',
    use: 'col-[use/end]',
    verdict: 'col-[verdict/end]',
    where: 'col-[where/end]',
}

/** The classes that place any element as a `RowLine` is placed, for one that is not a `div` (a nested list). */
export function rowLineFrom(from: RowColumn): string {
    return FROM[from]
}
