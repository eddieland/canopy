import type { ReactNode } from 'react'

import type {
    MemoryDigest,
    MemoryEntry,
    MemoryOrigin,
    MemoryProposal,
    MemoryTier,
    RunMemory,
    RunState,
} from '@/api/types'
import { Age } from '@/components/age'
import { CopyButton } from '@/components/copy-button'
import { RowLine, ListRow } from '@/components/rows'
import { RunLink } from '@/components/run-link'
import { Chip, RunDot, Word } from '@/components/status'
import { TicketLink } from '@/components/ticket-link'
import { lapsesText, leftOutText, memorySegments, memoryStand, reviewText, tierMode, usedText } from '@/lib/memory'
import type { MemoryStand, TierModes } from '@/lib/memory'
import { memoryRef } from '@/lib/refs'
import { RUN_TEXT } from '@/lib/run-state'
import { localTime, useNow } from '@/lib/time'
import { cn } from '@/lib/utils'

// A proposal this close to lapsing undecided says so in the color of what waits on the operator.
const LAPSING_SOON_MS = 2 * 24 * 60 * 60 * 1000

// Each standing's run state, for its dot and its word's color: what calls for the operator in the colors of what is
// broken and what waits on them, a memory in force as done, one out of force as stopped.
const STAND_STATE: Record<MemoryStand, RunState> = {
    wrong: 'failed',
    due: 'blocked',
    pending: 'blocked',
    active: 'done',
    superseded: 'stopped',
    invalid: 'stopped',
    recorded: 'stopped',
}

// What each standing means, on hover, where the journal gives no reason of its own.
const STAND_TITLE: Record<MemoryStand, string> = {
    wrong: 'a run reported it wrong: renew it or forget it',
    due: 'its review date has come: renew it or forget it',
    pending: 'waiting on you: promote it or reject it',
    active: 'in force',
    superseded: 'replaced by a later one under its key',
    invalid: 'no longer in force',
    recorded: 'recorded: no run reads it while its tier records',
}

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
 * Memories, one row each, in the order every list reads: where it stands, a dot and a word, so a lesson reported wrong
 * or due for review shows at the left edge; its id; with `ticket`, its ticket, for a list across tickets; its
 * repository; its key; how many runs relied on it, once any has; and when it was written. Then what it says, plain,
 * and one line of where it came from. `facts` adds to that line by a row's id, such as how a proposal's run ended;
 * `below` adds what goes under a row, such as its verbs; `ownRun` leaves out the run whose page it is; `digest` is
 * what a run is served of the entries' tier, so a row in force that its cap leaves out says so; `cited` is what the
 * run whose page it is said of each, so a row it relied on or found wrong says so; `modes` is each tier's mode now, so
 * a memory in force under a tier that only records reads `recorded`, never `active`.
 */
export function MemoryRows({
    entries,
    ticket = false,
    facts,
    below,
    ownRun,
    digest,
    cited,
    modes,
}: {
    entries: MemoryEntry[]
    ticket?: boolean
    facts?: ReadonlyMap<number, ReactNode>
    below?: ReadonlyMap<number, ReactNode>
    ownRun?: number
    digest?: MemoryDigest | null | undefined
    cited?: Pick<RunMemory, 'used' | 'wrong'>
    modes?: TierModes | undefined
}) {
    const now = useNow()
    const served = new Set(digest?.ids)
    return (
        <ul className="divide-y" data-testid="memory-rows">
            {entries.map((entry) => (
                <ListRow
                    key={entry.id}
                    kind={ticket ? 'memory-across' : 'memory'}
                    className="group/copy"
                    data-testid={`memory-${entry.id}`}
                >
                    <MemoryStanding entry={entry} now={now} mode={modes && tierMode(entry.scope, modes)} />
                    {/* Copied, since Forget asks for it typed and the CLI's verbs take it. */}
                    <span className="flex min-w-0 items-center gap-0.5">
                        <span className="readout text-xs text-muted-foreground">{memoryRef(entry.id)}</span>
                        <CopyButton text={memoryRef(entry.id)} label={memoryRef(entry.id)} reveal />
                    </span>
                    {ticket && (
                        <span className="min-w-0">
                            {entry.ticket_key !== null && <TicketLink ticketKey={entry.ticket_key} />}
                        </span>
                    )}
                    <span className="flex min-w-0">
                        {entry.repo !== null && <Chip className="min-w-0 shrink" word={entry.repo} />}
                    </span>
                    <span className="truncate font-mono text-xs" title={entry.key}>
                        {entry.key}
                    </span>
                    <span
                        className="truncate text-right text-xs text-muted-foreground"
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
                    <RowLine
                        from="key"
                        className="flex flex-wrap items-center gap-x-3 gap-y-1 text-xs text-muted-foreground"
                    >
                        {entry.run_id !== null && entry.run_id !== ownRun && (
                            <span>
                                by <RunLink id={entry.run_id} />
                            </span>
                        )}
                        {facts?.get(entry.id)}
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
                        {entry.review_at !== null && entry.status === 'active' && (
                            <span
                                className={cn(
                                    Date.parse(entry.review_at) <= now &&
                                        (modes === undefined || modes.lessons === 'use') &&
                                        'text-status-blocked',
                                )}
                                title={`at ${localTime(entry.review_at)}`}
                            >
                                {reviewText(entry.review_at, now)}
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
 * Where a memory stands, a row's leading column: a dot in its state's color and its word, in that color, the reason on
 * hover. A lesson in force that a run reported wrong reads `wrong`, and one past its review date `due`, since those
 * call for the operator; a proposal is `pending` on them too; and one in force under a tier that only records,
 * `recorded`, muted, since no run reads it.
 */
function MemoryStanding({
    entry,
    now,
    mode,
}: {
    entry: MemoryEntry
    now: number
    mode: MemoryTier['mode'] | undefined
}) {
    const stand = memoryStand(entry, now, mode)
    const state = STAND_STATE[stand]
    return (
        <span
            className={cn('flex min-w-0 items-center gap-1.5 font-mono text-xs', RUN_TEXT[state])}
            title={entry.why ?? STAND_TITLE[stand]}
            data-testid="memory-stand"
        >
            <RunDot state={state} />
            <span className="truncate">{stand}</span>
        </span>
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
 * What a proposal's line of provenance adds, after the run that wrote it (`MemoryRows`' `facts`): how its run ended,
 * whether its ticket is done, when it lapses undecided (in `status-blocked` in its last two days), and, for a private
 * ticket's run, a `private` chip that says why on hover.
 */
export function ProposalFacts({ proposal }: { proposal: MemoryProposal }) {
    const now = useNow()
    const soon = Date.parse(proposal.expires_at) - now < LAPSING_SOON_MS
    return (
        <>
            {proposal.run_kind !== null && (
                <span>
                    <Word word={proposal.run_kind} />, ended <Word word={proposal.run_status ?? 'unknown'} />
                </span>
            )}
            <span>{proposal.ticket_done ? 'ticket done' : 'ticket not done yet'}</span>
            <span
                className={cn(soon && 'text-status-blocked')}
                title={`at ${localTime(proposal.expires_at)}`}
                data-testid="proposal-lapses"
            >
                {lapsesText(proposal.expires_at, now)}
            </span>
            {proposal.private && (
                <span
                    title="its run worked a private ticket: its text may hold what you kept off the tracker"
                    className="inline-flex"
                >
                    <Chip tone="blocked">private</Chip>
                </span>
            )}
        </>
    )
}
