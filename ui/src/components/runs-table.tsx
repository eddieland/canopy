import { Link } from '@tanstack/react-router'
import { useState } from 'react'
import type { ReactNode } from 'react'

import type { ChoreRun, ReviewSummary, Run, RunState } from '@/api/types'
import { Age } from '@/components/age'
import { ChoreLink } from '@/components/chore-link'
import { Copyable } from '@/components/copy-button'
import { Cost } from '@/components/cost'
import { Disclosure } from '@/components/disclosure'
import { LinkedText } from '@/components/linked-text'
import { None } from '@/components/none'
import { PullRequestLink } from '@/components/pull-request-link'
import { ReviewLink } from '@/components/review-link'
import { ListRow, RowLine } from '@/components/rows'
import { RunDoing } from '@/components/run-doing'
import { RunLink } from '@/components/run-link'
import { RichText, SUMMARY_LINES } from '@/components/rich-text'
import { Chip, RunDot, Word } from '@/components/status'
import { TicketLink } from '@/components/ticket-link'
import { TicketTitle } from '@/components/ticket-title'
import { Clipped, Tip } from '@/components/tip'
import { Collapsible, CollapsibleContent } from '@/components/ui/collapsible'
import { choreRunRef } from '@/lib/refs'
import { shortSha, verdictText, verdictTone } from '@/lib/reviews'
import { rowLineFrom } from '@/lib/rows'
import { RUN_TEXT } from '@/lib/run-state'
import type { SubjectRuns } from '@/lib/run-state'
import { cn } from '@/lib/utils'
import { NO_TICKET, runKind } from '@/lib/words'

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
 * Every run on the runs page, a row per subject by its latest run (`subjectRuns`): a ticket's worker run, as
 * `RunsTable` shows it, a PR's review, or a chore's run, each in the same columns, its kind in the kind's. A toggle
 * under it opens the runs before it, so a ticket that asked twice, or a PR reviewed at each push, is one row.
 */
export function SubjectRunsTable({ groups }: { groups: SubjectRuns[] }) {
    return (
        <ul className="divide-y" data-testid="runs">
            {groups.map((group) => (
                <SubjectRow key={subjectKey(group)} group={group} />
            ))}
        </ul>
    )
}

// Unique across the three kinds: a ticket's key, a PR's URL, and a chore's name are each their own namespace.
function subjectKey(group: SubjectRuns): string {
    switch (group.of) {
        case 'worker': {
            return `worker-${group.latest.ticket_key}`
        }
        case 'review': {
            return `review-${group.latest.pr_url}`
        }
        case 'chore': {
            return `chore-${group.chore}`
        }
    }
}

function RunRow({ run, ticket, ownPr }: { run: Run; ticket: boolean; ownPr: string | undefined }) {
    return (
        <ListRow kind={ticket ? 'run' : 'own-run'} className="group/copy" data-testid={`run-${run.id}`}>
            <RunBody run={run} ticket={ticket} ownPr={ownPr} />
        </ListRow>
    )
}

function SubjectRow({ group }: { group: SubjectRuns }) {
    switch (group.of) {
        case 'worker': {
            return (
                <Folding
                    testId={`run-${group.latest.id}`}
                    earlierTestId={`earlier-runs-${group.latest.ticket_key}`}
                    head={<RunBody run={group.latest} ticket />}
                    earlier={group.earlier.map((run) => (
                        <EarlierRow key={run.id} run={run} />
                    ))}
                />
            )
        }
        case 'review': {
            return (
                <Folding
                    testId={`review-${group.latest.id}`}
                    earlierTestId={`earlier-reviews-${group.latest.id}`}
                    head={<ReviewBody review={group.latest} />}
                    earlier={group.earlier.map((review) => (
                        <EarlierReviewRow key={review.id} review={review} />
                    ))}
                />
            )
        }
        case 'chore': {
            return (
                <Folding
                    testId={`chore-run-${group.chore}-${group.latest.id}`}
                    earlierTestId={`earlier-chore-runs-${group.chore}`}
                    head={<ChoreRunBody chore={group.chore} title={group.title} run={group.latest} />}
                    earlier={group.earlier.map((run) => (
                        <EarlierChoreRow key={run.id} chore={group.chore} run={run} />
                    ))}
                />
            )
        }
    }
}

