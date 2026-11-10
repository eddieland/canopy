import { useQuery } from '@tanstack/react-query'
import { Link } from '@tanstack/react-router'
import { ArrowDown, ChevronRight, ListTree } from 'lucide-react'
import type { ReactNode } from 'react'

import { hostProcessesQuery } from '@/api/queries'
import type { HostProcess, HostProcesses, ProcessWork } from '@/api/types'
import { Empty, Panel, PanelHeader, PanelSkeleton } from '@/components/panel'
import { Button } from '@/components/ui/button'
import { Toggle } from '@/components/ui/toggle'
import { bytesText } from '@/lib/host'
import { setProcessSettings, useProcessSettings, withFold } from '@/lib/process-settings'
import { cpuText, processRows, processView, STATE_TEXT } from '@/lib/processes'
import type { ChainRow, ProcessOrder, ProcessRow, ProcessSection } from '@/lib/processes'
import { pullRequestLabel } from '@/lib/pull-request-label'
import { choreRunRef, epicRunRef, reviewRef, runRef, taskRunRef } from '@/lib/refs'
import { cn } from '@/lib/utils'

// A column's head, as the reports' tables have them.
const HEAD = 'panel-label pb-1.5 pl-3 text-right font-normal whitespace-nowrap'

// A process at least this busy, half a core, reads in the foreground: it is what the operator came to find.
const HOT_CPU = 0.5

// Each line steps in this far for each parent above it.
const STEP_REM = 0.875

// What a run's figures are: its own process and everything under it, what the run costs.
const RUN_TOTAL = 'This run and every process under it'

/**
 * The machine's processes as a tree, each parent over its children and the busiest first, with the processors each
 * kept busy since the server's read before and the memory it holds: what answers "what is keeping it busy, and is it
 * canopy?". Until the operator asks for every one, it is the loop's tree, its parents named in one line over it, each
 * run's process carrying its run and what the run adds up to, then whatever else is busy under `elsewhere`. A thin bar
 * behind each figure reads it at a glance; the CPU and memory heads order it; a parent folds to one line with what it
 * and its children add up to. How the tree was left is kept in this browser.
 */
export function ProcessTree({
    loop,
    cores,
    memory,
}: {
    /** The loop's own process id. */
    loop: number
    /** The machine's cores, for the header's count, or null where not known. */
    cores: number | null
    /** All the memory there is, which a memory bar is scaled to, or null where not known. */
    memory: number | null
}) {
    const { data } = useQuery(hostProcessesQuery)
    const { all } = useProcessSettings()
    return (
        <Panel data-testid="host-processes">
            <PanelHeader label="Processes">
                {data !== undefined && data.processes !== null && (
                    <span className="flex flex-wrap items-center gap-x-3 gap-y-1">
                        <span className="readout text-xs text-muted-foreground">{busyText(data, cores)}</span>
                        <Toggle
                            size="xs"
                            pressed={all}
                            onPressedChange={(pressed) => {
                                setProcessSettings({ all: pressed })
                            }}
                            title={all ? 'Show the loop’s work and what else is busy' : 'Show every process'}
                        >
                            <ListTree />
                            All
                        </Toggle>
                    </span>
                )}
            </PanelHeader>
            {data === undefined ? (
                <PanelSkeleton rows={4} className="min-h-40" />
            ) : data.processes === null ? (
                <Empty>not read on this system: only Linux says what each process uses</Empty>
            ) : (
                <Tree processes={data.processes} loop={loop} memory={memory} />
            )}
        </Panel>
    )
}

/** The tree's table: its sections, each under its heading, and how many idle processes it leaves out. */
function Tree({ processes, loop, memory }: { processes: HostProcess[]; loop: number; memory: number | null }) {
    const settings = useProcessSettings()
    const view = processView(processes, loop, settings.all)
    const folded = new Set(settings.folded)
    const chain = settings.all
        ? undefined
        : new Set([loop, ...processes.filter((p) => p.work !== null).map((p) => p.pid)])
    const fold = (pid: number) => {
        setProcessSettings({ folded: withFold(settings.folded, pid, !folded.has(pid)) })
    }
    return (
        <div className="overflow-x-auto px-3 pb-2">
            <table className="w-full border-collapse text-sm" data-testid="process-tree">
                <thead>
                    <tr>
                        <th className="panel-label w-full pt-3 pb-1.5 text-left font-normal">process</th>
                        <th className={cn(HEAD, 'hidden pt-3 @2xl:table-cell')}>user</th>
                        <SortHead
                            order="cpu"
                            current={settings.order}
                            title="Of one core: 100% is one core the whole time"
                        >
                            cpu
                        </SortHead>
                        <SortHead order="memory" current={settings.order} title="The memory each holds">
                            memory
                        </SortHead>
                    </tr>
                </thead>
                {view.sections.map((section) => (
                    <Section
                        key={section.heading ?? 'loop'}
                        section={section}
                        rows={processRows(section.roots, folded, { order: settings.order, chain })}
                        loop={loop}
                        memory={memory}
                        onFold={fold}
                    />
                ))}
            </table>
            {view.hidden > 0 && (
                <p className="pt-1.5 text-xs text-muted-foreground" data-testid="process-hidden">
                    {view.hidden} {view.hidden === 1 ? 'process' : 'processes'} using under 1% of a core left out.
                </p>
            )}
        </div>
    )
}

