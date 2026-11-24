// What a reference's hover card shows (ui/DESIGN.md, "A link's page at a glance is a hover card"): one card per kind
// of thing canopy names, each reading the same query its page reads, once the card opens, so the page it previews is
// already read when the link is followed. A card holds no link and no control: it is a preview, never a place to act.
import { useQuery } from '@tanstack/react-query'
import type { ReactNode } from 'react'

import {
    choreQuery,
    choreRunQuery,
    epicQuery,
    pullRequestQuery,
    reviewQuery,
    runQuery,
    taskQuery,
    taskRunQuery,
    tickDetailQuery,
    ticketQuery,
} from '@/api/queries'
import type {
    ChoreDetail,
    ChoreRunDetail,
    EpicDetail,
    PullRequestDetail,
    ReviewDetail,
    Run,
    RunState,
    TaskDetail,
    TaskRunDetail,
    Tick,
    TicketDetail,
} from '@/api/types'
import { CardRow, CardRows, CardWords, GlanceCard } from '@/components/glance'
import { Word } from '@/components/status'
import { Skeleton } from '@/components/ui/skeleton'
import { cadenceText, choreLine, findingsText, windowText } from '@/lib/chores'
import { useClock } from '@/lib/clock'
import { costText, countedText } from '@/lib/cost-total'
import { counted } from '@/lib/descriptions'
import { EPIC_LOOK, entriesFiled, epicTitle } from '@/lib/epics'
import { phaseLabel } from '@/lib/phase'
import { pullRequestLabel } from '@/lib/pull-request-label'
import { readFailure } from '@/lib/read-failure'
import { choreRef, choreRunRef, epicRef, reviewRef, runRef, taskRef, taskRunRef, tickRef } from '@/lib/refs'
import { shortSha, verdictText, verdictTone } from '@/lib/reviews'
import { RUN_TEXT, asksYou } from '@/lib/run-state'
import { TASK_LOOK, taskTitle } from '@/lib/tasks'
import { TICK_TONE, tickState } from '@/lib/ticks'
import { age, lasted, stamp, useNow } from '@/lib/time'
import { tokenCount } from '@/lib/transcript'
import { NO_TICKET, readable, runKind } from '@/lib/words'

/** A run at a glance, read when its card opens: `RunCard`. */
export function RunGlance({ id }: { id: number }) {
    const read = useQuery(runQuery(id))
    return read.data === undefined ? <Unread title={runRef(id)} error={read.error} /> : <RunCard run={read.data} />
}

/** A ticket at a glance, read when its card opens: `TicketCard`. */
export function TicketGlance({ ticketKey }: { ticketKey: string }) {
    const read = useQuery(ticketQuery(ticketKey))
    return read.data === undefined ? <Unread title={ticketKey} error={read.error} /> : <TicketCard detail={read.data} />
}

/** A tick at a glance, read when its card opens: `TickCard`. */
export function TickGlance({ id }: { id: number }) {
    const read = useQuery(tickDetailQuery(id))
    return read.data === undefined ? (
        <Unread title={tickRef(id)} error={read.error} />
    ) : (
        <TickCard tick={read.data.tick} />
    )
}

/** A task at a glance, read when its card opens: `TaskCard`. */
export function TaskGlance({ id }: { id: number }) {
    const read = useQuery(taskQuery(id))
    return read.data === undefined ? <Unread title={taskRef(id)} error={read.error} /> : <TaskCard detail={read.data} />
}

/** One run of a task at a glance, read when its card opens: `TaskRunCard`. */
export function TaskRunGlance({ task, run }: { task: number; run: number }) {
    const read = useQuery(taskRunQuery(task, run))
    return read.data === undefined ? (
        <Unread title={taskRunRef(task, run)} error={read.error} />
    ) : (
        <TaskRunCard detail={read.data} />
    )
}

/** A review at a glance, read when its card opens: `ReviewCard`. */
export function ReviewGlance({ id }: { id: number }) {
    const read = useQuery(reviewQuery(id))
    return read.data === undefined ? (
        <Unread title={reviewRef(id)} error={read.error} />
    ) : (
        <ReviewCard detail={read.data} />
    )
}

