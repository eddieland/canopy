import { Link } from '@tanstack/react-router'
import { Plus } from 'lucide-react'
import { useState } from 'react'
import type { ReactNode } from 'react'

import type { EpicDetail, EpicEntry, EpicMember } from '@/api/types'
import { Age } from '@/components/age'
import { Code } from '@/components/code'
import { OutlineId } from '@/components/epic-ids'
import { MemberForm, RemoveButton, RemoveQuestion } from '@/components/epic-members'
import { Notice } from '@/components/notice'
import { Empty, Panel, PanelFooter, PanelHeader } from '@/components/panel'
import { Chip, RunDot, Word } from '@/components/status'
import { TicketLink } from '@/components/ticket-link'
import { TicketTitle } from '@/components/ticket-title'
import { Button } from '@/components/ui/button'
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from '@/components/ui/table'
import { useLit } from '@/hooks/use-outline-lights'
import { citedBy, cites, memberChoices, unplaced } from '@/lib/epics'
import type { MemberOpen } from '@/lib/epics'
import { phaseMeaning } from '@/lib/meanings'
import { epicRef, epicRunRef } from '@/lib/refs'
import { cn } from '@/lib/utils'

// What the board's marks mean, in their tips: which plan the breakdown is read from.
const PROPOSED =
    'Read from the plan waiting on you: approve it, or reply with what to change. No ticket is registered against it ' +
    'until it is approved. Opens the plan.'
const APPROVED =
    'Read from the plan you approved: register each ticket you file against the entries it fulfils. Opens the plan.'

// A cell of the board: its room, and its top edge, so a cell of several lines reads from its first.
const CELL = 'px-3 py-2.5 align-top'
// A cell that keeps to one line where the board has room, and wraps in a narrow window, where its row stays one row.
const ONE_LINE = '@4xl:whitespace-nowrap'
// A column's head, on the board's left edge as its cells are.
const HEAD = 'px-3 pt-2.5 text-left align-bottom'
// How many columns the board has, which a row opened under an entry spans.
const COLUMNS = 7

/**
 * The operator's word on the board's members: what it has open, one thing at a time, and what the last write said,
 * which its foot keeps. `entries` are those a ticket can be registered against now, and `members` the epic's keys.
 */
interface Acts {
    epic: number
    open: MemberOpen
    setOpen: (open: MemberOpen) => void
    done: (said: string) => void
    entries: readonly EpicEntry[]
    why: string | null
    members: readonly string[]
}

/**
 * An epic's breakdown (DESIGN §43), its page's focal panel: a row per entry in the plan's order, each with its id and
 * title, its trivial mark with the reason in its tip, the requirements it covers, the contracts it provides and uses,
 * its repositories, the entries it comes after, and the members that fulfil it, or `none yet`, so the plan shows
 * what is left to file. Before an approval it is the proposed plan's, marked so; with no plan yet it is one line naming
 * the plan run at work, or why none is; a plan that does not read is its problem. Under it, the members the breakdown
 * does not place: those of no entry, and those registered against entries the approved plan dropped. Every title and
 * text is the planner's, rendered as text. A row wraps its cells in a narrow window, and stays one row.
 *
 * The operator registers and removes members on it, as `canopy epic add` and `remove` do: an entry of the approved
 * plan with no member offers Register a ticket, a form opened under its row with it picked; its foot offers Add a
 * ticket, for several entries or none, and before any plan is approved for none alone; and a member offers Remove,
 * which asks first, under the row or line it was asked from. What the last of them did stays in the foot.
 */
