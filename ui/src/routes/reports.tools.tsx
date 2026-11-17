import { useQuery } from '@tanstack/react-query'
import { createFileRoute, Link } from '@tanstack/react-router'

import { toolsReportQuery } from '@/api/queries'
import type { ToolsAgent, ToolsReport } from '@/api/types'
import { Empty, PageHeader, Panel, PanelHeader, PanelLoading, PanelSkeleton } from '@/components/panel'
import { ReadoutTiles } from '@/components/readout-tiles'
import type { ReadoutTile } from '@/components/readout-tiles'
import { ReportTable } from '@/components/report-table'
import type { ReportColumn } from '@/components/report-table'
import { Clipped } from '@/components/tip'
import { ToggleGroup, ToggleGroupItem } from '@/components/ui/toggle-group'
import { WindowToggle } from '@/components/window-toggle'
import { barPercent } from '@/lib/chart'
import { readoutDelta, wholeChange } from '@/lib/readout-delta'
import { windowBefore, windowName } from '@/lib/report-window'
import type { ReportWindow } from '@/lib/report-window'
import { noOffer, noOfferTip } from '@/lib/skill-report'
import {
    DEFAULT_TOOLS_WINDOW,
    failedTip,
    kindText,
    kindTip,
    offersText,
    pickedAgent,
    rateText,
    rateTip,
    rowKey,
    sortedAgents,
    sortedRows,
    toolRows,
    TOOLS_SORTS,
    TOOLS_WINDOWS,
    toolsAgent,
    toolsFigures,
    toolsLine,
    toolsSort,
    toolsWindow,
} from '@/lib/tool-report'
import type { ToolRow, ToolsSort } from '@/lib/tool-report'
import { tokenCount } from '@/lib/transcript'
import { cn } from '@/lib/utils'

interface ToolsSearch {
    days?: number | undefined
    order?: ToolsSort | undefined
    agent?: string | undefined
}

// What the page shows on every visit, on its title's hover: its description is the window's state.
const HELP =
    'Which MCP servers and tools the agents were offered and which they called, over the last days. Every tool an ' +
    'agent is offered rides in each of its model calls by its definition, called or not. Each agent, by its ' +
    'calls: pick one for its own servers and tools. Then each server and tool, by how often a run offered it ' +
    "called it, its calls, those that failed, and what they returned into the runs' context. An offer names a " +
    "server, not its tools, so a server's tool is listed once a run calls it. What a definition adds to a model " +
    'call is not recorded, so nothing here is the cost of being offered; and a short window cannot tell a tool ' +
    'nobody needs from one whose work did not come up. The page changes nothing: a server or a tool is denied to ' +
    "an agent in the runtime's own config."

// What a column or a tile counts, in its name's tip.
const EST = 'characters over 4, an estimate'
const OFFERED_TILE_HINT =
    "The MCP servers and the runtime's own tools a run was offered, by name: each rides in every model call of a " +
    'run offered it'
const UNUSED_TILE_HINT =
    'Of those, the servers and tools no run of any agent called, in a run offered them or any other'
const CALLS_TILE_HINT = 'The tool calls, of every tool, in every run'
const FAILED_TILE_HINT = 'Of those, the calls that failed'
const RUNS_HINT = 'Its runs that started in the window and have ended'
const NO_OFFER_HINT =
    'Of those, the runs nothing says what they were offered: canopy never asked about them, or the runtime could ' +
    'not answer. They count under the agent canopy ships for their kind of run'
const AGENT_SERVERS_HINT = 'How many MCP servers its runs were offered, by name'
const AGENT_TOOLS_HINT = "How many of the runtime's own tools its runs were offered, by name"
const AGENT_UNUSED_HINT = 'Of those servers and tools, the ones none of its runs called'
const AGENT_CALLS_HINT = 'Its tool calls, of every tool, in every run'
const AGENT_FAILED_HINT = 'Of those, the calls that failed'
const AGENT_RETURNED_HINT = `About how many tokens its calls returned into its runs' context: ${EST}`
const KIND_HINT =
    "What the row is: an MCP server, one of the runtime's own tools, or a tool of a server, which no offer names " +
    'and which is listed once a run calls it'
