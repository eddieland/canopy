import { useQuery } from '@tanstack/react-query'
import { createFileRoute } from '@tanstack/react-router'
import { Fragment, useState } from 'react'

import { memoryQuery, ticketMemoryQuery } from '@/api/queries'
import type { MemoryOverview, MemoryState, TicketNotes } from '@/api/types'
import { Age } from '@/components/age'
import { Disclosure } from '@/components/disclosure'
import { MemoryBand, MemoryDigestView, MemoryRows, ProposalProvenance } from '@/components/memory'
import { LessonActions, MemorySaid, ProposalActions } from '@/components/memory-actions'
import { Empty, PageHeader, Panel, PanelHeader, PanelScroll, PanelSkeleton } from '@/components/panel'
import { ListRow } from '@/components/rows'
import { TicketLink } from '@/components/ticket-link'
import { Collapsible, CollapsibleContent } from '@/components/ui/collapsible'
import { ticketNotesUsedText } from '@/lib/memory'
import { rowLineFrom } from '@/lib/rows'
import { cn } from '@/lib/utils'

/**
 * Agent memory (DESIGN §28): each tier under a band that says what reads it, the tickets with notes in force, each
 * opening to its notes, and the lessons with the proposals waiting on the operator, each with what a run would be
 * served. Every list scrolls in its panel, so a busy workspace's thousands of notes and hundreds of lessons keep the
 * page in reach. A proposal is promoted or rejected, and a lesson renewed or forgotten, from its row, as `canopy
 * memory` does, while `memory.proposals` is on (ROADMAP M52).
 */
export const Route = createFileRoute('/memory')({
    component: MemoryPage,
})

function MemoryPage() {
    const { data } = useQuery(memoryQuery)
    return (
        <>
            <PageHeader title="Memory">
                What workers recorded of what they learn, and the lessons you promoted. Promote and reject proposals,
                and renew and forget lessons, here or with <code className="font-mono text-xs">canopy memory</code>.
            </PageHeader>
            {data === undefined ? (
                <Panel>
                    <PanelSkeleton className="min-h-72" />
                </Panel>
            ) : data.state === null ? (
                <Panel>
                    <Empty size="panel">
                        memory is off now: set <code className="font-mono text-xs">[memory]</code> to record or use
                    </Empty>
                </Panel>
            ) : (
                <Tiers overview={data} state={data.state} />
            )}
        </>
    )
}

function Tiers({ overview, state }: { overview: MemoryOverview; state: MemoryState }) {
    const { tickets, proposals, lessons, lessons_digest: digest } = overview
    // What a verb did, under the panel's band: its row may have left the list once it was done.
    const [said, setSaid] = useState<string | null>(null)
    const acting = state.lessons.mode !== 'off'
    const belowProposals = new Map(
        proposals.map((p) => [
            p.entry.id,
            <Fragment key={p.entry.id}>
                <ProposalProvenance proposal={p} />
                {acting && <ProposalActions proposal={p.entry} onSaid={setSaid} />}
            </Fragment>,
        ]),
    )
    const belowLessons = new Map(
        acting ? lessons.map((m) => [m.id, <LessonActions key={m.id} lesson={m} onSaid={setSaid} />]) : [],
    )
    return (
        <div className="stagger flex flex-col gap-6">
            <Panel data-testid="memory-notes">
                <PanelHeader label="Ticket notes">
                    <span className="readout text-xs text-muted-foreground" data-testid="memory-notes-count">
                        {tickets.reduce((sum, t) => sum + t.count, 0)}
                    </span>
                </PanelHeader>
                <MemoryBand tier={state.ticket_notes} name="ticket notes" />
                {tickets.length === 0 ? (
                    <Empty>no notes in force now: a ticket&apos;s runs write them as they end</Empty>
                ) : (
                    <PanelScroll label="Ticket notes">
                        <ul className="divide-y">
                            {tickets.map((t) => (
                                <TicketNotesRow key={t.ticket_key} notes={t} />
                            ))}
                        </ul>
                    </PanelScroll>
                )}
            </Panel>
            <Panel data-testid="memory-lessons">
                <PanelHeader label="Lessons">
                    <span className="readout text-xs text-muted-foreground">{lessons.length}</span>
                </PanelHeader>
                <MemoryBand tier={state.lessons} name="lessons" />
                <MemorySaid said={said} className="border-b px-3 py-2" />
                <h3 className="px-3 pt-2 panel-label">Proposals, waiting on you: none reaches a run</h3>
                {proposals.length === 0 ? (
                    <Empty>no proposals wait on you now</Empty>
                ) : (
                    <PanelScroll label="Proposals">
                        <MemoryRows entries={proposals.map((p) => p.entry)} ticket below={belowProposals} />
                    </PanelScroll>
                )}
                <h3 className="border-t px-3 pt-2 panel-label">
                    Lessons you promoted: reported wrong first, then by review date
                </h3>
                {lessons.length === 0 ? (
                    <Empty>no lessons yet: promote a proposal above, or a ticket&apos;s note from its page</Empty>
                ) : (
                    <PanelScroll label="Lessons you promoted">
                        <MemoryRows entries={lessons} digest={digest} below={belowLessons} />
                    </PanelScroll>
                )}
                {digest !== null && <MemoryDigestView digest={digest} served="served to every run" />}
            </Panel>
        </div>
    )
}

/**
 * A ticket with notes in force: its key, how many, how runs used them, and when the newest was written. Its notes open
 * under it, read only once opened (closed, the content is not mounted), so a workspace of many tickets sends their
 * counts and not every note.
 */
function TicketNotesRow({ notes }: { notes: TicketNotes }) {
    const [open, setOpen] = useState(false)
    const what = `${notes.count} ${notes.count === 1 ? 'note' : 'notes'}`
    return (
        <Collapsible asChild open={open} onOpenChange={setOpen}>
            <ListRow kind="memory-ticket" data-testid={`memory-ticket-${notes.ticket_key}`}>
                <TicketLink ticketKey={notes.ticket_key} />
                <span className="min-w-0">
                    {/* No taller than a line of text, its chevron in line with the key beside it. */}
                    <Disclosure open={open} what={what} className="-my-1 -ml-2" />
                </span>
                <span className="truncate text-xs text-muted-foreground">{ticketNotesUsedText(notes)}</span>
                <Age at={notes.latest_at} variant="ago" className="text-right" />
                <CollapsibleContent className={cn('-mx-3 -mb-2.5 border-t', rowLineFrom('key'))}>
                    <OpenNotes ticketKey={notes.ticket_key} />
                </CollapsibleContent>
            </ListRow>
        </Collapsible>
    )
}

/** A ticket's notes in force, under its row: each marked when the cap leaves it out of its next run's prompt. */
function OpenNotes({ ticketKey }: { ticketKey: string }) {
    const { data } = useQuery(ticketMemoryQuery(ticketKey))
    if (data === undefined) {
        return <PanelSkeleton rows={1} />
    }
    const inForce = data.notes.filter((n) => n.status === 'active')
    if (inForce.length === 0) {
        return <Empty>no notes in force now: its page lists the ones before</Empty>
    }
    return <MemoryRows entries={inForce} digest={data.digest} />
}
