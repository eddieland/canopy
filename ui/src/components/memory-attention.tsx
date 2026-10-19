import { useQuery } from '@tanstack/react-query'
import { Link } from '@tanstack/react-router'
import { useState } from 'react'

import { ApiError } from '@/api/client'
import { memoryQuery } from '@/api/queries'
import { MemoryRows, ProposalFacts } from '@/components/memory'
import { LessonActions, MemorySaid, ProposalActions } from '@/components/memory-actions'
import { Notice } from '@/components/notice'
import { Empty, PanelSkeleton } from '@/components/panel'
import { dueForReview } from '@/lib/memory'
import { useNow } from '@/lib/time'

// What the attention list's memory items show under their head (DESIGN §28, ROADMAP M52): the proposals from a done
// ticket's runs with Promote as written and Reject, the lessons due for review with Renew, and the way to the lessons
// a run reported wrong. Each reads every tier's memory, as the memory page does; an item leaves at the next tick once
// its cause is gone, as an answered one does.

/** A `memory_proposal` item: the proposals from `ticketKey`'s runs that still wait, each promoted as written or not. */
export function ProposalsWaiting({ ticketKey }: { ticketKey: string }) {
    const { data, error } = useQuery(memoryQuery)
    const [said, setSaid] = useState<string | null>(null)
    if (error instanceof ApiError) {
        return <Notice error={error} className="border-b p-3" />
    }
    if (data === undefined) {
        return <PanelSkeleton rows={2} className="min-h-32 border-b" />
    }
    const waiting = data.proposals.filter((p) => p.entry.ticket_key === ticketKey)
    const facts = new Map(waiting.map((p) => [p.entry.id, <ProposalFacts key={p.entry.id} proposal={p} />]))
    const below = new Map(
        waiting.map((p) => [
            p.entry.id,
            <ProposalActions key={p.entry.id} proposal={p.entry} edit={false} forget={false} onSaid={setSaid} />,
        ]),
    )
    return (
        <section aria-label="Proposals" className="border-b" data-testid="attention-proposals">
            {waiting.length === 0 ? (
                <Empty>none of its proposals waits now: the item leaves at the next tick</Empty>
            ) : (
                <MemoryRows
                    entries={waiting.map((p) => p.entry)}
                    facts={facts}
                    below={below}
                    lapses={new Map(waiting.map((p) => [p.entry.id, p.expires_at]))}
                />
            )}
            <MemorySaid said={said} className="border-t px-3 py-2" />
            <p className="border-t px-3 py-2 text-xs text-muted-foreground">
                To promote one in your own words or for another repository, open it on the{' '}
                <Link to="/memory" className="text-accent underline underline-offset-4 hover:decoration-2">
                    memory page
                </Link>
                .
            </p>
        </section>
    )
}

/**
 * A `lesson_review` item: the lessons whose review date has come, the longest overdue first, each renewed from its
 * row. Graduating one into a repository's AGENTS.md or a skill is a ticket and a PR; forgetting one is the memory
 * page's.
 */
export function LessonsDue() {
    const { data, error } = useQuery(memoryQuery)
    const now = useNow()
    const [said, setSaid] = useState<string | null>(null)
    if (error instanceof ApiError) {
        return <Notice error={error} className="border-b p-3" />
    }
    if (data === undefined) {
        return <PanelSkeleton rows={2} className="min-h-32 border-b" />
    }
    const due = dueForReview(data.lessons, now)
    const below = new Map(
        due.map((m) => [m.id, <LessonActions key={m.id} lesson={m} forget={false} onSaid={setSaid} />]),
    )
    return (
        <section aria-label="Lessons due" className="border-b" data-testid="attention-lessons-due">
            {due.length === 0 ? (
                <Empty>no lesson is due now: the item leaves at the next tick</Empty>
            ) : (
                <MemoryRows entries={due} digest={data.lessons_digest} below={below} />
            )}
            <MemorySaid said={said} className="border-t px-3 py-2" />
            <p className="border-t px-3 py-2 text-xs text-muted-foreground">
                Renew each you keep. Graduate one into a repository&apos;s AGENTS.md or a skill through a ticket, or
                forget it on the{' '}
                <Link to="/memory" className="text-accent underline underline-offset-4 hover:decoration-2">
                    memory page
                </Link>
                .
            </p>
        </section>
    )
}

/** A `lesson_wrong` item: the way to the lessons, where one a run reported wrong comes first, to renew or forget. */
export function LessonsWrong() {
    return (
        <p className="border-b p-3 text-sm" data-testid="attention-lessons-wrong">
            Read it on the{' '}
            <Link to="/memory" className="text-accent underline underline-offset-4 hover:decoration-2">
                memory page
            </Link>
            , where a lesson reported wrong heads the lessons, then renew it or forget it.
        </p>
    )
}