const OFFERED_HINT = 'The runs the runtime said it offered it: its definition rides in each of their model calls'
const RATE_HINT =
    'The runs that called it, as a share of the runs offered it. A server reached through code that calls its ' +
    'tools for the agent has no call under its own name, and reads as never called'
const CALLS_HINT = "Its calls, in every run, offered it on record or not; a server's are its tools' together"
const FAILED_HINT = 'Of those, the calls that failed, a refusal among them'
const RETURNED_HINT =
    "About how many tokens its calls returned into the runs' context, which each later model call of the run " +
    `reads again: ${EST}`

// What the offers cannot say, under the servers and tools, on every visit.
const NAMES =
    "An offer names a server, not its tools: a server's tool is listed once a run calls it, so one never called is " +
    'not here. What a definition adds to a model call is not recorded, so no figure here is the cost of being ' +
    'offered.'

/**
 * Which MCP servers and tools the agent runs of the last days were offered and called: each agent, then each server
 * and tool, over every agent or the one picked. The window is `?days=`, the week or 30 days, the rows' order
 * `?order=`, and the agent picked `?agent=`; the week, the most called first, over every agent, the defaults, need no
 * search.
 */
export const Route = createFileRoute('/reports/tools')({
    // Typed search params: a window or an order the page does not offer is dropped, which reads as its default. Any
    // agent's name is kept: the page holds it to the agents the window has.
    validateSearch: (search: Record<string, unknown>): ToolsSearch => ({
        days: toolsWindow(search)?.days,
        order: toolsSort(search),
        agent: toolsAgent(search),
    }),
    component: ToolsPage,
})

function ToolsPage() {
    const search = Route.useSearch()
    const shown: ReportWindow = search.days === undefined ? DEFAULT_TOOLS_WINDOW : { days: search.days }
    const navigate = Route.useNavigate()
    const query = useQuery(toolsReportQuery(shown.days ?? 7))
    const span = windowName(shown)
    const { data } = query
    // A read that failed with nothing on screen says so once, in the first panel, with Read again.
    const failed = data === undefined && query.error !== null
    const picked = pickedAgent(data?.agents ?? [], search.agent)
    const rows = data === undefined ? [] : sortedRows(toolRows(data.rows, picked?.agent), search.order)
    return (
        <>
            <PageHeader
                title="Tools"
                help={HELP}
                controls={
                    <WindowToggle
                        windows={TOOLS_WINDOWS}
                        shown={shown}
                        testId="tools"
                        onPick={(window) => {
                            void navigate({
                                search: (prev) => ({
                                    ...prev,
                                    days: window === DEFAULT_TOOLS_WINDOW ? undefined : window.days,
                                }),
                            })
                        }}
                    />
                }
                links={
                    !failed && <ReadoutTiles tiles={toolsTiles(data)} against={windowBefore(shown)} testId="tools" />
                }
            >
                {data === undefined ? (query.isPending ? 'reading what the runs were offered' : null) : toolsLine(data)}
            </PageHeader>
            <Panel data-testid="tools-agents">
                <PanelHeader label="Agents">
                    <span className="readout text-xs text-muted-foreground">{data?.agents.length ?? ''}</span>
                </PanelHeader>
                {data === undefined ? (
                    <PanelLoading query={query} rows={4} className="min-h-40" />
                ) : (
                    <Agents found={data} span={span} />
                )}
            </Panel>
            {!failed && (
                <Panel data-testid="tools-rows">
                    <PanelHeader label="Servers and tools">
                        <span className="flex flex-wrap items-center gap-x-3 gap-y-1">
                            <SortToggle />
                            <Scope picked={picked} />
                            <span className="readout text-xs text-muted-foreground" data-testid="tools-count">
                                {data === undefined ? '' : countText(rows.length, data.rows.length)}
                            </span>
                        </span>
                    </PanelHeader>
                    {data === undefined ? (
                        <PanelSkeleton rows={8} className="min-h-64" />
                    ) : (
                        <Rows rows={rows} picked={picked} span={span} />
                    )}
                </Panel>
            )}
        </>
    )
}

