import { useQuery } from '@tanstack/react-query'
import { createFileRoute } from '@tanstack/react-router'
import { useState } from 'react'

import { ApiError } from '@/api/client'
import { loopQuery, ticketMemoryQuery, ticketPlansQuery, ticketQuery } from '@/api/queries'
import type { TicketDetail } from '@/api/types'
import { Age } from '@/components/age'
import { Attachments } from '@/components/attachments'
import { Copyable } from '@/components/copy-button'
import { CostTotalRow } from '@/components/cost-total'
import { Decisions } from '@/components/decisions'
import { Disclosure } from '@/components/disclosure'
import { FeedbackPlanCard } from '@/components/feedback-plan-card'
import { Field, Fields } from '@/components/fields'
import { ListPanel } from '@/components/list-panel'
import { MemoryBand, MemoryDigestFold, MemoryRows } from '@/components/memory'
import { MemorySaid, NoteActions } from '@/components/memory-actions'
import { None } from '@/components/none'
import { Notice } from '@/components/notice'
import { PageHeader, Panel, PanelHeader, PanelLoading, PanelScroll, PanelSkeleton } from '@/components/panel'
import { PlanCard } from '@/components/plan-card'
import { PullRequestLink } from '@/components/pull-request-link'
import { RunsTable } from '@/components/runs-table'
import { StartTicket } from '@/components/start-ticket'
import { Chip, Word } from '@/components/status'
import { TicketAgents } from '@/components/ticket-agents'
import { TicketAnswer, TicketVerbs } from '@/components/ticket-answer'
import { TicketDrafts } from '@/components/ticket-drafts'
import { TicketLinks } from '@/components/ticket-links'
import { TicketModelSpend } from '@/components/ticket-model-spend'
import { Collapsible, CollapsibleContent } from '@/components/ui/collapsible'
import { useBranchUrls } from '@/hooks/use-branch-urls'
import { useTicketUrl } from '@/hooks/use-ticket-url'
import { ticketDescription } from '@/lib/descriptions'
import { ordered, useListOrder } from '@/lib/list-order'
import { phaseMeaning } from '@/lib/meanings'
import { phaseLabel, phaseWord } from '@/lib/phase'
import { useViewedTicket } from '@/lib/recent-tickets'
import { cn } from '@/lib/utils'

