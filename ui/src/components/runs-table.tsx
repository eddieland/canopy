import { useState } from 'react'

import type { Run } from '@/api/types'
import { Age } from '@/components/age'
import { Copyable } from '@/components/copy-button'
import { Cost } from '@/components/cost'
import { Disclosure } from '@/components/disclosure'
import { LinkedText } from '@/components/linked-text'
import { PullRequestLink } from '@/components/pull-request-link'
import { ListRow, RowLine } from '@/components/rows'
import { RunDoing } from '@/components/run-doing'
import { RunLink } from '@/components/run-link'
import { RichText, SUMMARY_LINES } from '@/components/rich-text'
import { Chip, RunDot, Word } from '@/components/status'
import { TicketLink } from '@/components/ticket-link'
import { TicketTitle } from '@/components/ticket-title'
import { Clipped, Tip } from '@/components/tip'
import { Collapsible, CollapsibleContent } from '@/components/ui/collapsible'
import { rowLineFrom } from '@/lib/rows'
import { RUN_TEXT } from '@/lib/run-state'
import type { TicketRuns } from '@/lib/run-state'
import { cn } from '@/lib/utils'
import { runKind } from '@/lib/words'

// A run's worktrees named in its row before `+N more`: three repositories' worth, on one line in most panels.
const WORKTREES_SHOWN = 3

/**
 * Runs, one row each: state, the run's id (opening its page), the ticket, the run's kind, the ticket's title, cost,
 * when, and what it said, or while it runs, its latest tool call. `ticket` leaves out the ticket and its title, for a
 * ticket's own page; `ownPr` leaves out the PR whose page it is, among those a run pushed to.
 */
export function RunsTable({ runs, ticket = true, ownPr }: { runs: Run[]; ticket?: boolean; ownPr?: string }) {
    return (
        <ul className="divide-y" data-testid="runs">
            {runs.map((run) => (
                <RunRow key={run.id} run={run} ticket={ticket} ownPr={ownPr} />
            ))}
        </ul>
    )
}

/**
 * Runs grouped by ticket, one row each: the ticket's latest run, as `RunsTable` shows it, and a toggle that opens the
 * runs before it, so a ticket that asked twice is one row.
 */
export function TicketRunsTable({ groups }: { groups: TicketRuns[] }) {
    return (
        <ul className="divide-y" data-testid="runs">
            {groups.map((group) => (
                <TicketRow key={group.latest.ticket_key} group={group} />
            ))}
        </ul>
    )
}

function RunRow({ run, ticket, ownPr }: { run: Run; ticket: boolean; ownPr: string | undefined }) {
    return (
        <ListRow kind={ticket ? 'run' : 'own-run'} className="group/copy" data-testid={`run-${run.id}`}>
            <RunBody run={run} ticket={ticket} ownPr={ownPr} />
        </ListRow>
    )
}

function TicketRow({ group }: { group: TicketRuns }) {
    const [open, setOpen] = useState(false)
    const { latest, earlier } = group
    return (
        <Collapsible asChild open={open} onOpenChange={setOpen}>
            <ListRow kind="run" className="group/copy" data-testid={`run-${latest.id}`}>
                <RunBody run={latest} ticket />
                {earlier.length > 0 && (
                    <>
                        <RowLine from="title">
                            <Disclosure
                                open={open}
                                what={`${earlier.length} earlier ${earlier.length === 1 ? 'run' : 'runs'}`}
                                // In line with the title above it, and no taller than a line of text.
                                className="-my-1 -ml-2"
                            />
                        </RowLine>
                        <CollapsibleContent asChild>
                            <ul
                                className={cn('flex flex-col gap-1.5 pt-1', rowLineFrom('state'))}
                                data-testid={`earlier-runs-${latest.ticket_key}`}
                            >
                                {earlier.map((run) => (
                                    <EarlierRow key={run.id} run={run} />
                                ))}
                            </ul>
                        </CollapsibleContent>
                    </>
                )}
            </ListRow>
        </Collapsible>
    )
}

/**
 * One of a ticket's earlier runs, on one line in the columns of the row it sits in: its state, its id, its chips, the
 * first line of what it said where the title is, cost, and when. The rest is on the run's page.
 */
