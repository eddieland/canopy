import type { ReactNode } from 'react'

import type { MemoryDigest, MemoryEntry, MemoryTier } from '@/api/types'
import { Age } from '@/components/age'
import { RowLine, ListRow } from '@/components/rows'
import { RunLink } from '@/components/run-link'
import { Chip, Word } from '@/components/status'
import { TicketLink } from '@/components/ticket-link'
import { Timestamp } from '@/components/timestamp'
import { memorySegments, usedText } from '@/lib/memory'
import { memoryRef } from '@/lib/refs'
import { localTime } from '@/lib/time'
import { cn } from '@/lib/utils'

/**
 * What a worker wrote, or the operator for a lesson, as plain text (DESIGN §28): never Markdown or a link, and every
 * character that hides text named by its code point (`<U+200B>`), set apart so it is seen, as the CLI shows it.
 */
export function MemoryText({ text, className }: { text: string; className?: string }) {
    return (
        <span className={cn('break-words whitespace-pre-wrap', className)}>
            {memorySegments(text).map((segment, i) =>
                segment.hidden ? (
                    <span
                        key={i}
                        title="A character that hides text, which a model still reads"
                        className="rounded-xs border border-status-failed/40 bg-status-failed/10 font-mono text-2xs"
                    >
                        {segment.text}
                    </span>
                ) : (
                    <span key={i}>{segment.text}</span>
                ),
            )}
        </span>
    )
}

/**
 * A tier's band, heading its panel: its mode in words and what reads it, in words and never by color alone, so recorded
 * memory is never taken for memory in use. A tier in use wears the running tone: runs act on what it holds.
 */
export function MemoryBand({ tier, name }: { tier: MemoryTier; name: string }) {
    return (
        <p className="flex flex-wrap items-baseline gap-2 border-b px-3 py-2 text-sm" data-testid="memory-band">
            <Chip tone={tier.mode === 'use' ? 'running' : 'plain'}>
                {name}: {tier.words}
            </Chip>
            <span>{tier.band}</span>
        </p>
    )
}

/**
 * Memories, one row each: where it stands, id, key, how runs used it, and when it was written; then what it says,
 * plain, and where it came from. `ticket` names each note's ticket, for a list across tickets; `below` adds what goes
 * under a row, by its id, such as a proposal's provenance; `ownRun` leaves out the run whose page it is.
 */
export function MemoryRows({
    entries,
    ticket = false,
    below,
    ownRun,
}: {
    entries: MemoryEntry[]
    ticket?: boolean
    below?: ReadonlyMap<number, ReactNode>
    ownRun?: number
}) {
    return (
        <ul className="divide-y" data-testid="memory-rows">
            {entries.map((entry) => (
                <ListRow key={entry.id} kind="memory" data-testid={`memory-${entry.id}`}>
                    <span className="truncate text-xs" title={entry.why ?? undefined}>
                        <Word word={entry.status} />
                    </span>
                    <span className="readout text-xs text-muted-foreground">{memoryRef(entry.id)}</span>
                    <span className="flex min-w-0 items-center gap-2">
                        <span className="truncate font-mono text-xs">{entry.key}</span>
                        {ticket && entry.ticket_key !== null && <TicketLink ticketKey={entry.ticket_key} />}
                        {entry.repo !== null && <Chip>{entry.repo}</Chip>}
                    </span>
                    <span
                        className="truncate text-xs text-muted-foreground"
                        title={entry.last_used_at === null ? undefined : `last at ${localTime(entry.last_used_at)}`}
                    >
                        {usedText(entry)}
                    </span>
                    <Age at={entry.created_at} variant="ago" className="text-right" />
                    <RowLine from="key" className="text-sm">
                        {entry.text === null ? (
                            <span className="text-muted-foreground">text deleted</span>
                        ) : (
                            <MemoryText text={entry.text} />
                        )}
                    </RowLine>
                    <RowLine from="key" className="flex flex-wrap items-center gap-x-3 text-xs text-muted-foreground">
                        {entry.run_id !== null && entry.run_id !== ownRun && (
                            <span>
                                by <RunLink id={entry.run_id} />
                            </span>
                        )}
                        {entry.head !== null && <span className="font-mono">at {entry.head}</span>}
                        {entry.why !== null && <span>{entry.why}</span>}
                        {entry.review_at !== null && (
                            <span>
                                review at <Timestamp at={entry.review_at} />
                            </span>
                        )}
                        {entry.wrong_run_id !== null && (
                            <span className="text-status-failed">
                                reported wrong by <RunLink id={entry.wrong_run_id} />
                            </span>
                        )}
                    </RowLine>
                    {below?.get(entry.id)}
                </ListRow>
            ))}
        </ul>
    )
}

/**
 * What a run would be served of a tier, as its prompt would carry it, labelled by whether it is: `served to the next
 * run` at `use`, `would be served at use` while recording.
 */
export function MemoryDigestView({ digest, served }: { digest: MemoryDigest; served: string }) {
    return (
        <section aria-label={digest.served ? served : 'would be served at use'} className="border-t px-3 py-2">
            <p className="panel-label">{digest.served ? served : 'would be served at use'}</p>
            {/* canopy's own text, as the prompt carries it: the server named the hidden characters workers wrote. */}
            <pre
                className="mt-1 max-h-72 overflow-auto font-mono text-xs whitespace-pre-wrap"
                data-testid="memory-digest"
            >
                {digest.text}
            </pre>
        </section>
    )
}