/** An epic at a glance, read when its card opens: `EpicCard`. */
export function EpicGlance({ id }: { id: number }) {
    const read = useQuery(epicQuery(id))
    return read.data === undefined ? <Unread title={epicRef(id)} error={read.error} /> : <EpicCard detail={read.data} />
}

/** A chore at a glance, read when its card opens: `ChoreCard`. */
export function ChoreGlance({ name }: { name: string }) {
    const read = useQuery(choreQuery(name))
    return read.data === undefined ? (
        <Unread title={choreRef(name)} error={read.error} />
    ) : (
        <ChoreCard detail={read.data} />
    )
}

/** One run of a chore at a glance, read when its card opens: `ChoreRunCard`. */
export function ChoreRunGlance({ name, id }: { name: string; id: number }) {
    const read = useQuery(choreRunQuery(name, id))
    return read.data === undefined ? (
        <Unread title={choreRunRef(name, id)} error={read.error} />
    ) : (
        <ChoreRunCard detail={read.data} />
    )
}

/** A PR at a glance, read when its card opens: `PullRequestCard`. */
export function PullRequestGlance({ url }: { url: string }) {
    const read = useQuery(pullRequestQuery(url))
    return read.data === undefined ? (
        <Unread title={pullRequestLabel(url)} error={read.error} />
    ) : (
        <PullRequestCard detail={read.data} />
    )
}

/**
 * A run at a glance: how it stands, the ticket it works, what it is doing or what it said, when it ran, what it cost,
 * and the PRs it named.
 */
export function RunCard({ run }: { run: Run }) {
    const asks = asksYou(run)
    const words = run.state === 'running' ? (run.card?.summary ?? run.activity?.did ?? null) : run.summary
    return (
        <GlanceCard
            title={runRef(run.id)}
            state={asks ? 'blocked' : run.state}
            aside={
                asks ? (
                    <span className={RUN_TEXT.blocked}>waiting on you</span>
                ) : (
                    <Stands state={run.state} word={run.status} />
                )
            }
            name={run.ticket_title}
            foot={null}
        >
            {words !== null && words !== '' && <CardWords>{words}</CardWords>}
            <CardRows>
                <CardRow label="Ticket">
                    <span className="font-mono">{run.ticket_key}</span>
                </CardRow>
                <CardRow label="Kind">
                    <span className="font-mono">{runKind(run)}</span>
                </CardRow>
                <CardRow label="Started">
                    <Ran started={run.started_at} ended={run.ended_at} />
                </CardRow>
                <CardRow label="Cost">
                    <Spent usd={run.cost_usd} tokens={run.new_tokens} />
                </CardRow>
                {run.prs.length > 0 && (
                    <CardRow label={run.prs.length === 1 ? 'PR' : 'PRs'}>
                        <span className="font-mono">{run.prs.map(pullRequestLabel).join(', ')}</span>
                    </CardRow>
                )}
            </CardRows>
        </GlanceCard>
    )
}

/**
 * A ticket at a glance: whether a run works it or it waits on the operator, its phase, its work in each repository,
 * and what its runs cost.
 */
export function TicketCard({ detail }: { detail: TicketDetail }) {
    const { ticket, units, cost } = detail
    const now = useNow()
    const [state, word] = ticketStands(ticket)
    return (
        <GlanceCard
            title={ticket.key}
            state={state}
            aside={<span className={RUN_TEXT[state]}>{word}</span>}
            name={ticket.title}
            foot={null}
        >
            <CardRows>
                <CardRow label="Phase">{phaseLabel(ticket)}</CardRow>
                {ticket.running_run !== null && (
                    <CardRow label="Run">
                        <span className="font-mono">{runRef(ticket.running_run)}</span> is working it
                    </CardRow>
                )}
                {ticket.plan_waits && (
                    <CardRow label="Plan">
                        <span className={RUN_TEXT.blocked}>waiting on you</span>
                    </CardRow>
                )}
                {units.map((unit) => (
                    <CardRow key={`${unit.repo}:${unit.pr_url}`} label={unit.repo ?? 'Work'}>
                        {unit.pr_url === null ? (
                            'no PR yet'
                        ) : (
                            <span className="font-mono">{pullRequestLabel(unit.pr_url)}</span>
                        )}
                        {unit.phase !== null && ` · ${readable(unit.phase)}`}
                    </CardRow>
                ))}
                {cost.runs + cost.reviews > 0 && (
                    <CardRow label="Cost">
                        <span className="readout">{costText(cost.cost_usd)}</span> {countedText(cost)}
                    </CardRow>
                )}
                <CardRow label="Active">
                    <span className="readout">{age(ticket.active_at, now)}</span> ago
                </CardRow>
            </CardRows>
        </GlanceCard>
    )
}

