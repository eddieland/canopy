// The Tools report: which MCP servers and tools the agents were offered and called, and what the calls returned.
// The numbers are the server's; this lays them out.

import type { ToolsAgent, ToolsPrevious, ToolsReport, ToolsRow, ToolsUse } from '@/api/types'
import { counted } from '@/lib/descriptions'
import { pickWindow, windowName } from '@/lib/report-window'
import type { ReportWindow } from '@/lib/report-window'
import { runsText } from '@/lib/skill-report'
import { shareText } from '@/lib/spend'

/** The window the page opens on: the week, as the Skills page does. */
export const DEFAULT_TOOLS_WINDOW: ReportWindow = { days: 7 }

/** The windows the page offers, shortest first, the Skills page's: whole local days. */
export const TOOLS_WINDOWS: readonly ReportWindow[] = [DEFAULT_TOOLS_WINDOW, { days: 30 }]

/** The window the search params name, if the page offers it; undefined for the default. */
export function toolsWindow(search: { days?: unknown }): ReportWindow | undefined {
    return pickWindow(TOOLS_WINDOWS, search)
}

/** How the rows are ordered: the most called first, the least, by what their calls returned, or by those failed. */
export type ToolsSort = 'most' | 'least' | 'returned' | 'failed'

/** The orders the page offers, the one it opens on first, each with its name on the toggle. */
export const TOOLS_SORTS: readonly { key: ToolsSort; label: string }[] = [
    { key: 'most', label: 'most called' },
    { key: 'least', label: 'least called' },
    { key: 'returned', label: 'returned' },
    { key: 'failed', label: 'failed' },
]

/** The order the search params name, if the page offers it; undefined for the one it opens on. */
export function toolsSort(search: { order?: unknown }): ToolsSort | undefined {
    const picked = TOOLS_SORTS.find((s) => s.key === search.order)?.key
    return picked === 'most' ? undefined : picked
}

/** The agent the search params name: any name, kept as text, which the page holds to the agents the window has. */
export function toolsAgent(search: { agent?: unknown }): string | undefined {
    return typeof search.agent === 'string' && search.agent !== '' ? search.agent : undefined
}

/** The agent picked, if the window has it: one it does not have reads as every agent. */
export function pickedAgent(agents: readonly ToolsAgent[], picked: string | undefined): ToolsAgent | undefined {
    return agents.find((a) => a.agent === picked)
}

/**
 * A row of the servers and tools table: one server's or tool's figures over every agent, or over the one picked. The
 * same figures either way, so the table's columns mean one thing whichever it shows.
 */
export type ToolRow = Pick<
    ToolsRow,
    | 'kind'
    | 'name'
    | 'server'
    | 'listed'
    | 'unused'
    | 'offered'
    | 'partial'
    | 'called'
    | 'unoffered'
    | 'calls'
    | 'errors'
    | 'est_result_tokens'
>

/** What tells a row from every other: a server and a tool may share a name. */
export function rowKey(row: Pick<ToolRow, 'kind' | 'name'>): string {
    return `${row.kind}-${row.name}`
}

/**
 * The table's rows: each server and tool over every agent, or, with an agent picked, each that agent was offered or
 * called, by its own runs alone. A pair is unused when the agent was offered it and called it in no run of its own.
 */
export function toolRows(rows: readonly ToolsRow[], agent: string | undefined): ToolRow[] {
    if (agent === undefined) {
        return [...rows]
    }
    return rows.flatMap((row) => {
        const use = row.uses.find((u) => u.agent === agent)
        return use === undefined ? [] : [pairRow(row, use)]
    })
}

function pairRow(row: ToolsRow, use: ToolsUse): ToolRow {
    return {
        kind: row.kind,
        name: row.name,
        server: row.server,
        listed: row.listed,
        unused: use.offered > 0 && use.calls === 0,
        offered: use.offered,
        partial: use.partial,
        called: use.called,
        unoffered: use.unoffered,
        calls: use.calls,
        errors: use.errors,
        est_result_tokens: use.est_result_tokens,
    }
}