/** A column head that orders the tree by its column, the busiest or the heaviest first, saying which it is. */
function SortHead({
    order,
    current,
    title,
    children,
}: {
    order: ProcessOrder
    current: ProcessOrder
    title: string
    children: ReactNode
}) {
    const on = order === current
    return (
        <th className={cn(HEAD, 'pt-3')} aria-sort={on ? 'descending' : 'none'}>
            <button
                type="button"
                title={`${title}. Order by it, the most first`}
                className={cn(
                    'inline-flex items-center gap-0.5 uppercase hover:text-foreground',
                    on && 'text-foreground',
                )}
                onClick={() => {
                    setProcessSettings({ order })
                }}
            >
                {on && <ArrowDown aria-hidden className="size-3" />}
                {children}
            </button>
        </th>
    )
}

/** One section's rows: its heading, the loop's parents in one line, then its lines. */
function Section({
    section,
    rows,
    loop,
    memory,
    onFold,
}: {
    section: ProcessSection
    rows: (ProcessRow | ChainRow)[]
    loop: number
    memory: number | null
    onFold: (pid: number) => void
}) {
    return (
        <tbody data-testid={section.heading === null ? undefined : `process-${section.heading}`}>
            {section.heading !== null && (
                <tr className="border-t">
                    <th colSpan={4} scope="colgroup" className="panel-label pt-3 pb-1.5 text-left font-normal">
                        {section.heading}
                    </th>
                </tr>
            )}
            {section.above.length > 0 && (
                <tr className="border-t" data-testid="process-above">
                    <td colSpan={4} className="max-w-0 truncate py-1 text-xs text-muted-foreground">
                        <span title={section.above.map((p) => `${p.name} ${p.pid}`).join(' › ')}>
                            under {section.above.map((p) => p.name).join(' › ')}
                        </span>
                    </td>
                </tr>
            )}
            {rows.map((row) =>
                row.kind === 'chain' ? (
                    <Chain key={`chain-${row.nodes[0]?.process.pid}`} row={row} />
                ) : (
                    <Row key={row.node.process.pid} row={row} loop={loop} memory={memory} onFold={onFold} />
                ),
            )}
        </tbody>
    )
}

/** Idle parents on the way to one child each, as one muted line of their names; each one's pid on hover. */
function Chain({ row }: { row: ChainRow }) {
    return (
        <tr className="border-t" data-testid="process-chain">
            <td colSpan={4} className="max-w-0 py-1">
                <div
                    className="truncate pl-7.5 text-xs text-muted-foreground"
                    style={{ marginLeft: `${row.depth * STEP_REM}rem` }}
                    title={row.nodes.map((n) => `${n.process.name} ${n.process.pid}`).join(' › ')}
                >
                    {row.nodes.map((n) => n.process.name).join(' › ')}
                </div>
            </td>
        </tr>
    )
}

/**
 * One process's line: a fold for its children, its name and pid, the run it is the process of or that it is the
 * loop's, what it is doing when that is not sleeping, its command line, its account, and what it uses. Folded, its
 * figures are its own and its children's together; a run's always are, what the run costs.
 */