/**
 * The tick at a glance: its status, the overseer's summary, when it started and how long it took, its decisions, what
 * its overseer cost, and what woke the loop for it. The header's readout of the latest tick shows it too, and points
 * to the page with `foot`.
 */
export function TickCard({ tick, foot = null }: { tick: Tick; foot?: ReactNode }) {
    return (
        <GlanceCard
            title={tickRef(tick.id)}
            state={tickState(tick.status)}
            aside={
                <span className={TICK_TONE[tick.status] ?? undefined}>
                    <Word word={tick.status} />
                    {tick.dry_run ? ' · dry run' : ''}
                </span>
            }
            foot={foot}
        >
            {tick.summary !== null && tick.summary !== '' && <CardWords>{tick.summary}</CardWords>}
            <CardRows>
                <CardRow label="Started">
                    <Ran started={tick.started_at} ended={tick.ended_at} />
                </CardRow>
                <CardRow label="Decisions">{counted(tick.decisions, 'decision')}</CardRow>
                <CardRow label="Overseer">
                    <Spent usd={tick.cost_usd} tokens={tick.new_tokens} />
                </CardRow>
                {tick.woken_by !== null && <CardRow label="Woken by">{tick.woken_by}</CardRow>}
            </CardRows>
        </GlanceCard>
    )
}

/** A task at a glance: where it stands, the operator's words, its repository, its runs, and what its newest said. */
export function TaskCard({ detail }: { detail: TaskDetail }) {
    const { task } = detail
    const now = useNow()
    const look = TASK_LOOK[task.standing]
    const said = task.latest?.summary ?? null
    return (
        <GlanceCard
            title={taskRef(task.id)}
            state={look.state}
            aside={<span className={RUN_TEXT[look.state]}>{look.word}</span>}
            name={taskTitle(task.text)}
            foot={null}
        >
            {said !== null && said !== '' && <CardWords>{said}</CardWords>}
            <CardRows>
                <CardRow label="Repo">
                    <span className="font-mono">{task.repo}</span>
                </CardRow>
                <CardRow label="Runs">
                    {counted(task.runs, 'run')}
                    {detail.tickets.length > 0 && `, ${counted(detail.tickets.length, 'ticket')} filed`}
                </CardRow>
                <CardRow label="Submitted">
                    <span className="readout">{age(task.submitted_at, now)}</span> ago, from the {task.channel}
                </CardRow>
            </CardRows>
        </GlanceCard>
    )
}

/** One run of a task at a glance: how it ended, what it asked or said, when it ran, and what it cost. */
export function TaskRunCard({ detail }: { detail: TaskRunDetail }) {
    const { run } = detail
    const words = detail.question ?? detail.summary ?? detail.note
    return (
        <GlanceCard
            title={taskRunRef(detail.task_id, run.id)}
            state={run.state}
            aside={<Stands state={run.state} word={run.status} />}
            foot={null}
        >
            {words !== null && words !== '' && <CardWords>{words}</CardWords>}
            <CardRows>
                <CardRow label="Started">
                    <Ran started={run.started_at} ended={run.ended_at} />
                </CardRow>
                <CardRow label="Cost">
                    <Spent usd={run.cost_usd} tokens={run.new_tokens} />
                </CardRow>
                {run.prs.length > 0 && (
                    <CardRow label={run.prs.length === 1 ? 'PR' : 'PRs'}>
                        <span className="font-mono">{run.prs.map(pullRequestLabel).join(', ')}</span>
                    </CardRow>
                )}
            </CardRows>
        </GlanceCard>
    )
}

/**
 * A review at a glance: its verdict, in its worst finding's color, the PR and commit it reviewed, the persona it ran
 * in, where its draft stands, and what it cost.
 */
