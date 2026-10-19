import { useQuery } from '@tanstack/react-query'
import { createFileRoute } from '@tanstack/react-router'
import { useState } from 'react'

import { ApiError } from '@/api/client'
import { loopQuery, ticketMemoryQuery, ticketPlansQuery, ticketQuery } from '@/api/queries'
import type { TicketDetail } from '@/api/types'
import { Age } from '@/components/age'
import { CostTotalRow } from '@/components/cost-total'
import { Copyable } from '@/components/copy-button'
import { Decisions } from '@/components/decisions'
import { Field, Fields } from '@/components/fields'
import { MemoryBand, MemoryDigestView, MemoryRows } from '@/components/memory'
import { MemorySaid, NoteActions } from '@/components/memory-actions'
import { Notice } from '@/components/notice'
import { OrderToggle } from '@/components/order-toggle'
import { PlanCard } from '@/components/plan-card'
import { Empty, PageHeader, Panel, PanelHeader, PanelLoading, PanelScroll, PanelSkeleton } from '@/components/panel'
import { PullRequestLink } from '@/components/pull-request-link'
import { RunsTable } from '@/components/runs-table'
import { StartTicket } from '@/components/start-ticket'
import { Chip, Word } from '@/components/status'
import { TicketAnswer, TicketVerbs } from '@/components/ticket-answer'
import { TicketDrafts } from '@/components/ticket-drafts'
import { TicketLinks } from '@/components/ticket-links'
import { useBranchUrls } from '@/hooks/use-branch-urls'
import { useTicketUrl } from '@/hooks/use-ticket-url'
import { ticketDescription } from '@/lib/descriptions'
import { ordered, useListOrder } from '@/lib/list-order'
import { cn } from '@/lib/utils'
import { phaseLabel, phaseWord } from '@/lib/phase'
import { None } from '@/components/none'

/**
 * One ticket: its work, then its conversation, the reply, and the operator's actions, then its runs and decisions; and
 * for a ticket plans touch, its plan's card below them, which opens the plan's own page (DESIGN §25).
 */
export const Route = createFileRoute('/tickets/$key')({
    component: TicketPage,
})

// What every ticket's page shows, on its title's hover.
const HELP =
    "A ticket's page: its work and your actions on it, its conversation and the box to reply in, then its runs and " +
    'the decisions each tick made about it.'

// What a public ticket's chip means, on hover: where its comments and a reply sent here go, as the reply box says it.
const PUBLIC_HINT =
    'Public: its queue label authorizes it. Its comments stay on the tracker; a reply you send here stays in canopy, ' +
    'for its next worker.'

function TicketPage() {
    const { key } = Route.useParams()
    const query = useQuery(ticketQuery(key))
    const { data, error } = query
    // The plans too, before the page paints: a plan waiting on the operator leads the page with its card, which would
    // otherwise push everything down as it arrived.
    const plans = useQuery(ticketPlansQuery(key))
    if (error instanceof ApiError && error.status === 404) {
        return <Unknown ticketKey={key} />
    }
    if (error instanceof ApiError && error.status === 409) {
        return (
            <>
                <PageHeader title={key} />
                <Panel>
                    <Notice error={error} className="p-3" />
                </Panel>
            </>
        )
    }
    if (data === undefined || plans.isPending) {
        return (
            <>
                <PageHeader title={key} />
                <Panel>
                    <PanelLoading query={query} rows={1} className="min-h-72" />
                </Panel>
            </>
        )
    }
    // Each ticket its own page, so what one settled (where its plan sits) is never another's.
    return <Ticket key={data.ticket.key} detail={data} />
}