/**
 * The window's headline figures, each held in its place while the report is read, and set against the window
 * before's. None is colored: more tools, or more calls, is not a thing broken, and a call that failed may be a deny
 * at work.
 */
function toolsTiles(found: ToolsReport | undefined): ReadoutTile[] {
    const figures = found === undefined ? undefined : toolsFigures(found)
    const before = found === undefined ? undefined : toolsFigures(found.previous)
    return [
        {
            key: 'offered',
            label: 'offered',
            hint: OFFERED_TILE_HINT,
            value: figures?.offered,
            delta: readoutDelta(figures?.offered, before?.offered, wholeChange),
        },
        {
            key: 'unused',
            label: 'never called',
            hint: UNUSED_TILE_HINT,
            value: figures?.unused,
            delta: readoutDelta(figures?.unused, before?.unused, wholeChange),
        },
        {
            key: 'calls',
            label: 'calls',
            hint: CALLS_TILE_HINT,
            value: figures?.calls,
            delta: readoutDelta(figures?.calls, before?.calls, wholeChange),
        },
        {
            key: 'failed',
            label: 'failed',
            hint: FAILED_TILE_HINT,
            value: figures?.errors,
            delta: readoutDelta(figures?.errors, before?.errors, wholeChange),
        },
    ]
}

// The table's count: how many rows it lists, and of how many once an agent narrows it: `7 of 12`.
function countText(listed: number, all: number): string {
    return listed === all ? String(all) : `${listed} of ${all}`
}

/**
 * Each agent that ran, the most calls first: its runs, those with no offer on record, the servers and tools it was
 * offered, how many of those none of its runs called, then its calls, with a bar of the most's, those that failed,
 * and what they returned. An agent's name picks it for the table under it. Under the table, the runs nothing says
 * what they were offered, split by why.
 */
function Agents({ found, span }: { found: ToolsReport; span: string }) {
    if (found.agents.length === 0) {
        return <Empty size="panel">no agent ran in these {span}</Empty>
    }
    const agents = sortedAgents(found.agents)
    return (
        <div className="flex flex-col gap-3 pb-3">
            <ReportTable
                rows={agents}
                columns={agentColumns(agents)}
                rowKey={(a) => a.agent}
                label="Agents"
                className="max-h-96 px-3"
                testId="tools-agent-table"
                rowTestId={(a) => `tools-agent-${a.agent}`}
            />
            <p className="max-w-prose px-3 text-xs text-muted-foreground" data-testid="tools-offers">
                {offersText(found)}
            </p>
        </div>
    )
}

// A count the offers would say, or a dash for an agent no offer is on record for.
const NOT_KNOWN = 'no offer on record for any of its runs'

