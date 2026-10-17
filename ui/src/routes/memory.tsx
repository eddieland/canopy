import { useQuery } from '@tanstack/react-query'
import { createFileRoute } from '@tanstack/react-router'

import { memoryQuery } from '@/api/queries'
import type { MemoryOverview, MemoryProposal, MemoryState } from '@/api/types'
import { MemoryBand, MemoryDigestView, MemoryRows } from '@/components/memory'
import { Empty, PageHeader, Panel, PanelHeader, PanelScroll, PanelSkeleton } from '@/components/panel'
import { RowLine } from '@/components/rows'
import { Chip, Word } from '@/components/status'

/**
 * Agent memory (DESIGN §28): each tier under a band that says what reads it, the ticket notes in force, and the
 * lessons with the proposals waiting on the operator, each with what a run would be served. It reads only:
 * promoting, rejecting, renewing, and forgetting are `canopy memory`'s, in the operator's shell.
 */
export const Route = createFileRoute('/memory')({
    component: MemoryPage,
})

function MemoryPage() {
    const { data } = useQuery(memoryQuery)
    return (
        <>
            <PageHeader root="Memory" title="Memory">
                What workers recorded of what they learn, and the lessons you promoted. Promote, reject, renew, and
                forget them with <code className="font-mono text-xs">canopy memory</code>.
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
    const { notes, proposals, lessons, lessons_digest: digest } = overview
    const provenance = new Map(proposals.map((p) => [p.entry.id, <Provenance key={p.entry.id} proposal={p} />]))
    return (
        <div className="stagger flex flex-col gap-6">
            <Panel data-testid="memory-notes">
                <PanelHeader label="Ticket notes">
                    <span className="readout text-xs text-muted-foreground">{notes.length}</span>
                </PanelHeader>
                <MemoryBand tier={state.ticket_notes} name="ticket notes" />
                {notes.length === 0 ? (
                    <Empty>no notes in force now: a ticket&apos;s runs write them as they end</Empty>
                ) : (
                    <PanelScroll label="Ticket notes">
                        <MemoryRows entries={notes} ticket />
                    </PanelScroll>
                )}
            </Panel>
            <Panel data-testid="memory-lessons">
                <PanelHeader label="Lessons">
                    <span className="readout text-xs text-muted-foreground">{lessons.length}</span>
                </PanelHeader>
                <MemoryBand tier={state.lessons} name="lessons" />
                <h3 className="px-3 pt-2 panel-label">Proposals, waiting on you: none reaches a run</h3>
                {proposals.length === 0 ? (
                    <Empty>no proposals wait on you now</Empty>
                ) : (
                    <MemoryRows entries={proposals.map((p) => p.entry)} ticket below={provenance} />
                )}
                <h3 className="border-t px-3 pt-2 panel-label">Lessons you promoted</h3>
                {lessons.length === 0 ? (
                    <Empty>
                        no lessons yet: promote a proposal with{' '}
                        <code className="font-mono text-xs">canopy memory promote ID</code>
                    </Empty>
                ) : (
                    <MemoryRows entries={lessons} />
                )}
                {digest !== null && <MemoryDigestView digest={digest} served="served to every run" />}
            </Panel>
        </div>
    )
}

/** Where a proposal came from: how its run ended, its ticket's state, and a warning on one from a private run. */
function Provenance({ proposal }: { proposal: MemoryProposal }) {
    return (
        <RowLine from="key" className="flex flex-wrap items-center gap-x-3 gap-y-1 text-xs text-muted-foreground">
            {proposal.run_kind !== null && (
                <span>
                    its run: <Word word={proposal.run_kind} />, ended <Word word={proposal.run_status ?? 'unknown'} />
                </span>
            )}
            <span>{proposal.ticket_done ? 'its ticket is done' : 'its ticket is not done yet'}</span>
            {proposal.private && <Chip tone="blocked">private: its text may hold what you kept off the tracker</Chip>}
        </RowLine>
    )
}