export function ReviewCard({ detail }: { detail: ReviewDetail }) {
    const { review } = detail
    return (
        <GlanceCard
            title={reviewRef(review.id)}
            state={review.state}
            aside={<span className={verdictTone(review) || undefined}>{verdictText(review)}</span>}
            name={review.title}
            foot={null}
        >
            {detail.summary !== null && detail.summary !== '' && <CardWords>{detail.summary}</CardWords>}
            <CardRows>
                <CardRow label="PR">
                    <span className="font-mono">{pullRequestLabel(review.pr_url)}</span>
                    {review.author !== null && ` by ${review.author}`}
                </CardRow>
                <CardRow label="Commit">
                    <span className="font-mono">{shortSha(review.sha)}</span>
                </CardRow>
                {review.persona !== null && <CardRow label="Persona">{review.persona}</CardRow>}
                {review.draft !== null && <CardRow label="Draft">{review.draft}</CardRow>}
                <CardRow label="Started">
                    <Ran started={review.started_at} ended={review.ended_at} />
                </CardRow>
                <CardRow label="Cost">
                    <Spent usd={review.cost_usd} tokens={detail.new_tokens} />
                </CardRow>
            </CardRows>
        </GlanceCard>
    )
}

/** An epic at a glance: where it stands, its goal, its members against the bound, and how much of it is filed. */
export function EpicCard({ detail }: { detail: EpicDetail }) {
    const { epic } = detail
    const now = useNow()
    const look = EPIC_LOOK[epic.standing]
    return (
        <GlanceCard
            title={epicRef(epic.id)}
            state={look.state}
            aside={<span className={RUN_TEXT[look.state]}>{look.word}</span>}
            name={epicTitle(epic.text)}
            foot={null}
        >
            <CardWords>{look.meaning}</CardWords>
            <CardRows>
                <CardRow label="Members">
                    {counted(epic.members, 'ticket')}, of {detail.bound} at most
                </CardRow>
                <CardRow label="Breakdown">{entriesFiled(epic)}</CardRow>
                {epic.repos.length > 0 && (
                    <CardRow label={epic.repos.length === 1 ? 'Repo' : 'Repos'}>
                        <span className="font-mono">{epic.repos.join(', ')}</span>
                    </CardRow>
                )}
                <CardRow label="Submitted">
                    <span className="readout">{age(epic.submitted_at, now)}</span> ago, from the {epic.channel}
                </CardRow>
            </CardRows>
        </GlanceCard>
    )
}

/** A chore at a glance: whether it runs, how its last run ended, its open findings, when it may start, its spend. */
export function ChoreCard({ detail }: { detail: ChoreDetail }) {
    const { chore } = detail
    const now = useNow()
    const run = chore.running ?? chore.latest
    return (
        <GlanceCard
            title={choreRef(chore.name)}
            state={run?.state ?? 'stopped'}
            aside={run === null ? 'never run' : <Stands state={run.state} word={run.status} />}
            name={chore.title}
            foot={null}
        >
            <CardRows>
                <CardRow label="Stands">{choreLine(chore, now)}</CardRow>
                <CardRow label="Findings">{findingsText(chore.findings, chore.more_findings)}</CardRow>
                <CardRow label="Starts">
                    {cadenceText(chore.every_minutes)}, {windowText(chore)}
                </CardRow>
                <CardRow label="30 days">
                    <span className="readout">{costText(chore.spend.month.cost_usd)}</span> over{' '}
                    {counted(chore.spend.month.runs, 'run')}
                </CardRow>
            </CardRows>
        </GlanceCard>
    )
}

/** One run of a chore at a glance: how it ended, what it said, its findings, when it ran, and what it cost. */
export function ChoreRunCard({ detail }: { detail: ChoreRunDetail }) {
    const { run } = detail
    const words = detail.summary ?? detail.note
    return (
        <GlanceCard
            title={choreRunRef(detail.chore, run.id)}
            state={run.state}
            aside={<Stands state={run.state} word={run.status} />}
            name={detail.title}
            foot={null}
        >
            {words !== null && words !== '' && <CardWords>{words}</CardWords>}
            <CardRows>
                {run.status === 'ok' && (
                    <CardRow label="Findings">
                        {counted(run.findings + run.more_findings, 'finding')}
                        {run.more_findings > 0 && `, ${run.more_findings} not listed`}
                    </CardRow>
                )}
                <CardRow label="Started">
                    <Ran started={run.started_at} ended={run.ended_at} />
                </CardRow>
                <CardRow label="Cost">
                    <Spent usd={run.cost_usd} tokens={run.new_tokens} />
                </CardRow>
            </CardRows>
        </GlanceCard>
    )
}