export function EpicBoard({ detail }: { detail: EpicDetail }) {
    const { outline } = detail
    const entries = outline?.problem === null ? outline.entries : []
    const members = new Map(detail.members.map((member) => [member.key, member]))
    const [open, setOpen] = useState<MemberOpen>(null)
    const [said, setSaid] = useState<string | null>(null)
    const acts: Acts = {
        epic: detail.epic.id,
        open,
        setOpen: (next) => {
            setSaid(null)
            setOpen(next)
        },
        done: (words) => {
            setOpen(null)
            setSaid(words)
        },
        ...memberChoices(detail),
        members: detail.members.map((member) => member.key),
    }
    return (
        <Panel data-testid="epic-board">
            <PanelHeader label="Breakdown">
                {outline !== null && (
                    <span className="flex items-center gap-2">
                        {/* The mark opens the plan it names, on its page. */}
                        <Link
                            to="/epics/$id/plan"
                            params={{ id: String(detail.epic.id) }}
                            aria-label={`Open the ${outline.source} plan`}
                            className="rounded-sm"
                        >
                            {outline.source === 'proposed' ? (
                                <Chip tone="blocked" word="proposed" meaning={PROPOSED} />
                            ) : (
                                <Chip word="approved" meaning={APPROVED} />
                            )}
                        </Link>
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
                                acts={outline.source === 'approved' ? acts : null}
                            />
                        ))}
                    </TableBody>
                </Table>
            ) : (
                <Notice error={outline.problem} subject="its plan does not read" className="p-3" />
            )}
            <Unplaced members={detail.members} rows={outline?.problem === null} acts={acts} />
            <PanelFooter data-testid="members-foot">
                {open?.kind === 'add' ? (
                    <MemberForm
                        epic={acts.epic}
                        entries={acts.entries}
                        why={acts.why}
                        picked={[]}
                        members={acts.members}
                        onDone={acts.done}
                        onCancel={() => acts.setOpen(null)}
                    />
                ) : (
                    <span>
                        <Button
                            variant="outline"
                            onClick={() => acts.setOpen({ kind: 'add' })}
                            title={`canopy epic add ${epicRef(acts.epic)} KEY`}
                        >
                            <Plus />
                            Add a ticket
                        </Button>
                    </span>
                )}
                <Notice>{said}</Notice>
            </PanelFooter>
        </Panel>
    )
}

/**
 * An epic with no plan to read yet, in one line: the plan run at work, or, with none working, what starts the next or
 * why none starts. Its board says it, and so does its plan's page.
 */
