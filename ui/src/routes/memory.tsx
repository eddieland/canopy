import { useQuery } from '@tanstack/react-query'
import { createFileRoute } from '@tanstack/react-router'
import { useState } from 'react'

import { memoryQuery, ticketMemoryQuery } from '@/api/queries'
import type {
    MemoryDigest,
    MemoryEntry,
    MemoryOverview,
    MemoryProposal,
    MemoryState,
    MemoryTier,
    TicketNotes,
} from '@/api/types'
import { Age } from '@/components/age'
import { Disclosure } from '@/components/disclosure'
import { MemoryBand, MemoryDigestView, MemoryRows, ProposalFacts } from '@/components/memory'
import { LessonActions, MemorySaid, NoteActions, ProposalActions } from '@/components/memory-actions'
import { Empty, PageHeader, Panel, PanelHeader, PanelLoading, PanelScroll, PanelSkeleton } from '@/components/panel'
import { ListRow } from '@/components/rows'
import { TicketLink } from '@/components/ticket-link'
import { TicketTitle } from '@/components/ticket-title'
import { Collapsible, CollapsibleContent } from '@/components/ui/collapsible'
import { ticketNotesUsedText } from '@/lib/memory'
import type { TierModes } from '@/lib/memory'
import { rowLineFrom } from '@/lib/rows'
import { cn } from '@/lib/utils'

/**
 * Agent memory (DESIGN §28), what waits on the operator first: the proposals, then the lessons under the band that says
 * what reads them, then the tickets with notes in force, each opening to its notes. Every list scrolls in its panel, so
 * a busy workspace's thousands of notes and hundreds of lessons keep the page in reach. A proposal is promoted or
 * rejected, and a lesson renewed or forgotten, from its row, as `canopy memory` does, while `memory.proposals` is on
 * (ROADMAP M52). What every run is served of the lessons is folded under them, since it is the prompt's, not a queue.
 */
export const Route = createFileRoute('/memory')({
    component: MemoryPage,
})

