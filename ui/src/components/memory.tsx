import { useQuery } from '@tanstack/react-query'
import { Pin } from 'lucide-react'
import { useState } from 'react'
import type { ReactNode } from 'react'

import { memoryVersionsQuery } from '@/api/queries'
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
import { Copyable, CopyButton } from '@/components/copy-button'
import { Disclosure } from '@/components/disclosure'
import { VersionForget } from '@/components/memory-actions'
import { MemoryText } from '@/components/memory-text'
import { RowLine, ListRow } from '@/components/rows'
import { RunLink } from '@/components/run-link'
import { Chip, RunDot, Word } from '@/components/status'
import { TicketLink } from '@/components/ticket-link'
import { Clipped } from '@/components/tip'
import { Collapsible, CollapsibleContent } from '@/components/ui/collapsible'
import {
    byKind,
    lapsesText,
    leftOutText,
    leftText,
    hasVersions,
    memoryStand,
    readsText,
    readsTitle,
    reviewText,
    tierMode,
} from '@/lib/memory'
import type { MemoryStand, TierModes } from '@/lib/memory'
import { memoryRef } from '@/lib/refs'
import { RUN_TEXT } from '@/lib/run-state'
import { useClock } from '@/lib/clock'
import { localTime, useNow } from '@/lib/time'
import { cn } from '@/lib/utils'
import { Code } from '@/components/code'

// What `MemoryPurge` copies: the verb alone, since what it purges is the operator's to name in the shell.
const PURGE_COMMAND = 'canopy memory purge'

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
 * or due for review shows at the left edge; its id; with `ticket`, its ticket, for a list across tickets, or with
 * `across` that list's columns with the ticket's left empty, so lists stacked on one page line up; its
 * repository; its key; how many runs relied on it, once any has; and when it was written. Then what it says, plain,
 * and one line of where it came from. `facts` adds to that line by a row's id, such as how a proposal's run ended;
 * `below` adds what goes under a row, such as its verbs; `ownRun` leaves out the run whose page it is; `digest` is
 * what a run is served of the entries' tier, so a row in force that its cap leaves out says so; `cited` is what the
 * run whose page it is said of each, so a row it relied on or found wrong says so; `modes` is each tier's mode now, so
 * a memory in force under a tier that only records reads `recorded`, never `active`; `lapses` is when each proposal
 * lapses undecided, by its id, which its standing then says in place of `pending`, since every proposal is pending.
 * A memory with more than one version, a lesson edited or a note under a key a later run reused, says which it is and
 * opens its versions under it; with `onVersionSaid`, each version out of force that keeps its text has Forget, which
 * says what it did there.
 */
export function MemoryRows({
    entries,
    ticket = false,
    across = false,
    facts,
    below,
    ownRun,
    digest,
    cited,
    modes,
    lapses,
    onVersionSaid,
}: {
    entries: MemoryEntry[]
    ticket?: boolean
    across?: boolean
    facts?: ReadonlyMap<number, ReactNode>
    below?: ReadonlyMap<number, ReactNode>
    ownRun?: number
    digest?: MemoryDigest | null | undefined
    cited?: Pick<RunMemory, 'used' | 'wrong'>
    modes?: TierModes | undefined
    lapses?: ReadonlyMap<number, string>
    onVersionSaid?: (said: string) => void
}) {
    const now = useNow()
    const served = new Set(digest?.ids)
    return (
        <ul className="divide-y" data-testid="memory-rows">
            {entries.map((entry) => (
                <MemoryRow
                    key={entry.id}
                    entry={entry}
                    now={now}
                    ticket={ticket}
                    across={across}
                    facts={facts?.get(entry.id)}
                    below={below?.get(entry.id)}
                    ownRun={ownRun}
                    leftOut={digest && entry.status === 'active' && !served.has(entry.id) ? digest.served : undefined}
                    cited={cited}
                    modes={modes}
                    lapses={lapses?.get(entry.id)}
                    onVersionSaid={onVersionSaid}
                />
            ))}
        </ul>
    )
}