/**
 * A PR at a glance: its title, its ticket, its phase as the overseer last derived it, canopy's newest review of it,
 * the run working it now, and what its runs and reviews cost.
 */
export function PullRequestCard({ detail }: { detail: PullRequestDetail }) {
    const { pull_request: pr, cost } = detail
    const review = pr.latest_review
    return (
        <GlanceCard
            title={pullRequestLabel(pr.url)}
            mono
            aside={pr.phase === null ? undefined : <Word word={pr.phase} />}
            name={pr.title ?? pr.ticket_title}
            foot={null}
        >
            <CardRows>
                <CardRow label="Ticket">
                    {pr.ticket_key === null ? NO_TICKET : <span className="font-mono">{pr.ticket_key}</span>}
                </CardRow>
                {pr.running_run !== null && (
                    <CardRow label="Run">
                        <span className="font-mono">{runRef(pr.running_run)}</span> is working it
                    </CardRow>
                )}
                <CardRow label="Review">
                    {review === null ? (
                        'canopy has not reviewed it'
                    ) : (
                        <>
                            <span className={verdictTone(review) || undefined}>{verdictText(review)}</span>
                            {pr.reviews > 1 && `, the newest of ${pr.reviews}`}
                        </>
                    )}
                </CardRow>
                {pr.draft !== null && <CardRow label="Draft">{pr.draft.status}</CardRow>}
                {cost.runs + cost.reviews > 0 && (
                    <CardRow label="Cost">
                        <span className="readout">{costText(cost.cost_usd)}</span> {countedText(cost)}
                    </CardRow>
                )}
            </CardRows>
        </GlanceCard>
    )
}

// A card before its read lands: its reference, so the card names what it opened on at once, over placeholders the
// height of a card's first rows, or, when the read failed, why.
function Unread({ title, error }: { title: string; error: unknown }) {
    return (
        <GlanceCard title={title} mono foot={null}>
            {error === null ? (
                <div className="flex flex-col gap-2" aria-busy aria-label="Reading it">
                    <Skeleton className="h-4 w-3/4" />
                    <Skeleton className="h-3 w-full" />
                    <Skeleton className="h-3 w-5/6" />
                    <Skeleton className="h-3 w-2/3" />
                </div>
            ) : (
                <p className="wrap-break-word text-status-failed">{readFailure(error)}</p>
            )}
        </GlanceCard>
    )
}

// A journal status in its state's color, read as words (`timeout`, `ok`), with the CLI's spelling in its tip.
function Stands({ state, word }: { state: RunState; word: string }) {
    return <Word word={word} className={RUN_TEXT[state]} />
}

// When something that runs started, and for how long it has run or how long it took.
function Ran({ started, ended }: { started: string; ended: string | null }) {
    const clock = useClock()
    const now = useNow()
    return (
        <>
            {stamp(started, clock)}
            {ended === null ? `, running for ${age(started, now)}` : `, took ${lasted(started, ended)}`}
        </>
    )
}

// What an agent run cost, and the tokens it took in or wrote anew when the runtime reported them.
function Spent({ usd, tokens }: { usd: number | null; tokens: number | null }) {
    if (usd === null) {
        return 'no cost reported'
    }
    return (
        <>
            <span className="readout">{costText(usd)}</span>
            {tokens !== null && `, ${tokenCount(tokens)} tokens`}
        </>
    )
}

// Where a ticket stands, as the tickets list's leading column says it (`TicketState`), in one word and its color.
function ticketStands(ticket: TicketDetail['ticket']): [RunState, string] {
    if (ticket.awaiting !== null) {
        return ['blocked', 'waiting on you']
    }
    if (ticket.running_run !== null) {
        return ['running', 'running']
    }
    return ticket.done ? ['done', 'done'] : ['stopped', 'open']
}
