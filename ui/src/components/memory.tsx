import type { ReactNode } from 'react'

import type { MemoryDigest, MemoryEntry, MemoryOrigin, MemoryProposal, MemoryTier, RunMemory } from '@/api/types'
import { Age } from '@/components/age'
import { CopyButton } from '@/components/copy-button'
import { RowLine, ListRow } from '@/components/rows'
import { RunLink } from '@/components/run-link'
import { Chip, Word } from '@/components/status'
import { TicketLink } from '@/components/ticket-link'
import { Timestamp } from '@/components/timestamp'
import { lapsesText, leftOutText, memorySegments, usedText } from '@/lib/memory'
import { memoryRef } from '@/lib/refs'
import { localTime, useNow } from '@/lib/time'
import { cn } from '@/lib/utils'

// A proposal this close to lapsing undecided says so in the color of what waits on the operator.
const LAPSING_SOON_MS = 2 * 24 * 60 * 60 * 1000

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
 * under a row, by its id, such as a proposal's provenance; `ownRun` leaves out the run whose page it is; `digest` is
 * what a run is served of the entries' tier, so a row in force that its cap leaves out says so; `cited` is what the
 * run whose page it is said of each, so a row it relied on or found wrong says so.
 */
export function MemoryRows({
    entries,
    ticket = false,
    below,
    ownRun,
    digest,
    cited,
}: {
    entries: MemoryEntry[]
    ticket?: boolean
    below?: ReadonlyMap<number, ReactNode>
    ownRun?: number
    digest?: MemoryDigest | null | undefined
    cited?: Pick<RunMemory, 'used' | 'wrong'>
}) {
    const served = new Set(digest?.ids)
    return (
        <ul className="divide-y" data-testid="memory-rows">
            {entries.map((entry) => (
                <ListRow key={entry.id} kind="memory" className="group/copy" data-testid={`memory-${entry.id}`}>
                    <span className="truncate text-xs" title={entry.why ?? undefined}>
                        <Word word={entry.status} />
                    </span>
                    {/* Copied, since Forget asks for it typed and the CLI's verbs take it. */}
                    <span className="flex min-w-0 items-center gap-0.5">
                        <span className="readout text-xs text-muted-foreground">{memoryRef(entry.id)}</span>
                        <CopyButton text={memoryRef(entry.id)} label={memoryRef(entry.id)} reveal />
                    </span>
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
                        {entry.origin !== null && <Origin origin={entry.origin} />}
                        {cited?.used.includes(entry.id) === true && <span>this run relied on it</span>}
                        {cited?.wrong.includes(entry.id) === true && (
                            <span className="text-status-failed">this run found it wrong</span>
                        )}
                        <UsedIn entry={entry} ownRun={ownRun} />
                        {digest && entry.status === 'active' && !served.has(entry.id) && (
                            <span>{leftOutText(digest.served)}</span>
                        )}
                        {entry.why !== null && <span>{entry.why}</span>}
                        {entry.review_at !== null && (
                            <span>
                                review at <Timestamp at={entry.review_at} />
                            </span>
                        )}
                        {entry.wrong_run_id !== null && (
                            <span className="text-status-failed">
                                reported wrong by <RunLink id={entry.wrong_run_id} />
                                {entry.wrong_at !== null && (
                                    <>
                                        {' '}
                                        <Age at={entry.wrong_at} variant="ago" className="text-status-failed" />
                                    </>
                                )}
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
 * What a lesson was promoted from, as the CLI names it, `from proposal memory:7 of ABC-103`, then the run that wrote
 * it.
 */
function Origin({ origin }: { origin: MemoryOrigin }) {
    return (
        <span>
            from {origin.scope} {memoryRef(origin.id)}
            {origin.ticket_key !== null && (
                <>
                    {' '}
                    of <TicketLink ticketKey={origin.ticket_key} />
                </>
            )}
            {origin.run_id !== null && (
                <>
                    {', by '}
                    <RunLink id={origin.run_id} />
                </>
            )}
        </span>
    )
}

/**
 * The latest runs that relied on a memory, each a link to its page, and how many more did: those the use count holds
 * past the few named, and runs from before canopy named them. The run whose page it is is left out.
 */
function UsedIn({ entry, ownRun }: { entry: MemoryEntry; ownRun: number | undefined }) {
    const runs = entry.used_by.filter((id) => id !== ownRun)
    if (runs.length === 0) {
        return null
    }
    const more = entry.use_count - entry.used_by.length
    return (
        <span>
            used in{' '}
            {runs.map((id, i) => (
                <span key={id}>
                    {i > 0 && ', '}
                    <RunLink id={id} />
                </span>
            ))}
            {more > 0 && ` and ${more} more`}
        </span>
    )
}

/**
 * What a run would be served of a tier, as its prompt would carry it, labelled by whether it is: `served to the next
 * run` at `use`, `would be served at use` while recording. With `labelled` false, as under a disclosure that already
 * says so, the label is left to screen readers.
 */
export function MemoryDigestView({
    digest,
    served,
    labelled = true,
}: {
    digest: MemoryDigest
    served: string
    labelled?: boolean
}) {
    const label = digest.served ? served : 'would be served at use'
    return (
        <section aria-label={label} className="border-t px-3 py-2">
            {labelled && <p className="panel-label">{label}</p>}
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

/**
 * Where a proposal came from, under its row: how its run ended, its ticket's state, when it lapses undecided (in
 * `status-blocked` in its last two days), and a private run's warning.
 */
export function ProposalProvenance({ proposal }: { proposal: MemoryProposal }) {
    const now = useNow()
    const soon = Date.parse(proposal.expires_at) - now < LAPSING_SOON_MS
    return (
        <RowLine from="key" className="flex flex-wrap items-center gap-x-3 gap-y-1 text-xs text-muted-foreground">
            {proposal.run_kind !== null && (
                <span>
                    its run: <Word word={proposal.run_kind} />, ended <Word word={proposal.run_status ?? 'unknown'} />
                </span>
            )}
            <span>{proposal.ticket_done ? 'its ticket is done' : 'its ticket is not done yet'}</span>
            <span
                className={cn(soon && 'text-status-blocked')}
                title={`at ${localTime(proposal.expires_at)}`}
                data-testid="proposal-lapses"
            >
                {lapsesText(proposal.expires_at, now)}
            </span>
            {proposal.private && <Chip tone="blocked">private: its text may hold what you kept off the tracker</Chip>}
        </RowLine>
    )
}