function Row({
    row,
    loop,
    memory,
    onFold,
}: {
    row: ProcessRow
    loop: number
    memory: number | null
    onFold: (pid: number) => void
}) {
    const { node, depth, folded } = row
    const { process } = node
    const parent = node.children.length > 0
    const whole = folded || process.work !== null
    const cpu = whole ? node.cpu : process.cpu
    const rss = whole ? node.rss : process.rss
    const state = STATE_TEXT[process.state]
    const title = process.work === null ? undefined : RUN_TOTAL
    return (
        <tr className="border-t align-baseline" data-testid="process-row">
            <td className="max-w-0 py-1 pr-1">
                {/* A step in for each level; a leaf keeps the fold's place, so names line up. */}
                <div className="flex min-w-0 items-baseline gap-1.5" style={{ paddingLeft: `${depth * STEP_REM}rem` }}>
                    {parent ? (
                        <Button
                            variant="ghost"
                            size="icon-xs"
                            className="-my-1 shrink-0 self-center"
                            aria-expanded={!folded}
                            aria-label={`${folded ? 'Unfold' : 'Fold'} ${process.name} ${process.pid}`}
                            onClick={() => {
                                onFold(process.pid)
                            }}
                        >
                            <ChevronRight
                                aria-hidden
                                className={cn(!folded && 'rotate-90', 'motion-safe:transition-transform')}
                            />
                        </Button>
                    ) : (
                        <span aria-hidden className="w-6 shrink-0" />
                    )}
                    <span className="shrink-0 font-mono text-xs">{process.name}</span>
                    <span className="readout shrink-0 text-xs text-muted-foreground">{process.pid}</span>
                    {process.pid === loop && (
                        <span className="shrink-0 text-xs text-accent" data-testid="process-loop">
                            the loop
                        </span>
                    )}
                    {process.work !== null && <WorkChip work={process.work} />}
                    {state !== undefined && (
                        <span
                            className={cn(
                                'shrink-0 text-xs',
                                process.state === 'running' ? 'text-status-running' : 'text-status-blocked',
                            )}
                        >
                            {state}
                        </span>
                    )}
                    {folded && <span className="shrink-0 text-xs text-muted-foreground">+{node.under} under it</span>}
                    {process.command !== '' && process.command !== process.name && (
                        <span className="truncate font-mono text-xs text-muted-foreground" title={process.command}>
                            {process.command}
                        </span>
                    )}
                </div>
            </td>
            <td className="hidden py-1 pl-3 text-right text-xs whitespace-nowrap text-muted-foreground @2xl:table-cell">
                {process.user}
            </td>
            <Figure share={Math.min(1, cpu)} hot={cpu >= HOT_CPU} title={title}>
                {cpuText(cpu)}
            </Figure>
            <Figure share={memory === null || memory <= 0 ? 0 : Math.min(1, rss / memory)} hot={false} title={title}>
                {bytesText(rss)}
            </Figure>
        </tr>
    )
}

/**
 * A figure's cell, over a thin bar of how much it is: the processors against one core, the memory against all there
 * is, so a compiler at 98% stands out from a shell at 0% before a digit is read. The bar is for the eye alone.
 */
function Figure({ share, hot, title, children }: { share: number; hot: boolean; title?: string; children: ReactNode }) {
    return (
        <td className="relative py-1 pl-3 text-right text-xs whitespace-nowrap" title={title}>
            <span
                aria-hidden
                data-testid="process-bar"
                className="absolute inset-y-1 right-0 rounded-sm bg-accent/15"
                style={{ width: `${share * 100}%` }}
            />
            <span className={cn('readout relative', hot ? 'text-foreground' : 'text-muted-foreground')}>
                {children}
            </span>
        </td>
    )
}

/**
 * The run a process is the process of, as its reference and what it works on, opening its page: `run:41 ABC-101`,
 * `review:4 acme/web#88`, `chore:deps#2`, `task:6#6`, `epic:2#3`.
 */
function WorkChip({ work }: { work: ProcessWork }) {
    const link = 'shrink-0 font-mono text-xs text-accent underline-offset-4 hover:underline'
    const id = String(work.id)
    switch (work.kind) {
        case 'run': {
            return (
                <Link to="/workspace/runs/$id" params={{ id }} className={link} data-testid="process-work">
                    {runRef(work.id)} <span className="text-foreground">{work.ticket_key}</span>
                </Link>
            )
        }
        case 'review': {
            return (
                <Link to="/pull-requests/reviews/$id" params={{ id }} className={link} data-testid="process-work">
                    {reviewRef(work.id)}
                    {work.pr_url !== null && <span className="text-foreground"> {pullRequestLabel(work.pr_url)}</span>}
                </Link>
            )
        }
        case 'chore': {
            const name = work.chore ?? ''
            return (
                <Link to="/chores/$name/runs/$id" params={{ name, id }} className={link} data-testid="process-work">
                    {choreRunRef(name, work.id)}
                </Link>
            )
        }
        case 'task': {
            const task = String(work.task_id ?? 0)
            return (
                <Link
                    to="/tasks/$id/runs/$run"
                    params={{ id: task, run: id }}
                    className={link}
                    data-testid="process-work"
                >
                    {taskRunRef(task, work.id)}
                </Link>
            )
        }
        case 'epic': {
            const epic = String(work.epic_id ?? 0)
            return (
                <Link to="/epics/$id" params={{ id: epic }} className={link} data-testid="process-work">
                    {epicRunRef(epic, work.id)}
                </Link>
            )
        }
    }
}

// What every process kept busy together, against the cores, and over how long: `2.2 of 12 cores busy over 10 s`.
function busyText(found: HostProcesses, cores: number | null): string {
    const busy = (found.processes ?? []).reduce((sum, p) => sum + p.cpu, 0)
    const over = found.over_seconds === null ? '' : ` over ${Math.round(found.over_seconds)} s`
    const of = cores === null ? '' : ` of ${cores}`
    return `${busy.toFixed(1)}${of} cores busy${over}`
}