function EarlierRow({ run }: { run: Run }) {
    const said = run.summary?.split('\n', 1)[0] ?? ''
    return (
        <ListRow kind="run" className="p-0" data-testid={`run-${run.id}`}>
            <RunStatus run={run} />
            <RunLink id={run.id} />
            <span />
            <RunChips run={run} />
            <Clipped text={said} className="text-sm text-muted-foreground">
                <LinkedText text={said} />
            </Clipped>
            <RunReadouts run={run} />
        </ListRow>
    )
}

function RunBody({ run, ticket, ownPr }: { run: Run; ticket: boolean; ownPr?: string | undefined }) {
    // What goes under the head line starts under the ticket's title, or under the run's id on its subject's page.
    const under = ticket ? 'title' : 'facts'
    // On a PR's page, the PR is its title: its rows name only the others a run pushed to.
    const prs = run.prs.filter((pr) => pr !== ownPr)
    return (
        <>
            <RunStatus run={run} />
            {ticket ? (
                <>
                    <RunLink id={run.id} />
                    <TicketLink ticketKey={run.ticket_key} className="truncate" />
                    <RunChips run={run} />
                    <TicketTitle title={run.ticket_title} />
                </>
            ) : (
                // On its subject's page the id leads the free column at a fixed width, so the chips still line up.
                <span className="flex items-center gap-3">
                    <RunLink id={run.id} className="w-14" />
                    <RunChips run={run} />
                </span>
            )}
            <RunReadouts run={run} />
            {run.summary && <RichText text={run.summary} lines={SUMMARY_LINES} className={rowLineFrom(under)} />}
            {run.activity && (
                <RowLine from={under}>
                    <RunDoing activity={run.activity} />
                </RowLine>
            )}
            {(prs.length > 0 || run.worktrees.length > 0 || run.session_id) && (
                <RowLine from={under} className="flex flex-wrap items-center gap-x-4 gap-y-1 font-mono text-xs">
                    {prs.map((pr) => (
                        <PullRequestLink key={pr} url={pr} />
                    ))}
                    <RunWorktrees paths={run.worktrees} />
                    {run.session_id && (
                        <Copyable text={run.session_id} label="session id" reveal className="text-muted-foreground">
                            <span title="its transcript is on the run's page">session {run.session_id}</span>
                        </Copyable>
                    )}
                </RowLine>
            )}
        </>
    )
}

/**
 * The worktrees a run holds, one per repository it works in: the first three, then how many more, every one in a tip.
 * A ticket across many repositories holds a slot in each, and its run's page lists them all. One more is named rather
 * than counted, since `+1 more` would take the room its path does.
 */
function RunWorktrees({ paths }: { paths: string[] }) {
    const shown = paths.length > WORKTREES_SHOWN + 1 ? paths.slice(0, WORKTREES_SHOWN) : paths
    const more = paths.length - shown.length
    return (
        <>
            {shown.map((path) => (
                <span key={path} className="text-muted-foreground" title="the worktree it holds">
                    {path}
                </span>
            ))}
            {more > 0 && (
                <Tip fact={`the worktrees it holds:\n${paths.join('\n')}`} mono>
                    <span className="text-muted-foreground" data-testid="run-worktrees-more">
                        +{more} more {more === 1 ? 'worktree' : 'worktrees'}
                    </span>
                </Tip>
            )}
        </>
    )
}

/** A run's chips: its kind, with a resume's reasons, and `private` for a private ticket's. */
function RunChips({ run }: { run: Run }) {
    return (
        <span className="flex min-w-0 items-center gap-3">
            <Chip word={runKind(run)} className="min-w-0 shrink" />
            {run.private && <Chip>private</Chip>}
        </span>
    )
}

function RunStatus({ run }: { run: Run }) {
    return (
        <span className={cn('flex items-center gap-1.5 font-mono text-xs', RUN_TEXT[run.state])}>
            <RunDot state={run.state} />
            <Word word={run.status} />
        </span>
    )
}

/** A run's cost and when, a cell each, in the row's `cost` and `age` columns. */
function RunReadouts({ run }: { run: Run }) {
    return (
        <>
            <span className="text-right text-xs text-muted-foreground" data-testid="run-cost">
                <Cost usd={run.cost_usd} />
            </span>
            <Age variant="span" started={run.started_at} ended={run.ended_at} className="text-right" />
        </>
    )
}