/**
 * The rows in an order (`ToolsSort`). `most`: the most calls first, the most runs offered among equals. `least`: the
 * servers and tools never called first, then the lowest call rate, the most runs offered among equals; a row with no
 * call rate, which no offer names, sorts last. `returned`: the most returned into context first. `failed`: the most
 * failed calls first. Rows that tie keep their names' order, a server before a tool of its name.
 */
export function sortedRows(rows: readonly ToolRow[], sort: ToolsSort = 'most'): ToolRow[] {
    const figures = SORT_FIGURES[sort]
    return rows.toSorted((a, b) => {
        const [x, y] = [figures(a), figures(b)]
        const at = x.findIndex((figure, i) => figure !== y[i])
        return at === -1 ? rowKey(a).localeCompare(rowKey(b)) : (x[at] ?? 0) - (y[at] ?? 0)
    })
}

// What each order sorts a row by, the smallest first, each figure breaking the ties of the one before it.
const SORT_FIGURES: Record<ToolsSort, (row: ToolRow) => number[]> = {
    most: (r) => [-r.calls, -r.offered],
    least: (r) => [r.unused ? 0 : 1, callRate(r) ?? 2, -r.offered],
    returned: (r) => [-r.est_result_tokens, -r.calls],
    failed: (r) => [-r.errors, -r.calls],
}

/**
 * The runs that called a server or a tool as a share of the runs offered it, 0 to 1; null for one no run was offered
 * on record, as a server's tool never is.
 */
export function callRate(row: Pick<ToolRow, 'offered' | 'called'>): number | null {
    return row.offered === 0 ? null : row.called / row.offered
}

/**
 * A row's call rate as its cell says it: `63%`, or `<1%` for one called too seldom to round to 1; `never` for one
 * offered and called in no run, which a muted `0%` would bury; a dash where there is no rate to say.
 */
export function rateText(row: Pick<ToolRow, 'unused' | 'offered' | 'called'>): string {
    const rate = callRate(row)
    if (rate === null) {
        return '–'
    }
    if (row.unused) {
        return 'never'
    }
    const said = shareText(rate)
    return rate > 0 && said === '0%' ? '<1%' : said
}

// The one phrase for a run nothing says what it was offered, wherever the page says it.
const NO_OFFER = 'no offer on record'

/**
 * What a row's call rate counts, on its tip: `called in 3 of the 19 runs offered it`, then the runs offered only some
 * of a server's tools, and the runs that called it with no offer on record; or why it has no rate.
 */
export function rateTip(
    row: Pick<ToolRow, 'listed' | 'server' | 'offered' | 'partial' | 'called' | 'unoffered'>,
): string {
    if (!row.listed) {
        return row.server === null
            ? `${NO_OFFER} names it, or a server it is of`
            : `an offer names ${row.server}, not its tools: known by its calls, in ${runsText(row.unoffered)}`
    }
    if (row.offered === 0) {
        return `${NO_OFFER} names it`
    }
    return [
        `called in ${row.called} of the ${runsText(row.offered)} offered it`,
        ...(row.partial === 0 ? [] : [`${row.partial} of them offered only some of its tools`]),
        ...(row.unoffered === 0 ? [] : [`called in ${runsText(row.unoffered)} with ${NO_OFFER}`]),
    ].join(' · ')
}

/** What a row is, in its cell: an MCP server, a tool built into the runtime, a tool of a server, or a tool. */
export function kindText(row: Pick<ToolRow, 'kind' | 'listed' | 'server'>): string {
    if (row.kind === 'server') {
        return 'MCP server'
    }
    if (row.listed) {
        return 'built in'
    }
    return row.server === null ? 'tool' : `of ${row.server}`
}