/**
 * What a run wrote or read, as its page lists it, grouped by kind: ticket notes, then proposals, then lessons, each
 * under a heading that names the kind, counts it, and says what it is for, since a row alone does not say whether it
 * is a note for one ticket or a lesson every run reads. `ownRun`, `cited`, and `modes` are `MemoryRows`'.
 */
export function MemoryKinds({
    entries,
    ownRun,
    cited,
    modes,
}: {
    entries: MemoryEntry[]
    ownRun: number
    cited?: Pick<RunMemory, 'used' | 'wrong'>
    modes: TierModes | undefined
}) {
    return byKind(entries).map((group) => (
        <section key={group.kind} aria-label={group.name} data-testid={`memory-kind-${group.kind}`}>
            <h4 className="flex flex-wrap items-center gap-x-2 px-3 pt-2 text-xs text-muted-foreground">
                <Chip>{group.name}</Chip>{' '}
                <span>
                    <span className="readout">{group.entries.length}</span> · {group.what}
                </span>
            </h4>
            <MemoryRows entries={group.entries} ownRun={ownRun} cited={cited} modes={modes} />
        </section>
    ))
}

/**
 * One memory's row in `MemoryRows`, a `Collapsible` whose content is its versions, read only once opened. `leftOut`
 * is whether its digest's cap leaves it out, `served` or recording, and undefined when it does not.
 */