function MemoryPage() {
    const query = useQuery(memoryQuery)
    const { data } = query
    return (
        <>
            <PageHeader title="Memory">
                What workers learned, the proposals waiting on you, and the lessons you promoted. Decide them here or
                with <code className="font-mono text-xs">canopy memory</code>.
            </PageHeader>
            {data === undefined ? (
                <Panel>
                    <PanelLoading query={query} className="min-h-72" />
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
    const acting = state.lessons.mode !== 'off'
    const modes = { ticket_notes: state.ticket_notes.mode, lessons: state.lessons.mode }
    return (
        // Wide, the queue keeps the width and the tickets with notes sit beside it, in the narrow order's last place.
        <div
            className={cn(
                'stagger flex flex-col gap-6',
                '2xl:grid 2xl:grid-cols-[minmax(0,1fr)_minmax(0,34rem)] 2xl:items-start',
            )}
        >
            <div className="flex flex-col gap-6">
                <Proposals proposals={proposals} acting={acting} />
                <Lessons lessons={lessons} digest={digest} tier={state.lessons} acting={acting} modes={modes} />
            </div>
            <TicketNotesPanel tickets={tickets} tier={state.ticket_notes} acting={acting} modes={modes} />
        </div>
    )
}

/**
 * The proposals waiting on the operator, oldest first, each with where it came from and its verbs. None reaches a run
 * until it is promoted, at any mode, so the panel says that rather than the tier's band, which heads the lessons. Its
 * count wears `status-blocked` while one waits, as the nav's does.
 */
function Proposals({ proposals, acting }: { proposals: MemoryProposal[]; acting: boolean }) {
    // What a verb did: its row leaves the list once it is done, so it is said under the panel's header.
    const [said, setSaid] = useState<string | null>(null)
    const facts = new Map(proposals.map((p) => [p.entry.id, <ProposalFacts key={p.entry.id} proposal={p} />]))
    const acted = acting ? proposals : []
    const below = new Map(
        acted.map((p) => [p.entry.id, <ProposalActions key={p.entry.id} proposal={p.entry} onSaid={setSaid} />]),
    )
    return (
        <Panel data-testid="memory-proposals">
            <PanelHeader label="Proposals">
                <span
                    className={cn(
                        'readout text-xs',
                        proposals.length > 0 ? 'text-status-blocked' : 'text-muted-foreground',
                    )}
                    data-testid="memory-proposals-count"
                >
                    {proposals.length}
                </span>
            </PanelHeader>
            <p className="border-b px-3 py-2 text-sm text-muted-foreground">
                What workers proposed. None reaches a run until you promote it.
            </p>
            <MemorySaid said={said} className="border-b px-3 py-2" />
            {proposals.length === 0 ? (
                // Cleared from this page just now: the one queue memory has is empty, and that is worth a word.
                <Empty className={cn(said !== null && 'text-accent')}>
                    {said === null ? 'no proposals wait on you now' : 'all decided: no proposal waits on you'}
                </Empty>
            ) : (
                <PanelScroll label="Proposals">
                    <MemoryRows entries={proposals.map((p) => p.entry)} ticket facts={facts} below={below} />
                </PanelScroll>
            )}
        </Panel>
    )
}

/**
 * The lessons the operator promoted, under the band that says whether runs read them, those a run reported wrong first,
 * then by review date. What every run is served of them opens under the list.
 */
function Lessons({
    lessons,
    digest,
    tier,
    acting,
    modes,
}: {
    lessons: MemoryEntry[]
    digest: MemoryDigest | null
    tier: MemoryTier
    acting: boolean
    modes: TierModes
}) {
    const [said, setSaid] = useState<string | null>(null)
    const below = new Map(
        acting ? lessons.map((m) => [m.id, <LessonActions key={m.id} lesson={m} onSaid={setSaid} />]) : [],
    )
    return (
        <Panel data-testid="memory-lessons">
            <PanelHeader label="Lessons">
                <span className="readout text-xs text-muted-foreground" data-testid="memory-lessons-count">
                    {lessons.length}
                </span>
            </PanelHeader>
            <MemoryBand tier={tier} name="lessons" />
            <MemorySaid said={said} className="border-b px-3 py-2" />
            {lessons.length === 0 ? (
                <Empty>no lessons yet: promote a proposal above, or a ticket&apos;s note from its page</Empty>
            ) : (
                <PanelScroll label="Lessons">
                    <MemoryRows entries={lessons} digest={digest} below={below} modes={modes} />
                </PanelScroll>
            )}
            {digest !== null && <ServedDigest digest={digest} />}
        </Panel>
    )
}

/** What every run is served of the lessons, folded at the panel's foot until the operator asks to read it. */
function ServedDigest({ digest }: { digest: MemoryDigest }) {
    const [open, setOpen] = useState(false)
    const what = digest.served ? 'what every run is served' : 'what every run would be served at use'
    return (
        <Collapsible open={open} onOpenChange={setOpen} className="border-t px-3 py-1.5">
            <Disclosure open={open} what={what} className="-ml-2" data-testid="memory-digest-toggle" />
            <CollapsibleContent className="-mx-3 -mb-1.5">
                <MemoryDigestView digest={digest} served="served to every run" labelled={false} />
            </CollapsibleContent>
        </Collapsible>
    )
}

/**
 * The tickets with notes in force, a row each, under the tier's band. Its header counts the rows, the tickets, and the
 * notes they hold beside them, since a row opens to several. While `acting`, each opened note is promoted or
 * forgotten from its row, and what that did is said under the band.
 */
function TicketNotesPanel({
    tickets,
    tier,
    acting,
    modes,
}: {
    tickets: TicketNotes[]
    tier: MemoryTier
    acting: boolean
    modes: TierModes
}) {
    const [said, setSaid] = useState<string | null>(null)
    const notes = tickets.reduce((sum, t) => sum + t.count, 0)
    return (
        <Panel data-testid="memory-notes">
            <PanelHeader label="Ticket notes">
                <span className="readout text-xs text-muted-foreground" data-testid="memory-notes-count">
                    {tickets.length} {tickets.length === 1 ? 'ticket' : 'tickets'} · {notes}{' '}
                    {notes === 1 ? 'note' : 'notes'}
                </span>
            </PanelHeader>
            <MemoryBand tier={tier} name="ticket notes" />
            <MemorySaid said={said} className="border-b px-3 py-2" />
            {tickets.length === 0 ? (
                <Empty>no notes in force now: a ticket&apos;s runs write them as they end</Empty>
            ) : (
                <PanelScroll label="Ticket notes">
                    <ul className="divide-y">
                        {tickets.map((t) => (
                            <TicketNotesRow
                                key={t.ticket_key}
                                notes={t}
                                onSaid={acting ? setSaid : undefined}
                                modes={modes}
                            />
                        ))}
                    </ul>
                </PanelScroll>
            )}
        </Panel>
    )
}

/**
 * A ticket with notes in force: its key, how many, its title, how runs used them, and when the newest was written.
 * Its notes open under it, read only once opened (closed, the content is not mounted), so a workspace of many tickets
 * sends their counts and not every note.
 */
function TicketNotesRow({
    notes,
    onSaid,
    modes,
}: {
    notes: TicketNotes
    onSaid: ((said: string) => void) | undefined
    modes: TierModes
}) {
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
                <TicketTitle title={notes.title} />
                <span className="truncate text-right text-xs text-muted-foreground">{ticketNotesUsedText(notes)}</span>
                <Age at={notes.latest_at} variant="ago" className="text-right" />
                <CollapsibleContent className={cn('-mx-3 -mb-2.5 border-t', rowLineFrom('key'))}>
                    <OpenNotes ticketKey={notes.ticket_key} onSaid={onSaid} modes={modes} />
                </CollapsibleContent>
            </ListRow>
        </Collapsible>
    )
}

/**
 * A ticket's notes in force, under its row: each marked when the cap leaves it out of its next run's prompt, and with
 * `onSaid`, each with its verbs, Promote and Forget.
 */
function OpenNotes({
    ticketKey,
    onSaid,
    modes,
}: {
    ticketKey: string
    onSaid: ((said: string) => void) | undefined
    modes: TierModes
}) {
    const { data } = useQuery(ticketMemoryQuery(ticketKey))
    if (data === undefined) {
        return <PanelSkeleton rows={1} />
    }
    const inForce = data.notes.filter((n) => n.status === 'active')
    if (inForce.length === 0) {
        return <Empty>no notes in force now: its page lists the ones before</Empty>
    }
    const below = new Map(
        onSaid === undefined ? [] : inForce.map((n) => [n.id, <NoteActions key={n.id} note={n} onSaid={onSaid} />]),
    )
    return <MemoryRows entries={inForce} digest={data.digest} below={below} modes={modes} />
}