/** The agents table's columns, its bar measured against the agents shown. */
function agentColumns(agents: readonly ToolsAgent[]): ReportColumn<ToolsAgent>[] {
    const calls = agents.map((a) => a.calls)
    return [
        { key: 'agent', kind: 'name', label: 'agent', cell: (a) => <AgentLink agent={a.agent} /> },
        { key: 'runs', kind: 'figure', label: 'runs', hint: RUNS_HINT, cell: (a) => a.runs },
        {
            key: 'none',
            kind: 'figure',
            label: 'no offer',
            hint: NO_OFFER_HINT,
            cell: noOffer,
            tip: noOfferTip,
            tone: (a) => noOffer(a) === 0 && 'text-muted-foreground',
        },
        {
            key: 'servers',
            kind: 'figure',
            label: 'servers',
            hint: AGENT_SERVERS_HINT,
            cell: (a) => a.servers ?? '–',
            tip: (a) => (a.servers === null ? NOT_KNOWN : undefined),
            tone: (a) => (a.servers ?? 0) === 0 && 'text-muted-foreground',
        },
        {
            key: 'tools',
            kind: 'figure',
            label: 'tools',
            hint: AGENT_TOOLS_HINT,
            cell: (a) => a.tools ?? '–',
            tip: (a) => (a.tools === null ? NOT_KNOWN : undefined),
            tone: (a) => (a.tools ?? 0) === 0 && 'text-muted-foreground',
        },
        {
            key: 'unused',
            kind: 'figure',
            label: 'never called',
            hint: AGENT_UNUSED_HINT,
            cell: (a) => a.unused ?? '–',
            tone: (a) => (a.unused ?? 0) === 0 && 'text-muted-foreground',
        },
        {
            key: 'calls',
            kind: 'bar',
            label: 'calls',
            hint: AGENT_CALLS_HINT,
            cell: (a) => a.calls,
            bar: (a) => barPercent(a.calls, calls),
            tone: (a) => a.calls === 0 && 'text-muted-foreground',
        },
        {
            key: 'failed',
            kind: 'figure',
            label: 'failed',
            hint: AGENT_FAILED_HINT,
            cell: (a) => a.errors,
            tip: failedTip,
            tone: (a) => a.errors === 0 && 'text-muted-foreground',
        },
        {
            key: 'returned',
            kind: 'figure',
            label: 'returned ~tokens',
            hint: AGENT_RETURNED_HINT,
            cell: (a) => tokenCount(a.est_result_tokens),
            tone: (a) => a.est_result_tokens === 0 && 'text-muted-foreground',
        },
    ]
}

/** An agent's name, which picks it for the servers and tools table: its rows are then that agent's own. */
function AgentLink({ agent }: { agent: string }) {
    return (
        // The router marks the picked one's link `aria-current="page"`: its search is the page's own.
        <Link
            from={Route.fullPath}
            to="/reports/tools"
            search={(prev) => ({ ...prev, agent })}
            replace
            resetScroll={false}
            className={cn(
                '-mx-1 block rounded-sm px-1 font-mono text-accent underline-offset-4 hover:underline',
                'aria-[current=page]:bg-accent/16 aria-[current=page]:text-foreground',
            )}
        >
            <Clipped text={agent} mono className="block max-w-64" />
        </Link>
    )
}

/** The rows' order, kept in `?order=`: the most called first, the one the page opens on, or one of the others. */
function SortToggle() {
    const search = Route.useSearch()
    const navigate = Route.useNavigate()
    return (
        <ToggleGroup
            type="single"
            value={search.order ?? 'most'}
            aria-label="Sort"
            onValueChange={(value) => {
                const picked = TOOLS_SORTS.find((s) => s.key === value)
                // Pressing the order shown turns it off: keep it. The order the page opens on needs no search.
                if (picked !== undefined) {
                    void navigate({
                        search: (prev) => ({ ...prev, order: picked.key === 'most' ? undefined : picked.key }),
                        replace: true,
                        resetScroll: false,
                    })
                }
            }}
        >
            {TOOLS_SORTS.map((s) => (
                <ToggleGroupItem key={s.key} value={s.key} data-testid={`tools-sort-${s.key}`}>
                    {s.label}
                </ToggleGroupItem>
            ))}
        </ToggleGroup>
    )
}

/**
 * Whose runs the servers and tools table counts, in its header: every agent's, or the picked agent's, by its name,
 * then a link back to every agent's.
 */