function MemoryRow({
    entry,
    now,
    ticket,
    across,
    facts,
    below,
    ownRun,
    leftOut,
    cited,
    modes,
    lapses,
    onVersionSaid,
}: {
    entry: MemoryEntry
    now: number
    ticket: boolean
    across: boolean
    facts: ReactNode
    below: ReactNode
    ownRun: number | undefined
    leftOut: boolean | undefined
    cited: Pick<RunMemory, 'used' | 'wrong'> | undefined
    modes: TierModes | undefined
    lapses: string | undefined
    onVersionSaid: ((said: string) => void) | undefined
}) {
    const clock = useClock()
    const [open, setOpen] = useState(false)
    const byRun = entry.run_id !== null && entry.run_id !== ownRun
    return (
        <Collapsible asChild open={open} onOpenChange={setOpen}>
            <ListRow
                kind={ticket || across ? 'memory-across' : 'memory'}
                // Relative, so a quiet lesson's verbs can show over its end (`LessonActions`).
                className="group/copy relative"
                data-testid={`memory-${entry.id}`}
            >
                <MemoryStanding entry={entry} now={now} mode={modes && tierMode(entry.scope, modes)} lapses={lapses} />
                {/* Copied, since Forget asks for it typed and the CLI's verbs take it. */}
                <span className="flex min-w-0 items-center gap-0.5">
                    <span className="readout text-xs text-muted-foreground">{memoryRef(entry.id)}</span>
                    <CopyButton text={memoryRef(entry.id)} label={memoryRef(entry.id)} reveal />
                </span>
                {(ticket || across) && (
                    <span className="min-w-0">
                        {ticket && entry.ticket_key !== null && <TicketLink ticketKey={entry.ticket_key} />}
                    </span>
                )}
                <span className="flex min-w-0">
                    {entry.repo !== null && <Chip className="min-w-0 shrink" word={entry.repo} />}
                </span>
                <Clipped text={entry.key} className="font-mono text-xs" />
                <span
                    className="truncate text-right text-xs text-muted-foreground"
                    title={readsTitle(entry, (at) => localTime(at, clock))}
                >
                    {readsText(entry)}
                </span>
                <Age at={entry.created_at} variant="ago" className="text-right" />
                <RowLine from="key" className="text-sm">
                    {entry.text === null ? (
                        <span className="text-muted-foreground">text deleted</span>
                    ) : (
                        <MemoryText text={entry.text} lines />
                    )}
                </RowLine>
                <RowLine
                    from="key"
                    className="flex flex-wrap items-center gap-x-3 gap-y-1 text-xs text-muted-foreground"
                >
                    {/* First, and in the foreground, so a pin is seen wherever the row is listed. */}
                    {entry.pinned_at !== null && entry.status === 'active' && (
                        <span
                            className="flex items-center gap-1 text-foreground"
                            title={`pinned at ${localTime(entry.pinned_at, clock)}: never due, and served first`}
                        >
                            <Pin aria-hidden className="size-3 fill-current" />
                            pinned
                        </span>
                    )}
                    {/* The commit it was written against, on the run's hover, so the line stays one line. */}
                    {byRun && entry.run_id !== null && (
                        <span title={entry.head === null ? undefined : `written at ${entry.head}`}>
                            by <RunLink id={entry.run_id} />
                        </span>
                    )}
                    {facts}
                    {!byRun && entry.head !== null && <span className="font-mono">at {entry.head}</span>}
                    {entry.version > 1 && <span>version {entry.version}</span>}
                    {entry.edited && entry.promoted_from !== null && (
                        <span>edited from {memoryRef(entry.promoted_from)}</span>
                    )}
                    {entry.origin !== null && <Origin origin={entry.origin} />}
                    {cited?.used.includes(entry.id) === true && <span>this run relied on it</span>}
                    {cited?.wrong.includes(entry.id) === true && (
                        <span className="text-status-failed">this run found it wrong</span>
                    )}
                    <UsedIn entry={entry} ownRun={ownRun} />
                    {leftOut !== undefined && <span>{leftOutText(leftOut)}</span>}
                    {entry.why !== null && <span>{entry.why}</span>}
                    {entry.review_at !== null && entry.status === 'active' && (
                        <span
                            className={cn(
                                Date.parse(entry.review_at) <= now &&
                                    (modes === undefined || modes.lessons === 'use') &&
                                    'text-status-blocked',
                            )}
                            title={`at ${localTime(entry.review_at, clock)}`}
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
                {below}
                {hasVersions(entry) && (
                    <>
                        <RowLine from="key">
                            {/* No taller than a line of text, in line with the text above it. */}
                            <Disclosure open={open} what="versions" className="-my-1 -ml-2" />
                        </RowLine>
                        <CollapsibleContent asChild>
                            <RowLine from="key">
                                <MemoryVersions id={entry.id} onSaid={onVersionSaid} />
                            </RowLine>
                        </CollapsibleContent>
                    </>
                )}
            </ListRow>
        </Collapsible>
    )
}

/**
 * Every version of a memory, newest first (`canopy memory history`): which it is, its ref, where it stands, its
 * repository, how it was made, and when, then its words, plain. Those out of force are muted: no run reads them.
 * With `onSaid`, a version out of force that keeps its text has Forget, which says there what it did.
 */
function MemoryVersions({ id, onSaid }: { id: number; onSaid: ((said: string) => void) | undefined }) {
    const { data, error } = useQuery(memoryVersionsQuery(id))
    if (data === undefined) {
        return (
            <p className="min-h-4 text-xs text-muted-foreground">
                {error === null ? 'Reading its versions.' : `Its versions could not be read: ${error.message}`}
            </p>
        )
    }
    return (
        <ol aria-label="Versions, newest first" className="flex flex-col gap-2 border-l pl-3">
            {data.versions.map((version) => (
                <li
                    key={version.id}
                    className={cn('flex flex-col gap-0.5', version.status !== 'active' && 'text-muted-foreground')}
                    data-testid={`memory-version-${version.id}`}
                >
                    <span className="flex flex-wrap items-center gap-x-2 text-xs">
                        <span className="readout">v{version.version}</span>
                        <span className="readout">{memoryRef(version.id)}</span>
                        <span className="font-mono" title={version.why ?? undefined}>
                            {version.status}
                        </span>
                        {version.repo !== null && <Chip word={version.repo} />}
                        <VersionMade version={version} />
                        <Age at={version.created_at} variant="ago" />
                        {version.id === id && <span>this row</span>}
                    </span>
                    <span className="text-sm">
                        {version.text === null ? 'text deleted' : <MemoryText text={version.text} lines />}
                    </span>
                    {onSaid !== undefined && version.status !== 'active' && version.text !== null && (
                        <VersionForget version={version} onSaid={onSaid} />
                    )}
                </li>
            ))}
        </ol>
    )
}

/** How a version was made, as the CLI's history says it: a lesson edited or promoted, a note by its run. */
function VersionMade({ version }: { version: MemoryEntry }) {
    if (version.edited) {
        return <span>edited</span>
    }
    if (version.scope === 'lesson') {
        return <span>promoted</span>
    }
    if (version.run_id === null) {
        return null
    }
    return (
        <span>
            by <RunLink id={version.run_id} />
        </span>
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
    lapses,
}: {
    entry: MemoryEntry
    now: number
    mode: MemoryTier['mode'] | undefined
    lapses: string | undefined
}) {
    const clock = useClock()
    const stand = memoryStand(entry, now, mode)
    const state = STAND_STATE[stand]
    if (stand === 'pending' && lapses !== undefined) {
        // In a list of proposals every row is pending: the time it has left says more, in amber in its last days.
        const soon = Date.parse(lapses) - now < LAPSING_SOON_MS
        return (
            <span
                className={cn(
                    'flex min-w-0 items-center gap-1.5 font-mono text-xs',
                    soon ? RUN_TEXT.blocked : 'text-muted-foreground',
                )}
                title={`waiting on you: ${lapsesText(lapses, now)}, at ${localTime(lapses, clock)}`}
                data-testid="memory-stand"
            >
                <RunDot state="blocked" />
                <span className="truncate">{leftText(lapses, now)}</span>
            </span>
        )
    }
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
 * The latest runs that cited a memory as relied on, each a link to its page, and how many more did: those the use count
 * holds past the few named, and runs from before canopy named them. The run whose page it is is left out.
 */
function UsedIn({ entry, ownRun }: { entry: MemoryEntry; ownRun: number | undefined }) {
    const runs = entry.used_by.filter((id) => id !== ownRun)
    if (runs.length === 0) {
        return null
    }
    const more = entry.use_count - entry.used_by.length
    return (
        <span>
            cited in{' '}
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
 * What a run would be served of a tier, folded at its panel's foot until the operator asks to read it: `Show what
 * <who> is served`, or `would be served at use` while recording, opening the digest under it. `who` names the runs it
 * goes to (`every run`, `its next run`).
 */
export function MemoryDigestFold({ digest, who }: { digest: MemoryDigest; who: string }) {
    const [open, setOpen] = useState(false)
    const what = digest.served ? `what ${who} is served` : `what ${who} would be served at use`
    return (
        <Collapsible open={open} onOpenChange={setOpen} className="border-t px-3 py-1.5">
            <Disclosure open={open} what={what} className="-ml-2" data-testid="memory-digest-toggle" />
            <CollapsibleContent className="-mx-3 -mb-1.5">
                <MemoryDigestView digest={digest} served={`served to ${who}`} labelled={false} />
            </CollapsibleContent>
        </Collapsible>
    )
}

/**
 * What a proposal's line of provenance adds, after the run that wrote it (`MemoryRows`' `facts`): how its run ended,
 * whether its ticket is done, and, for a private ticket's run, a `private` chip that says why on hover. When it lapses
 * is its standing's (`MemoryRows`' `lapses`).
 */
export function ProposalFacts({ proposal }: { proposal: MemoryProposal }) {
    return (
        <>
            {proposal.run_kind !== null && (
                <span>
                    <Word word={proposal.run_kind} />, ended <Word word={proposal.run_status ?? 'unknown'} />
                </span>
            )}
            <span>{proposal.ticket_done ? 'ticket done' : 'ticket not done yet'}</span>
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

/**
 * `canopy memory purge`, the one memory verb the page does not have, with a button that copies it and the options that
 * name what it deletes. It stays the CLI's (DESIGN §28): a verb over many memories at once is not a click. What is
 * copied is the verb alone, which run as it is asks for one of them, so a paste never purges what no one named.
 */
export function MemoryPurge() {
    return (
        <p
            className="flex flex-wrap items-center gap-x-1.5 gap-y-1 text-xs text-muted-foreground"
            data-testid="memory-purge"
        >
            <span>Purge deletes the text of many memories at once, from your shell alone:</span>
            <Copyable text={PURGE_COMMAND} label="purge command" className="font-mono text-foreground" />
            <span>
                with <Code>--ticket KEY</Code> for what a ticket&apos;s runs wrote, <Code>--run ID</Code> for a
                run&apos;s, or <Code>--all</Code> for every memory, your lessons included.
            </span>
        </p>
    )
}