/** What a row's kind leaves unsaid, on its tip: where a tool no offer names comes from, as far as canopy can tell. */
export function kindTip(row: Pick<ToolRow, 'kind' | 'listed' | 'server'>): string | undefined {
    if (row.kind === 'server') {
        return "its figures are its tools' together"
    }
    if (row.listed) {
        return "one of the runtime's own tools"
    }
    return row.server === null
        ? `${NO_OFFER} names it, and its name opens with no offered server's`
        : `its name opens with ${row.server}'s, as the runtime names a server's tools`
}

/**
 * The page's description, the window's state: `3 servers and 7 tools offered over 7 days · 4 never called · 292
 * calls, 15 failed`; or `no server or tool offered over 7 days`, with the calls of runs with no offer on record.
 */
export function toolsLine(
    found: Pick<ToolsReport, 'days' | 'servers' | 'tools' | 'unused' | 'calls' | 'errors'>,
): string {
    const over = windowName(found)
    const calls = found.calls === 0 ? [] : [callsText(found)]
    if (found.servers + found.tools === 0) {
        return [`no server or tool offered over ${over}`, ...calls].join(' · ')
    }
    return [
        `${counted(found.servers, 'server')} and ${counted(found.tools, 'tool')} offered over ${over}`,
        found.unused === 0 ? 'each one called' : `${found.unused} never called`,
        ...calls,
    ].join(' · ')
}

function callsText(found: Pick<ToolsReport, 'calls' | 'errors'>): string {
    const calls = counted(found.calls, 'call')
    return found.errors === 0 ? calls : `${calls}, ${found.errors} failed`
}

/** The window's headline counts, as the page's tiles show them, which the window before's are compared with. */
export interface ToolsFigures {
    /** The servers and tools a run was offered. */
    offered: number
    /** Of those, the ones no run called. */
    unused: number
    /** The tool calls, of every tool. */
    calls: number
    /** Of those, the calls that failed. */
    errors: number
}

/** A window's servers and tools offered, those never called, its calls, and those that failed. */
export function toolsFigures(
    found: Pick<ToolsReport | ToolsPrevious, 'servers' | 'tools' | 'unused' | 'calls' | 'errors'>,
): ToolsFigures {
    return { offered: found.servers + found.tools, unused: found.unused, calls: found.calls, errors: found.errors }
}

/**
 * The runs nothing says what they were offered, under the agents' table, on every visit: how many, split into those
 * the runtime could not answer for and those it was never asked about, and where they are counted all the same.
 * Empty for a window no run started in.
 */
export function offersText(found: Pick<ToolsReport, 'runs' | 'unanswered' | 'unasked'>): string {
    const none = found.unanswered + found.unasked
    if (found.runs === 0) {
        return ''
    }
    if (none === 0) {
        return `Each of the ${runsText(found.runs)} has its offer on record.`
    }
    const why = [
        ...(found.unanswered === 0 ? [] : [`the runtime could not answer for ${found.unanswered}`]),
        ...(found.unasked === 0
            ? []
            : [`canopy never asked about ${found.unasked}, a task's, an epic's plan, or one from before it asked`]),
    ]
    return (
        `No offer on record for ${none} of ${runsText(found.runs)}: ${why.join(', and ')}. They count under the ` +
        'agent canopy ships for their kind of run, and their calls are counted.'
    )
}

/**
 * The agents in the order their table lists them: the most calls first, then the most runs. Agents that tie keep the
 * server's order.
 */
export function sortedAgents(agents: readonly ToolsAgent[]): ToolsAgent[] {
    return agents
        .map((agent, at) => ({ agent, at }))
        .toSorted((a, b) => {
            const busier = b.agent.calls - a.agent.calls
            const more = b.agent.runs - a.agent.runs
            return busier === 0 ? (more === 0 ? a.at - b.at : more) : busier
        })
        .map(({ agent }) => agent)
}

/** An agent's failed calls as a share of its calls, on their tip; undefined for an agent that called nothing. */
export function failedTip(found: Pick<ToolRow | ToolsAgent, 'calls' | 'errors'>): string | undefined {
    return found.calls === 0 ? undefined : `${shareText(found.errors / found.calls)} of ${counted(found.calls, 'call')}`
}