function Scope({ picked }: { picked: ToolsAgent | undefined }) {
    return (
        <span className="flex min-w-0 items-center gap-3 text-xs">
            <span className="min-w-0 truncate readout text-muted-foreground" data-testid="tools-scope">
                {picked === undefined ? 'every agent' : picked.agent}
            </span>
            {picked !== undefined && (
                <Link
                    from={Route.fullPath}
                    to="/reports/tools"
                    search={(prev) => ({ ...prev, agent: undefined })}
                    // Not the page shown while an agent is: its search drops the agent rather than matching it.
                    activeOptions={{ explicitUndefined: true }}
                    replace
                    resetScroll={false}
                    className="whitespace-nowrap text-accent underline-offset-4 hover:underline"
                >
                    every agent
                </Link>
            )}
        </span>
    )
}

/**
 * Each server and tool a run was offered or called, over every agent or the one picked: what it is, the runs offered
 * it and the share that called it, its calls, with a bar of the most's, those that failed, and what they returned. One
 * offered and called in no run reads `never` where its rate would. Under the table, what the offers cannot say.
 */
function Rows({ rows, picked, span }: { rows: ToolRow[]; picked: ToolsAgent | undefined; span: string }) {
    return (
        <div className="flex flex-col gap-3 pb-3">
            {rows.length === 0 ? (
                <Empty size="panel">
                    {picked === undefined ? (
                        <>no server or tool was offered or called in these {span}</>
                    ) : (
                        <>
                            no server or tool was offered to <span className="font-mono">{picked.agent}</span> or called
                            by it in these {span}
                        </>
                    )}
                </Empty>
            ) : (
                <ReportTable
                    rows={rows}
                    columns={rowColumns(rows)}
                    rowKey={rowKey}
                    label="Servers and tools"
                    className="max-h-none px-3"
                    testId="tools-row-table"
                    rowTestId={(r) => `tools-row-${rowKey(r)}`}
                />
            )}
            <p className="max-w-prose px-3 text-xs text-muted-foreground" data-testid="tools-names">
                {NAMES}
            </p>
        </div>
    )
}

/** The servers and tools table's columns, its bar measured against the rows shown. */
function rowColumns(rows: readonly ToolRow[]): ReportColumn<ToolRow>[] {
    const calls = rows.map((r) => r.calls)
    return [
        {
            key: 'name',
            kind: 'name',
            label: 'name',
            cell: (r) => <Clipped text={r.name} mono className="block max-w-80 font-mono" />,
        },
        { key: 'kind', kind: 'word', label: 'kind', hint: KIND_HINT, cell: kindText, tip: kindTip, muted: true },
        {
            key: 'offered',
            kind: 'figure',
            label: 'offered',
            hint: OFFERED_HINT,
            cell: (r) => (r.offered === 0 ? '–' : r.offered),
            tone: (r) => r.offered === 0 && 'text-muted-foreground',
        },
        {
            key: 'rate',
            kind: 'figure',
            label: 'call rate',
            hint: RATE_HINT,
            cell: rateText,
            tip: rateTip,
            // `never` is the finding, so it is not muted as a zero would be; a dash, nothing to say, is.
            tone: (r) => rateText(r) === '–' && 'text-muted-foreground',
        },
        {
            key: 'calls',
            kind: 'bar',
            label: 'calls',
            hint: CALLS_HINT,
            cell: (r) => r.calls,
            bar: (r) => barPercent(r.calls, calls),
            tone: (r) => r.calls === 0 && 'text-muted-foreground',
        },
        {
            key: 'failed',
            kind: 'figure',
            label: 'failed',
            hint: FAILED_HINT,
            cell: (r) => r.errors,
            tip: failedTip,
            tone: (r) => r.errors === 0 && 'text-muted-foreground',
        },
        {
            key: 'returned',
            kind: 'figure',
            label: 'returned ~tokens',
            hint: RETURNED_HINT,
            cell: (r) => tokenCount(r.est_result_tokens),
            tone: (r) => r.est_result_tokens === 0 && 'text-muted-foreground',
        },
    ]
}