/**
 * One ticket: its work, then its conversation, the reply, and the operator's actions, then its runs and decisions, each
 * its header alone while empty, and its memory, folded; and for a ticket plans touch, its plan's card below them, which
 * opens the plan's own page (DESIGN §25). A plan waiting on the operator, a feedback plan's card too, leads the page.
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
    useViewedTicket(ticket.key, ticket.title)
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
    // A feedback plan waiting on the operator leads the page too (DESIGN §32), its card pointing at the PR's page,
    // where it is approved. Settled once as well: a plan approved meanwhile leaves its card where it was read.
    const [led] = useState(ticket.feedback_plan)
    const state = ticketDescription(ticket, plans)
    // Ticket notes on, the Memory panel is the left column's last row, which takes what the conversation is taller by.
    const memoryTier = useQuery(loopQuery).data?.memory?.ticket_notes
    const memoryOn = memoryTier !== undefined && memoryTier.mode !== 'off'
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
            {led !== null && <FeedbackPlanCard led={led} plan={ticket.feedback_plan} />}
            {planned && planLeads === true && <PlanCard ticketKey={ticket.key} plans={plans} />}
            {/* The detail skeleton (DESIGN.md): what it is, its conversation and its answer, then its lists. */}
            {/* Wide, the conversation moves beside the rest, as in the inbox; the source keeps the reading order. */}
            <div
                className={cn(
                    'stagger flex flex-col gap-6',
                    '2xl:grid 2xl:grid-cols-[minmax(0,36rem)_minmax(0,1fr)] 2xl:items-start',
                    memoryOn ? '2xl:grid-rows-[auto_auto_auto_1fr]' : '2xl:grid-rows-[auto_auto_1fr]',
                )}
            >
                <Panel className="2xl:col-start-1 2xl:row-start-1">
                    <PanelHeader label="Work" />
                    {/* Three field lists spaced as one: a ticket across many repositories scrolls its units in */}
                    {/* place, so its total stays in reach. */}
                    <Fields className="pb-0">
                        <Field label="phase" mono>
                            <Word
                                word={phaseWord(ticket)}
                                text={phaseLabel(ticket)}
                                meaning={phaseMeaning(ticket.phase)}
                            />
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
                    {/* Who its runs write as and what they run on, from the next: yours to choose, here or with */}
                    {/* `canopy persona` and `canopy model`, each agent's model level with its persona. */}
                    <TicketAgents
                        ticketKey={ticket.key}
                        personas={detail.personas}
                        names={detail.persona_names}
                        models={detail.models}
                        className="border-t"
                    />
                    {/* What its workers' models cost each beside the workspace's, once there is a model to compare. */}
                    <TicketModelSpend
                        ticketKey={ticket.key}
                        spend={detail.worker_models}
                        models={detail.models}
                        className="px-3 pb-3"
                    />
                </Panel>
                {/* The answer: the conversation, the reply, then the ticket's verbs, so the keyboard reaches the
                    reply before Stop or Forget, as on its attention item. */}
                <Panel
                    className={cn('2xl:col-start-2 2xl:row-start-1', memoryOn ? '2xl:row-span-4' : '2xl:row-span-3')}
                    data-testid="ticket-conversation"
                >
                    <TicketAnswer
                        detail={detail}
                        after={
                            <>
                                <TicketVerbs ticket={ticket} limits={limits} place="after" testId="ticket-actions" />
                                {/* What you attached for its runs to read, such as a design doc someone sent
                                    you (DESIGN §22): beside the reply that says what to do with it, as on a task's
                                    page. */}
                                <Attachments
                                    subject={{ kind: 'ticket', key: ticket.key }}
                                    attachments={detail.attachments}
                                    className="border-t"
                                />
                            </>
                        }
                    />
                </Panel>
                {/* Each list is its header alone while it holds nothing (ListPanel): the count says so. */}
                <ListPanel
                    label="Runs"
                    count={runs.length}
                    list="ticket-runs"
                    className="2xl:col-start-1 2xl:row-start-2"
                    data-testid="ticket-runs"
                >
                    <PanelScroll label="Runs">
                        <RunsTable runs={ordered('ticket-runs', runsOrder, runs)} ticket={false} />
                    </PanelScroll>
                </ListPanel>
                <ListPanel
                    label="Decisions"
                    count={decisions.length}
                    list="ticket-decisions"
                    className="2xl:col-start-1 2xl:row-start-3"
                    data-testid="ticket-decisions"
                >
                    <PanelScroll label="Decisions">
                        <Decisions decisions={ordered('ticket-decisions', decisionsOrder, decisions)} byTick />
                    </PanelScroll>
                </ListPanel>
                {/* The least read, so last; wide, in the left column under the lists rather than across the page. */}
                {memoryOn && <TicketMemoryPanel ticketKey={ticket.key} className="2xl:col-start-1 2xl:row-start-4" />}
            </div>
            {/* What its runs would have said on it, waiting on the operator to send (DESIGN §29). */}
            <TicketDrafts ticketKey={ticket.key} drafts={detail.drafts} />
            {planned && planLeads === false && <PlanCard ticketKey={ticket.key} plans={plans} />}
        </>
    )
}

/**
 * The ticket's notes (DESIGN §28), the least read of its page, so folded on each visit: the band that says what reads
 * them, then `Show 3 notes`, which opens the rows and, folded at their foot, what its next run is served. With none,
 * its header alone, counting `0`, as an empty list's is. Each note that keeps its text is forgotten from its row, and
 * while proposals are on, promoted to a lesson, done or invalidated ones too. Shown only while ticket notes are on.
 */
function TicketMemoryPanel({ ticketKey, className }: { ticketKey: string; className?: string }) {
    const memory = useQuery(loopQuery).data?.memory
    const tier = memory?.ticket_notes
    const on = tier !== undefined && tier.mode !== 'off'
    const { data } = useQuery({ ...ticketMemoryQuery(ticketKey), enabled: on })
    // What a promote did, under the band, as the memory page says it.
    const [said, setSaid] = useState<string | null>(null)
    const [open, setOpen] = useState(false)
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
    const count = data?.notes.length ?? 0
    return (
        <Panel className={className} data-testid="ticket-memory">
            <PanelHeader label="Memory">
                <span className="readout text-xs text-muted-foreground">{data === undefined ? '' : count}</span>
            </PanelHeader>
            {data === undefined && <PanelSkeleton rows={1} />}
            {count > 0 && <MemoryBand tier={tier} name="ticket notes" />}
            <MemorySaid said={said} className="border-b px-3 py-2 last:border-b-0" />
            {data !== undefined && count > 0 && (
                <Collapsible open={open} onOpenChange={setOpen}>
                    <div className="px-3 py-1.5">
                        <Disclosure open={open} what={count === 1 ? '1 note' : `${count} notes`} className="-ml-2" />
                    </div>
                    <CollapsibleContent className="border-t">
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
                        {data.digest && <MemoryDigestFold digest={data.digest} who="its next run" />}
                    </CollapsibleContent>
                </Collapsible>
            )}
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
            {phase && <Word word={phase} meaning={phaseMeaning(phase)} className="text-muted-foreground" />}
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