export function NoPlan({ detail }: { detail: EpicDetail }) {
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

/**
 * A breakdown's entry, lit while an id it cites, or its own, is pointed at; `entries` are its breakdown's. With `acts`,
 * the approved plan's, it offers Register a ticket while no member fulfils it and Remove on each member, and what one
 * opens takes a row of its own under it, at the board's width.
 */
function EntryRow({
    entry,
    entries,
    members,
    acts,
}: {
    entry: EpicEntry
    entries: readonly EpicEntry[]
    members: EpicMember[]
    acts: Acts | null
}) {
    const lit = useLit()
    const on = lit !== null && cites(entry, lit)
    const open = acts?.open ?? null
    const opened = open !== null && open.kind !== 'add' && open.at === entry.id
    return (
        <>
            <TableRow
                data-testid={`entry-${entry.id}`}
                data-lit={on ? '' : undefined}
                className={cn(
                    'motion-safe:transition-colors motion-safe:duration-150 motion-safe:ease-out',
                    on && 'bg-accent/10',
                    // What it opened reads as its own: no hairline between them.
                    opened && 'border-b-0',
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
                        <span className={cn('flex items-center gap-2', ONE_LINE)}>
                            <span className="whitespace-nowrap text-muted-foreground">none yet</span>
                            {acts !== null && (
                                <Button
                                    variant="ghost"
                                    size="xs"
                                    aria-expanded={opened}
                                    onClick={() => acts.setOpen({ kind: 'register', at: entry.id })}
                                    title={`canopy epic add ${epicRef(acts.epic)} KEY --entry ${entry.id}`}
                                >
                                    <Plus />
                                    Register a ticket
                                </Button>
                            )}
                        </span>
                    ) : (
                        <ul className="flex flex-col gap-1">
                            {members.map((member) => (
                                <li key={member.key}>
                                    <MemberLine
                                        member={member}
                                        remove={acts === null ? null : removing(acts, member.key, entry.id)}
                                    />
                                </li>
                            ))}
                        </ul>
                    )}
                </TableCell>
            </TableRow>
            {acts !== null && opened && (
                <TableRow className="hover:bg-transparent" data-testid={`entry-${entry.id}-open`}>
                    <TableCell colSpan={COLUMNS} className="px-3 pt-0.5 pb-3">
                        {open.kind === 'register' ? (
                            <MemberForm
                                epic={acts.epic}
                                entries={acts.entries}
                                why={acts.why}
                                picked={[entry.id]}
                                members={acts.members}
                                onDone={acts.done}
                                onCancel={() => acts.setOpen(null)}
                            />
                        ) : (
                            <RemoveQuestion
                                epic={acts.epic}
                                member={open.key}
                                onDone={acts.done}
                                onCancel={() => acts.setOpen(null)}
                            />
                        )}
                    </TableCell>
                </TableRow>
            )}
        </>
    )
}

/** A member's Remove, asking under `at`, the entry's row or the list it shows in. */
function removing(acts: Acts, key: string, at: string): ReactNode {
    return (
        <RemoveButton
            member={key}
            asking={asks(acts, key, at)}
            onAsk={() => acts.setOpen({ kind: 'remove', key, at })}
        />
    )
}

/** Whether `acts` asks, under `at`, before member `key` is removed. */
function asks(acts: Acts, key: string, at: string): boolean {
    const { open } = acts
    return open?.kind === 'remove' && open.key === key && open.at === at
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
 * A member as the board names it: its latest run's dot, its key opening its page, and its phase, muted, then `remove`,
 * its Remove, where the operator may remove it. One with no run yet keeps the dot's room, so the keys line up.
 */
function MemberLine({ member, remove = null }: { member: EpicMember; remove?: ReactNode }) {
    return (
        <span
            className={cn('group/member flex flex-wrap items-center gap-x-1.5 gap-y-0.5', ONE_LINE, '@4xl:flex-nowrap')}
        >
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
            {remove}
        </span>
    )
}

/**
 * The members the board has no row for, under it: while it has no rows (`rows` false), those registered against its
 * entries, with them, so a plan that does not read hides no member; those registered against no entry, each with its
 * title, since no entry names what it is for; and those registered against an entry the approved plan no longer holds,
 * with the entries it lost. None shows while it has none. Each offers Remove, which asks under its line.
 */
function Unplaced({ members, rows, acts }: { members: readonly EpicMember[]; rows: boolean; acts: Acts }) {
    const { none, dropped, registered } = unplaced(members, rows)
    // A member's line, its Remove, and the question under it while asked; `at` names the list.
    const line = (member: EpicMember, at: string, said: ReactNode, wrap = true) => (
        <li key={member.key} className="flex flex-col gap-1.5">
            <span className={cn('flex min-w-0 items-center', wrap ? 'flex-wrap gap-x-3 gap-y-0.5' : 'gap-3')}>
                <MemberLine member={member} remove={removing(acts, member.key, at)} />
                {said}
            </span>
            {asks(acts, member.key, at) && (
                <RemoveQuestion
                    epic={acts.epic}
                    member={member.key}
                    onDone={acts.done}
                    onCancel={() => acts.setOpen(null)}
                />
            )}
        </li>
    )
    return (
        <>
            {registered.length > 0 && (
                <section className="flex flex-col gap-2 border-t px-3 py-2.5" data-testid="members-of-entries">
                    <h3 className="panel-label">Members of its entries</h3>
                    <ul className="flex flex-col gap-1.5 text-xs">
                        {registered.map((member) =>
                            line(
                                member,
                                'registered',
                                <span className="text-muted-foreground">
                                    registered against <span className="readout">{member.entries.join(', ')}</span>
                                </span>,
                            ),
                        )}
                    </ul>
                </section>
            )}
            {none.length > 0 && (
                <section className="flex flex-col gap-2 border-t px-3 py-2.5" data-testid="members-of-no-entry">
                    <h3 className="panel-label">Members of no entry</h3>
                    <ul className="flex flex-col gap-1.5 text-xs">
                        {none.map((member) =>
                            line(member, 'none', <TicketTitle title={member.title ?? null} />, false),
                        )}
                    </ul>
                </section>
            )}
            {dropped.length > 0 && (
                <section className="flex flex-col gap-2 border-t px-3 py-2.5" data-testid="members-of-dropped-entries">
                    <h3 className="panel-label">Members of dropped entries</h3>
                    <ul className="flex flex-col gap-1.5 text-xs">
                        {dropped.map((member) =>
                            line(
                                member,
                                'dropped',
                                <span className="text-muted-foreground">
                                    registered against <span className="readout">{member.dropped.join(', ')}</span>,
                                    which the approved plan no longer holds
                                </span>,
                            ),
                        )}
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
