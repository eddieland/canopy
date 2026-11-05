import type { EpicDetail, EpicEntry, EpicMember } from '@/api/types'
import { Age } from '@/components/age'
import { Code } from '@/components/code'
import { OutlineId } from '@/components/epic-ids'
import { Notice } from '@/components/notice'
import { Empty, Panel, PanelHeader } from '@/components/panel'
import { Chip, RunDot, Word } from '@/components/status'
import { TicketLink } from '@/components/ticket-link'
import { TicketTitle } from '@/components/ticket-title'
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from '@/components/ui/table'
import { useLit } from '@/hooks/use-outline-lights'
import { citedBy, cites, unplaced } from '@/lib/epics'
import { phaseMeaning } from '@/lib/meanings'
import { epicRunRef } from '@/lib/refs'
import { cn } from '@/lib/utils'

// What the board's marks mean, in their tips: which plan the breakdown is read from.
const PROPOSED =
    'Read from the plan waiting on you: approve it, or reply with what to change. No ticket is registered against it ' +
    'until it is approved.'
const APPROVED = 'Read from the plan you approved: register each ticket you file against the entries it fulfils.'

// A cell of the board: its room, and its top edge, so a cell of several lines reads from its first.
const CELL = 'px-3 py-2.5 align-top'
// A cell that keeps to one line where the board has room, and wraps in a narrow window, where its row stays one row.
const ONE_LINE = '@4xl:whitespace-nowrap'
// A column's head, on the board's left edge as its cells are.
const HEAD = 'px-3 pt-2.5 text-left align-bottom'

/**
 * An epic's breakdown (DESIGN §43), its page's focal panel: a row per entry in the plan's order, each with its id and
 * title, its trivial mark with the reason in its tip, the requirements it covers, the contracts it provides and uses,
 * its repositories, the entries it comes after, and the members that fulfil it, or `none yet`, so the plan shows
 * what is left to file. Before an approval it is the proposed plan's, marked so; with no plan yet it is one line naming
 * the plan run at work, or why none is; a plan that does not read is its problem. Under it, the members the breakdown
 * does not place: those of no entry, and those registered against entries the approved plan dropped. Every title and
 * text is the planner's, rendered as text. A row wraps its cells in a narrow window, and stays one row.
 */
export function EpicBoard({ detail }: { detail: EpicDetail }) {
    const { outline } = detail
    const entries = outline?.problem === null ? outline.entries : []
    const members = new Map(detail.members.map((member) => [member.key, member]))
    return (
        <Panel data-testid="epic-board">
            <PanelHeader label="Breakdown">
                {outline !== null && (
                    <span className="flex items-center gap-2">
                        {outline.source === 'proposed' ? (
                            <Chip tone="blocked" word="proposed" meaning={PROPOSED} />
                        ) : (
                            <Chip word="approved" meaning={APPROVED} />
                        )}
                        {outline.problem === null && (
                            <span className="readout text-xs text-muted-foreground">{entries.length}</span>
                        )}
                    </span>
                )}
            </PanelHeader>
            {outline === null ? (
                <NoPlan detail={detail} />
            ) : outline.problem === null ? (
                <Table className="w-full" data-testid="breakdown">
                    <TableHeader>
                        <TableRow className="border-b">
                            <TableHead className={cn(HEAD, 'w-full')}>Entry</TableHead>
                            <TableHead className={HEAD}>Covers</TableHead>
                            <TableHead className={HEAD}>Provides</TableHead>
                            <TableHead className={HEAD}>Uses</TableHead>
                            <TableHead className={HEAD}>Repositories</TableHead>
                            <TableHead className={HEAD}>After</TableHead>
                            <TableHead className={HEAD}>Members</TableHead>
                        </TableRow>
                    </TableHeader>
                    <TableBody className="divide-y">
                        {entries.map((entry) => (
                            <EntryRow
                                key={entry.id}
                                entry={entry}
                                entries={entries}
                                members={entry.members.map((key) => members.get(key) ?? stranger(key))}
                            />
                        ))}
                    </TableBody>
                </Table>
            ) : (
                <Notice error={outline.problem} subject="its plan does not read" className="p-3" />
            )}
            <Unplaced members={detail.members} />
        </Panel>
    )
}

/**
 * The board with no plan to read yet: one line naming the plan run at work, or, with none working, what starts the
 * next or why none starts.
 */
function NoPlan({ detail }: { detail: EpicDetail }) {
    const { epic, runs, max_plan_attempts: limit } = detail
    const working = runs.find((run) => run.status === 'running')
    if (working !== undefined) {
        return (
            <p className="flex items-center gap-2 px-3 py-2.5 text-sm" data-testid="plan-run-working">
                <RunDot state="running" />
                <span>
                    <span className="readout text-xs">{epicRunRef(epic.id, working.id)}</span> is writing its plan
                </span>
                <Age variant="span" started={working.started_at} ended={null} className="ml-auto" />
            </p>
        )
    }
    if (epic.standing !== 'unplanned') {
        return <Empty>no plan yet: the next tick starts its plan run</Empty>
    }
    if (runs.length >= limit) {
        return (
            <Empty>
                no plan: its {runs.length} plan runs, <Code>policy.max_plan_attempts</Code>, ended without one
            </Empty>
        )
    }
    return <Empty>no plan yet: its plan runs ended without one, and a reply starts the next</Empty>
}