function Ticket({ detail }: { detail: TicketDetail }) {
    const { ticket, units, limits, runs, decisions, cost } = detail
    const tracker = useTicketUrl(ticket.key)
    const branchUrl = useBranchUrls()
    const branch = ticket.branch
    const branches = units.flatMap((u) => {
        const href = branch === null ? undefined : branchUrl(u.repo, branch)
        return u.repo !== null && href !== undefined ? [{ repo: u.repo, href }] : []
    })
    const runsOrder = useListOrder('ticket-runs')
    const decisionsOrder = useListOrder('ticket-decisions')
    const plans = useQuery(ticketPlansQuery(ticket.key)).data
    const planned = plans !== undefined && (plans.needed || plans.plans.length > 0)
    // A plan waiting on the operator is what they came to answer, so its card leads the page. Where it sits is settled
    // once, as the plans arrive: a plan approved meanwhile leaves its card where it was read, rather than move it.
    const [planLeads, setPlanLeads] = useState<boolean | undefined>(undefined)
    if (planLeads === undefined && plans !== undefined) {
        setPlanLeads(plans.newest?.plan.status === 'proposed' && plans.planning === null)
    }
    const state = ticketDescription(ticket, plans)
    return (
        <>
            <PageHeader
                chips={
                    // What public or private means is the chip's, on hover and to a screen reader: the description is
                    // the ticket's state.
                    <span title={accessHint(ticket)} className="inline-flex">
                        <Chip>{ticket.private ? 'private' : 'public'}</Chip>
                        <span className="sr-only">{accessHint(ticket)}</span>
                    </span>
                }
                title={ticket.key}
                subject={ticket.title}
                help={HELP}
                links={<TicketLinks tracker={tracker} units={units} branches={branches} />}
            >
                {state}
                {state === '' ? '' : ' · '}
                active <Age at={ticket.active_at} variant="ago" />
            </PageHeader>
            {planned && planLeads === true && <PlanCard ticketKey={ticket.key} plans={plans} />}
            {/* The detail skeleton (DESIGN.md): what it is, its conversation and its answer, then its lists. */}
            {/* Wide, the conversation moves beside the rest, as in the inbox; the source keeps the reading order. */}
            <div
                className={cn(
                    'stagger flex flex-col gap-6',
                    '2xl:grid 2xl:grid-cols-[minmax(0,36rem)_minmax(0,1fr)] 2xl:grid-rows-[auto_auto_1fr]',
                    '2xl:items-start',
                )}
            >
                <Panel className="2xl:col-start-1 2xl:row-start-1">
                    <PanelHeader label="Work" />
                    {/* Three field lists spaced as one: a ticket across many repositories scrolls its units in */}
                    {/* place, so its total stays in reach. */}
                    <Fields className="pb-0">
                        <Field label="phase" mono>
                            <Word word={phaseWord(ticket)} text={phaseLabel(ticket)} />
                            {ticket.done ? ', done' : ''}
                        </Field>
                        <Field label="branch" mono>
                            {ticket.branch === null ? <None /> : <Copyable text={ticket.branch} label="branch" />}
                        </Field>
                    </Fields>
                    {units.length > 0 && (
                        <PanelScroll label="Repositories" className="max-h-60" data-testid="ticket-units">
                            <Fields className="pt-1.5 pb-0">
                                {units.map((unit) => (
                                    <Unit key={unit.repo ?? ''} repo={unit.repo} pr={unit.pr_url} phase={unit.phase} />
                                ))}
                            </Fields>
                        </PanelScroll>
                    )}
                    <Fields className="pt-1.5">
                        <CostTotalRow cost={cost} />
                    </Fields>
                </Panel>
                {/* The answer: the conversation, the reply, then the ticket's verbs, so the keyboard reaches the
                    reply before Stop or Forget, as on its attention item. */}
                <Panel className="2xl:col-start-2 2xl:row-span-3 2xl:row-start-1" data-testid="ticket-conversation">
                    <TicketAnswer
                        detail={detail}
                        after={<TicketVerbs ticket={ticket} limits={limits} place="after" testId="ticket-actions" />}
                    />
                </Panel>
                <Panel className="2xl:col-start-1 2xl:row-start-2" data-testid="ticket-runs">
                    <PanelHeader label="Runs">
                        <span className="flex items-center gap-2">
                            {runs.length > 1 && <OrderToggle list="ticket-runs" />}
                            <span className="readout text-xs text-muted-foreground">{runs.length}</span>
                        </span>
                    </PanelHeader>
                    {runs.length === 0 ? (
                        <Empty>no runs yet: none has worked it</Empty>
                    ) : (
                        <PanelScroll label="Runs">
                            <RunsTable runs={ordered('ticket-runs', runsOrder, runs)} ticket={false} />
                        </PanelScroll>
                    )}
                </Panel>
                <Panel className="2xl:col-start-1 2xl:row-start-3" data-testid="ticket-decisions">
                    <PanelHeader label="Decisions">
                        <span className="flex items-center gap-2">
                            {decisions.length > 1 && <OrderToggle list="ticket-decisions" />}
                            <span className="readout text-xs text-muted-foreground">{decisions.length}</span>
                        </span>
                    </PanelHeader>
                    {decisions.length === 0 ? (
                        <Empty>no decisions yet: no tick has decided anything about it</Empty>
                    ) : (
                        <PanelScroll label="Decisions">
                            <Decisions decisions={ordered('ticket-decisions', decisionsOrder, decisions)} byTick />
                        </PanelScroll>
                    )}
                </Panel>
            </div>
            {/* What its runs would have said on it, waiting on the operator to send (DESIGN §29). */}
            <TicketDrafts ticketKey={ticket.key} drafts={detail.drafts} />
            {planned && planLeads === false && <PlanCard ticketKey={ticket.key} plans={plans} />}
            <TicketMemoryPanel ticketKey={ticket.key} />
        </>
    )
}

