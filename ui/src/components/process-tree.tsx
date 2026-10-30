import { useQuery } from '@tanstack/react-query'
import { ChevronRight, ListTree } from 'lucide-react'
import { useState } from 'react'

import { hostProcessesQuery } from '@/api/queries'
import type { HostProcesses } from '@/api/types'
import { Empty, Panel, PanelHeader, PanelSkeleton } from '@/components/panel'
import { Button } from '@/components/ui/button'
import { Toggle } from '@/components/ui/toggle'
import { bytesText } from '@/lib/host'
import { busyTree, cpuText, processCount, processRows, processTree, STATE_TEXT } from '@/lib/processes'
import type { ProcessRow } from '@/lib/processes'
import { cn } from '@/lib/utils'

// A column's head, as the reports' tables have them.
const HEAD = 'panel-label pb-1.5 pl-3 text-right font-normal whitespace-nowrap'

// A process at least this busy, half a core, reads in the foreground: it is what the operator came to find.
const HOT_CPU = 0.5

/**
 * The machine's processes as a tree, each parent over its children and the busiest first, with the processors each
 * kept busy since the server's read before and the memory it holds: what answers "what is keeping it busy?". Only the
 * busy ones and their parents show, with the loop's process, until the operator asks for every one. A parent folds to
 * one line with what it and its children add up to.
 */
export function ProcessTree({ loop, cores }: { loop: number; cores: number | null }) {
    const { data } = useQuery(hostProcessesQuery)
    const [all, setAll] = useState(false)
    return (
        <Panel data-testid="host-processes">
            <PanelHeader label="Processes">
                {data !== undefined && data.processes !== null && (
                    <span className="flex flex-wrap items-center gap-x-3 gap-y-1">
                        <span className="readout text-xs text-muted-foreground">{busyText(data, cores)}</span>
                        <Toggle
                            size="xs"
                            pressed={all}
                            onPressedChange={setAll}
                            title={all ? 'Show only the busy processes' : 'Show every process'}
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
                <Tree found={data} loop={loop} all={all} />
            )}
        </Panel>
    )
}

/** The tree's table: every process with `all`, else the busy ones, with the parents of each and the loop. */
function Tree({ found, loop, all }: { found: HostProcesses; loop: number; all: boolean }) {
    const [folded, setFolded] = useState<ReadonlySet<number>>(new Set())
    const whole = processTree(found.processes ?? [])
    const shown = all ? whole : busyTree(whole, new Set([loop]))
    const hidden = processCount(whole) - processCount(shown)
    const rows = processRows(shown, folded)
    const fold = (pid: number) => {
        setFolded((was) => {
            const next = new Set(was)
            if (!next.delete(pid)) {
                next.add(pid)
            }
            return next
        })
    }
    return (
        <div className="overflow-x-auto px-3 pb-2">
            <table className="w-full border-collapse text-sm" data-testid="process-tree">
                <thead>
                    <tr>
                        <th className="panel-label w-full pt-3 pb-1.5 text-left font-normal">process</th>
                        <th className={cn(HEAD, 'hidden pt-3 @2xl:table-cell')}>user</th>
                        <th className={cn(HEAD, 'pt-3')} title="Of one core: 100% is one core the whole time">
                            cpu
                        </th>
                        <th className={cn(HEAD, 'pt-3')}>memory</th>
                    </tr>
                </thead>
                <tbody>
                    {rows.map((row) => (
                        <Row key={row.node.process.pid} row={row} loop={loop} onFold={fold} />
                    ))}
                </tbody>
            </table>
            {hidden > 0 && (
                <p className="pt-1.5 text-xs text-muted-foreground" data-testid="process-hidden">
                    {hidden} {hidden === 1 ? 'process' : 'processes'} using under 1% of a core left out.
                </p>
            )}
        </div>
    )
}

/**
 * One process's line: a fold for its children, its name and pid, what it is doing when that is not sleeping, its
 * command line, its account, and what it uses. Folded, its figures are its own and its children's together.
 */
function Row({ row, loop, onFold }: { row: ProcessRow; loop: number; onFold: (pid: number) => void }) {
    const { node, depth, folded } = row
    const { process } = node
    const parent = node.children.length > 0
    const cpu = folded ? node.cpu : process.cpu
    const rss = folded ? node.rss : process.rss
    const state = STATE_TEXT[process.state]
    return (
        <tr className="border-t align-baseline" data-testid="process-row">
            <td className="max-w-0 py-1 pr-1">
                {/* A step in for each level; a leaf keeps the fold's place, so names line up. */}
                <div className="flex min-w-0 items-baseline gap-1.5" style={{ paddingLeft: `${depth * 0.875}rem` }}>
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
            <td
                className={cn(
                    'readout py-1 pl-3 text-right text-xs whitespace-nowrap',
                    cpu >= HOT_CPU ? 'text-foreground' : 'text-muted-foreground',
                )}
            >
                {cpuText(cpu)}
            </td>
            <td className="readout py-1 pl-3 text-right text-xs whitespace-nowrap text-muted-foreground">
                {bytesText(rss)}
            </td>
        </tr>
    )
}

// What every process kept busy together, against the cores, and over how long: `2.2 of 12 cores busy over 10 s`.
function busyText(found: HostProcesses, cores: number | null): string {
    const busy = (found.processes ?? []).reduce((sum, p) => sum + p.cpu, 0)
    const over = found.over_seconds === null ? '' : ` over ${Math.round(found.over_seconds)} s`
    const of = cores === null ? '' : ` of ${cores}`
    return `${busy.toFixed(1)}${of} cores busy${over}`
}