/** A breakdown's entry, lit while an id it cites, or its own, is pointed at; `entries` are its breakdown's. */
function EntryRow({
    entry,
    entries,
    members,
}: {
    entry: EpicEntry
    entries: readonly EpicEntry[]
    members: EpicMember[]
}) {
    const lit = useLit()
    const on = lit !== null && cites(entry, lit)
    return (
        <TableRow
            data-testid={`entry-${entry.id}`}
            data-lit={on ? '' : undefined}
            className={cn(
                'motion-safe:transition-colors motion-safe:duration-150 motion-safe:ease-out',
                on && 'bg-accent/10',
            )}
        >
            <TableCell className={CELL}>
                <span className="flex flex-wrap items-baseline gap-x-2 gap-y-1">
                    {/* Its title is beside it, so its tip says what comes after it. */}
                    <OutlineId id={entry.id} fact={citedBy(entries, entry.id)} className="-ml-1" />
                    <span className="text-sm font-medium wrap-break-word">{entry.title}</span>
                    {entry.trivial !== null && <Chip word="trivial" meaning={entry.trivial} />}
                </span>
            </TableCell>
            <TableCell className={CELL}>
                <Ids ids={entry.covers} />
            </TableCell>
            <TableCell className={CELL}>
                <Ids ids={entry.provides} />
            </TableCell>
            <TableCell className={CELL}>
                <Ids ids={entry.uses} />
            </TableCell>
            <TableCell className={cn(CELL, ONE_LINE, 'font-mono text-muted-foreground')}>
                {entry.repos.length === 0 ? <span>none</span> : entry.repos.join(', ')}
            </TableCell>
            <TableCell className={CELL}>
                <Ids ids={entry.after} />
            </TableCell>
            <TableCell className={CELL}>
                {members.length === 0 ? (
                    <span className="text-muted-foreground">none yet</span>
                ) : (
                    <ul className="flex flex-col gap-1">
                        {members.map((member) => (
                            <li key={member.key}>
                                <MemberLine member={member} />
                            </li>
                        ))}
                    </ul>
                )}
            </TableCell>
        </TableRow>
    )
}

/** A cell's ids, each lit where it is pointed at, or `none`. */
function Ids({ ids }: { ids: readonly string[] }) {
    if (ids.length === 0) {
        return <span className="text-muted-foreground">none</span>
    }
    return (
        <span className="-ml-1 flex flex-wrap gap-x-0.5 gap-y-1 @4xl:flex-nowrap">
            {ids.map((id) => (
                <OutlineId key={id} id={id} />
            ))}
        </span>
    )
}

/**
 * A member as the board names it: its latest run's dot, its key opening its page, and its phase, muted. One with no
 * run yet keeps the dot's room, so the keys line up.
 */
function MemberLine({ member }: { member: EpicMember }) {
    return (
        <span className={cn('flex flex-wrap items-center gap-x-1.5 gap-y-0.5', ONE_LINE, '@4xl:flex-nowrap')}>
            {/* The dot stays with the key it is the run of; the phase wraps under them in a narrow window. */}
            <span className="flex items-center gap-1.5 whitespace-nowrap">
                {member.latest_run === null ? (
                    <span aria-hidden className="size-2 shrink-0" />
                ) : (
                    <RunDot state={member.latest_run.state} />
                )}
                <TicketLink ticketKey={member.key} />
            </span>
            {member.phase !== null && (
                <Word word={member.phase} meaning={phaseMeaning(member.phase)} className="text-muted-foreground" />
            )}
        </span>
    )
}

/**
 * The members the board has no row for, under it: those registered against no entry, each with its title, since no
 * entry names what it is for; and those registered against an entry the approved plan no longer holds, with the
 * entries it lost. Neither shows while it has none.
 */
function Unplaced({ members }: { members: readonly EpicMember[] }) {
    const { none, dropped } = unplaced(members)
    return (
        <>
            {none.length > 0 && (
                <section className="flex flex-col gap-2 border-t px-3 py-2.5" data-testid="members-of-no-entry">
                    <h3 className="panel-label">Members of no entry</h3>
                    <ul className="flex flex-col gap-1.5 text-xs">
                        {none.map((member) => (
                            <li key={member.key} className="flex min-w-0 items-center gap-3">
                                <MemberLine member={member} />
                                <TicketTitle title={member.title ?? null} />
                            </li>
                        ))}
                    </ul>
                </section>
            )}
            {dropped.length > 0 && (
                <section className="flex flex-col gap-2 border-t px-3 py-2.5" data-testid="members-of-dropped-entries">
                    <h3 className="panel-label">Members of dropped entries</h3>
                    <ul className="flex flex-col gap-1.5 text-xs">
                        {dropped.map((member) => (
                            <li key={member.key} className="flex min-w-0 flex-wrap items-center gap-x-3 gap-y-0.5">
                                <MemberLine member={member} />
                                <span className="text-muted-foreground">
                                    registered against <span className="readout">{member.dropped.join(', ')}</span>,
                                    which the approved plan no longer holds
                                </span>
                            </li>
                        ))}
                    </ul>
                </section>
            )}
        </>
    )
}

/** A member the entry names that the epic's members do not hold: its key alone, with no phase or run to show. */
function stranger(key: string): EpicMember {
    return {
        key,
        title: null,
        entries: [],
        dropped: [],
        added_at: '',
        added_channel: '',
        phase: null,
        prs: [],
        latest_run: null,
    }
}