/** A subject's row: its latest run's cells, then a toggle that opens its earlier runs, one line each, under it. */
function Folding({
    testId,
    earlierTestId,
    head,
    earlier,
}: {
    testId: string
    earlierTestId: string
    head: ReactNode
    earlier: ReactNode[]
}) {
    const [open, setOpen] = useState(false)
    return (
        <Collapsible asChild open={open} onOpenChange={setOpen}>
            <ListRow kind="run" className="group/copy" data-testid={testId}>
                {head}
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
                                data-testid={earlierTestId}
                            >
                                {earlier}
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

/**
 * A review on the runs page, in a worker run's columns: how its run went, its id, its ticket, `review`, its PR's
 * title, cost, and when, and under them the PR and the commit it read with what it found. Its findings are on its page.
 */
function ReviewBody({ review }: { review: ReviewSummary }) {
    return (
        <>
            <StateCell state={review.state} status={review.status} />
            <ReviewLink id={review.id} />
            <span className="truncate">
                {review.ticket_key === null ? (
                    <None reason={NO_TICKET} brief className="font-mono text-xs" />
                ) : (
                    <TicketLink ticketKey={review.ticket_key} />
                )}
            </span>
            <span className="flex min-w-0 items-center gap-3">
                <Chip word="review" />
            </span>
            <TicketTitle title={review.title} />
            <Readouts cost={review.cost_usd} started={review.started_at} ended={review.ended_at} />
            <RowLine from="title" className="flex flex-wrap items-center gap-x-3 gap-y-1">
                <PullRequestLink url={review.pr_url} />
                <ReviewFound review={review} />
            </RowLine>
        </>
    )
}

/** One of a PR's earlier reviews, on one line in the columns of the row it sits in: the PR is the row's. */
function EarlierReviewRow({ review }: { review: ReviewSummary }) {
    return (
        <ListRow kind="run" className="p-0" data-testid={`review-${review.id}`}>
            <StateCell state={review.state} status={review.status} />
            <ReviewLink id={review.id} />
            <span />
            <span className="flex min-w-0 items-center gap-3">
                <Chip word="review" />
            </span>
            <span className="flex min-w-0 items-center gap-3">
                <ReviewFound review={review} />
            </span>
            <Readouts cost={review.cost_usd} started={review.started_at} ended={review.ended_at} />
        </ListRow>
    )
}

/** The commit a review read, and what it found in the color of its worst finding. */
function ReviewFound({ review }: { review: ReviewSummary }) {
    return (
        <>
            <Tip fact={review.sha} mono>
                <span className="readout shrink-0 text-xs text-muted-foreground">at {shortSha(review.sha)}</span>
            </Tip>
            <Clipped text={verdictText(review)} className={cn('font-mono text-xs', verdictTone(review))} />
        </>
    )
}

/**
 * A chore's run on the runs page, in a worker run's columns: how it went, its number, its chore, `chore`, the chore's
 * title, cost, and when, and under them what it said. Its findings, and its runs before these, are on its chore's page.
 */
function ChoreRunBody({ chore, title, run }: { chore: string; title: string | null; run: ChoreRun }) {
    return (
        <>
            <StateCell state={run.state} status={run.status} />
            <ChoreRunNumber chore={chore} id={run.id} />
            <ChoreLink name={chore} className="truncate" />
            <span className="flex min-w-0 items-center gap-3">
                <Chip word="chore" />
            </span>
            <TicketTitle title={title} />
            <Readouts cost={run.cost_usd} started={run.started_at} ended={run.ended_at} />
            {run.summary && <RichText text={run.summary} lines={SUMMARY_LINES} className={rowLineFrom('title')} />}
        </>
    )
}

/** A chore's run before the one its row leads with, on one line: the first line of what it said. */
function EarlierChoreRow({ chore, run }: { chore: string; run: ChoreRun }) {
    const said = run.summary?.split('\n', 1)[0] ?? ''
    return (
        <ListRow kind="run" className="p-0" data-testid={`chore-run-${chore}-${run.id}`}>
            <StateCell state={run.state} status={run.status} />
            <ChoreRunNumber chore={chore} id={run.id} />
            <span />
            <span className="flex min-w-0 items-center gap-3">
                <Chip word="chore" />
            </span>
            <Clipped text={said} className="text-sm text-muted-foreground">
                <LinkedText text={said} />
            </Clipped>
            <Readouts cost={run.cost_usd} started={run.started_at} ended={run.ended_at} />
        </ListRow>
    )
}

/**
 * A chore run's number, `#2`, opening its page: its chore is named in the next column, so the two read as its
 * reference, `chore:deps#2`, which its hover gives whole.
 */
function ChoreRunNumber({ chore, id }: { chore: string; id: number }) {
    return (
        <Link
            to="/chores/$name/runs/$id"
            params={{ name: chore, id: String(id) }}
            title={choreRunRef(chore, id)}
            className="readout text-xs text-accent underline-offset-4 hover:underline"
        >
            #{id}
        </Link>
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
    return <StateCell state={run.state} status={run.status} />
}

/** A run's state cell: its dot in its state's color, and its status in the journal's word. */
function StateCell({ state, status }: { state: RunState; status: string }) {
    return (
        <span className={cn('flex items-center gap-1.5 font-mono text-xs', RUN_TEXT[state])}>
            <RunDot state={state} />
            <Word word={status} />
        </span>
    )
}

/** A run's cost and when, a cell each, in the row's `cost` and `age` columns. */
function RunReadouts({ run }: { run: Run }) {
    return <Readouts cost={run.cost_usd} started={run.started_at} ended={run.ended_at} />
}

/** Any run's cost and when, a cell each, in the row's `cost` and `age` columns. */
function Readouts({ cost, started, ended }: { cost: number | null; started: string; ended: string | null }) {
    return (
        <>
            <span className="text-right text-xs text-muted-foreground" data-testid="run-cost">
                <Cost usd={cost} />
            </span>
            <Age variant="span" started={started} ended={ended} className="text-right" />
        </>
    )
}