/**
 * The ticket's notes (DESIGN §28), under the band that says what reads them; none while ticket notes are off. Each
 * note that keeps its text is forgotten from its row, and while proposals are on, promoted to a lesson, done or
 * invalidated ones too.
 */
function TicketMemoryPanel({ ticketKey }: { ticketKey: string }) {
    const memory = useQuery(loopQuery).data?.memory
    const tier = memory?.ticket_notes
    const on = tier !== undefined && tier.mode !== 'off'
    const { data } = useQuery({ ...ticketMemoryQuery(ticketKey), enabled: on })
    // What a promote did, under the band, as the memory page says it.
    const [said, setSaid] = useState<string | null>(null)
    if (!on) {
        return null
    }
    const promoting = memory !== undefined && memory !== null && memory.lessons.mode !== 'off'
    // Forget whenever ticket notes are on, so a note holding what should not be kept goes from where it shows; Promote
    // only while lessons are on, since it makes a lesson.
    const below = new Map(
        (data?.notes ?? []).map((n) => [
            n.id,
            <NoteActions key={n.id} note={n} promote={promoting} onSaid={setSaid} />,
        ]),
    )
    return (
        <Panel data-testid="ticket-memory">
            <PanelHeader label="Memory">
                <span className="readout text-xs text-muted-foreground">{data?.notes.length ?? ''}</span>
            </PanelHeader>
            <MemoryBand tier={tier} name="ticket notes" />
            <MemorySaid said={said} className="border-b px-3 py-2" />
            {data === undefined ? (
                <PanelSkeleton rows={1} />
            ) : data.notes.length === 0 ? (
                <Empty>no notes yet: its runs write them as they end</Empty>
            ) : (
                <PanelScroll label="Memory">
                    <MemoryRows
                        entries={data.notes}
                        digest={data.digest}
                        below={below}
                        onVersionSaid={setSaid}
                        modes={
                            memory
                                ? { ticket_notes: memory.ticket_notes.mode, lessons: memory.lessons.mode }
                                : undefined
                        }
                    />
                </PanelScroll>
            )}
            {data?.digest && <MemoryDigestView digest={data.digest} served="served to its next run" />}
        </Panel>
    )
}

/**
 * What the ticket's `public` or `private` chip means, on hover: what authorizes it, and where its conversation and a
 * reply sent here go, in the words the reply box uses.
 */
function accessHint(ticket: TicketDetail['ticket']): string {
    if (ticket.private) {
        return `Private, ${ticket.start ?? 'started'}: its conversation stays in canopy; nothing reaches the ticket.`
    }
    return PUBLIC_HINT
}

function Unit({ repo, pr, phase }: { repo: string | null; pr: string | null; phase: string | null }) {
    return (
        <Field label={repo ? `PR in ${repo}` : 'PR'} mono className="flex items-baseline gap-3">
            {pr ? <PullRequestLink url={pr} className="text-sm" /> : <None />}
            {phase && <Word word={phase} className="text-muted-foreground" />}
        </Field>
    )
}

function Unknown({ ticketKey }: { ticketKey: string }) {
    const tracker = useTicketUrl(ticketKey)
    return (
        <>
            <PageHeader title={ticketKey} links={<TicketLinks tracker={tracker} />}>
                canopy has no record of it. Start it to work it privately.
            </PageHeader>
            <Panel>
                <PanelHeader label="Start a ticket" />
                <StartTicket />
            </Panel>
        </>
    )
}
