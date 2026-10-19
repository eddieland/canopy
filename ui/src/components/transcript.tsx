import { ChevronRight, ChevronsUpDown, Rows3 } from 'lucide-react'
import { useState } from 'react'
import type { ReactNode } from 'react'

import type {
    Transcript,
    TranscriptEntry,
    TranscriptPrompt,
    TranscriptStep,
    TranscriptTokens,
    TranscriptTool,
} from '@/api/types'
import { ContextChart } from '@/components/context-chart'
import { Copyable } from '@/components/copy-button'
import { Cost } from '@/components/cost'
import { FoldButton } from '@/components/fold-button'
import { SearchField } from '@/components/input'
import { JsonTokens } from '@/components/json-text'
import { MarkedText } from '@/components/marked-text'
import { OrderToggle } from '@/components/order-toggle'
import { Empty, Panel, PanelHeader, PanelSkeleton } from '@/components/panel'
import { RowGrid, RowLine } from '@/components/rows'
import { Chip, RunDot } from '@/components/status'
import { Collapsible, CollapsibleContent, CollapsibleTrigger } from '@/components/ui/collapsible'
import { Toggle } from '@/components/ui/toggle'
import { useTranscriptView } from '@/hooks/use-transcript-view'
import type { TranscriptView } from '@/hooks/use-transcript-view'
import { setContextChartOpen, useContextChartOpen } from '@/lib/context-chart-open'
import type { TranscriptPage } from '@/lib/context-chart-open'
import { ordered, useListOrder } from '@/lib/list-order'
import { tokenize } from '@/lib/json-lines'
import { rowLineFrom } from '@/lib/rows'
import { markedTokens } from '@/lib/search'
import { localTime } from '@/lib/time'
import {
    byCall,
    callLine,
    contextShape,
    drawnRows,
    duration,
    elapsed,
    findQueryOf,
    hitsIn,
    moreLabel,
    outcome,
    sentTokens,
    shownOutput,
    signed,
    startOf,
    summary,
    tally,
    tokenCount,
    TRANSCRIPT_BUDGET,
    wroteTokens,
} from '@/lib/transcript'
import type { ModelCall as Call } from '@/lib/transcript'
import { cn } from '@/lib/utils'

// What a row marks with no search: one stable value, as a default prop must be.
const NO_WORDS: readonly string[] = []
// The calls a row inside a call is given: none, since it holds no model call's line.
const NO_CALLS: readonly Call[] = []

/**
 * A session's transcript (DESIGN §22): the agent's text, each tool call (what it did and how it ended on its line,
 * its input and output open on a click), each model call's cost, and the runtime's errors, in the order the runtime
 * printed them. Above them, a line naming the session's peak context and largest addition, which opens to a chart
 * of each model call's context and what grew it, whose entries show their rows; `page` is the kind of page it sits
 * on, each of which keeps the chart open or closed (src/lib/context-chart-open.ts). With two model calls or more, By
 * call, the same entries are grouped by the model call they came from, each opening to what it was sent and what it
 * did. In order, a search keeps the rows with a line that holds it, its matches marked, and opens a tool call whose
 * input or output holds it. A long transcript draws a page of its rows, or of its calls By call, and a fold after them
 * draws more (`TRANSCRIPT_BUDGET`). All of it is agent output, rendered as text. `running` says the session has not
 * ended: its events reach the log as the runtime prints them, so it is what the agent has done so far. Its header
 * names the session, on every page that shows one. With no events, it is its header alone, which says why in a few
 * words (`log gone`), the whole reason on hover. A page that shows a row from outside the panel passes the `view` it
 * holds (`useTranscriptView`).
 */
export function TranscriptPanel({
    transcript,
    running,
    page,
    view,
}: {
    transcript: Transcript | undefined
    running: boolean
    page: TranscriptPage
    view?: TranscriptView
}) {
    const own = useTranscriptView()
    const { grouped, setGrouped, typed, found, setTyped, target, show } = view ?? own
    const entries = transcript?.entries ?? []
    const counts = tally(entries)
    const calls = byCall(entries)
    const shape = contextShape(entries, transcript?.prompt ?? null)
    const chartOpen = useContextChartOpen(page)
    // One model call grouped is the events in order again.
    const groups = counts.calls > 1
    const callView = grouped && groups
    // The search is the events' in order: By call keeps its own, whole.
    const query = callView ? null : findQueryOf(found)
    const words = query === null ? [] : [query]
    // Bumped by All open, on or off: each call remounts open or closed, then toggles on its own. It wins over the
    // search it was made under; a new search opens the calls it finds again.
    const [opened, setOpened] = useState<{ open: boolean; round: number; query: string | null }>({
        open: false,
        round: 0,
        query: null,
    })
    const tools = entries.some((e) => e.kind === 'tool')
    const order = useListOrder('transcript')
    // Each entry with its place in the log, which is its identity: a log only ever grows at the end.
    const numbered = ordered(
        'transcript',
        order,
        entries.map((entry, i) => ({ entry, i, hits: query === null ? null : hitsIn(entry, query) })),
    )
    const shown = numbered.filter((n) => n.hits === null || n.hits.row + n.hits.body > 0)
    // By call's rows: the entries before the first call, then the calls.
    const callRows = calls.before.length + calls.calls.length
    // The rows drawn (TRANSCRIPT_BUDGET): a page of them, and each step a fold was asked for, until the transcript,
    // its view, or its search changes; and on through a row just shown, so it is drawn before it is scrolled to. The
    // draw-through is the showing's alone: a later search, view, or session starts again at a page.
    const budget = JSON.stringify([transcript?.session_id ?? null, callView, query])
    const round = target?.round ?? 0
    const [asked, setAsked] = useState({ budget, round: 0, rows: 0, through: 0 })
    const fresh = asked.budget !== budget || asked.round !== round
    const shownNow = asked.round !== round && target !== null && !callView
    const through = fresh ? (shownNow ? shown.findIndex((n) => n.i === target.i) + 1 : 0) : asked.through
    const rows = fresh ? 0 : asked.rows
    if (fresh) {
        setAsked({ budget, round, rows, through })
    }
    const drawn = callView ? drawnRows(callRows, rows, 0) : drawnRows(shown.length, rows, through)
    const more = () => setAsked({ budget, round, rows: drawn + TRANSCRIPT_BUDGET.step, through })
    // A search opens a call whose input or output holds it, until All open is turned on or off under it.
    const searchOpens = (hits: { body: number } | null) => hits !== null && hits.body > 0 && opened.query !== query
    // All open stays on while the calls stand open together: it was turned on, or a search opened what it found.
    const allOpen = opened.open || (!callView && shown.some((n) => searchOpens(n.hits)))
    const lines = shown.reduce((sum, n) => sum + (n.hits === null ? 0 : n.hits.row + n.hits.body), 0)
    // Why there is nothing to show, once read: the header says it, and the panel is that header alone.
    const why = transcript !== undefined && entries.length === 0 ? empty(transcript, running) : null
    return (
        // Its space is held only while it is read (No layout shift): read, it is as tall as what it holds.
        <Panel className={cn(transcript === undefined && 'min-h-40')} data-testid="transcript">
            <PanelHeader label="Transcript">
                <span className="flex flex-wrap items-center gap-3">
                    {transcript?.session_id && (
                        <Copyable
                            text={transcript.session_id}
                            label="session id"
                            className="readout hidden text-xs text-muted-foreground @lg:inline-flex"
                        >
                            <span title="open it with the runtime's tools too: opencode export <id>">
                                session {transcript.session_id}
                            </span>
                        </Copyable>
                    )}
                    {why !== null && (
                        <span className="readout text-xs text-muted-foreground" title={why.reason}>
                            {why.short}
                        </span>
                    )}
                    {transcript?.session_id && (entries.length > 1 || groups || tools) && (
                        // The session is what the transcript is; the modes after the rule are how it is shown.
                        <span aria-hidden className="hidden h-4 w-px bg-border @lg:inline" />
                    )}
                    <span className="flex items-center gap-1">
                        {entries.length > 1 && <OrderToggle list="transcript" />}
                        {groups && (
                            <Toggle
                                size="xs"
                                pressed={grouped}
                                onPressedChange={setGrouped}
                                title={grouped ? 'Show each event in order' : 'Group the events by model call'}
                            >
                                <Rows3 />
                                By call
                            </Toggle>
                        )}
                        {(tools || callView) && (
                            <Toggle
                                size="xs"
                                pressed={allOpen}
                                onPressedChange={(on) => setOpened((o) => ({ open: on, round: o.round + 1, query }))}
                                title={allOpen ? 'Close every call' : 'Open every call'}
                            >
                                <ChevronsUpDown />
                                All open
                            </Toggle>
                        )}
                    </span>
                </span>
            </PanelHeader>
            {transcript === undefined ? (
                <PanelSkeleton />
            ) : entries.length === 0 ? null : (
                <>
                    <div
                        className={cn(
                            'flex flex-wrap items-center gap-x-4 gap-y-1.5 px-3 pt-1.5',
                            // The context chart's line reads as the counts' second, in the same band.
                            shape.peak === null ? 'border-b pb-1.5' : 'pb-1',
                        )}
                    >
                        <p className="flex flex-wrap gap-x-4 font-mono text-xs text-muted-foreground">
                            <span>
                                {counts.tools} tool {counts.tools === 1 ? 'call' : 'calls'}
                                {counts.failed > 0 && (
                                    <>
                                        , <span className="text-status-failed">{counts.failed} failed</span>
                                    </>
                                )}
                                {counts.refused > 0 && (
                                    <>
                                        , <span className="text-status-failed">{counts.refused} refused</span>
                                    </>
                                )}
                            </span>
                            <span>
                                {counts.calls} model {counts.calls === 1 ? 'call' : 'calls'}
                            </span>
                            {counts.errors > 0 && (
                                <span className="text-status-failed">
                                    {counts.errors} runtime {counts.errors === 1 ? 'error' : 'errors'}
                                </span>
                            )}
                            {transcript.truncated && <span>cut: the log holds more than a page shows</span>}
                            {transcript.unreadable > 0 && <span>{transcript.unreadable} events could not be read</span>}
                        </p>
                        {!callView && (
                            <Find
                                value={typed}
                                onChange={setTyped}
                                lines={query === null ? null : lines}
                                rows={shown.length}
                            />
                        )}
                    </div>
                    <ContextChart
                        shape={shape}
                        onShow={show}
                        open={chartOpen}
                        onOpenChange={(open) => setContextChartOpen(page, open)}
                    />
                    {callView ? (
                        <ol className="divide-y" data-testid="transcript-calls">
                            {ordered('transcript', order, [
                                ...calls.before.map((entry, i) => (
                                    <Entry key={`before-${i}`} entry={entry} start={startOf(entries)} open={false} />
                                )),
                                ...calls.calls.map((call) => (
                                    <CallRow
                                        key={`${call.n}-${opened.round}`}
                                        call={call}
                                        step={shape.calls.find((c) => c.n === call.n)?.step ?? null}
                                        prompt={transcript.prompt}
                                        start={startOf(entries)}
                                        open={opened.open}
                                    />
                                )),
                            ]).slice(0, drawn)}
                            {drawn < callRows && <Fold label={moreLabel(callRows - drawn, 'calls')} onShow={more} />}
                        </ol>
                    ) : shown.length === 0 ? (
                        <Empty>no line holds “{query}”</Empty>
                    ) : (
                        <ol className="divide-y" data-testid="transcript-entries">
                            {shown.slice(0, drawn).map(({ entry, i, hits }) => {
                                const targeted = target?.i === i
                                // A row whose place changes remounts to it, as does the one the chart shows.
                                const open = opened.open || searchOpens(hits) || targeted
                                return (
                                    <Entry
                                        key={`${i}-${opened.round}-${open}-${targeted ? target.round : ''}`}
                                        entry={entry}
                                        start={startOf(entries)}
                                        open={open}
                                        words={words}
                                        targeted={targeted}
                                        calls={calls.calls}
                                        prompt={transcript.prompt}
                                    />
                                )
                            })}
                            {drawn < shown.length && (
                                <Fold label={moreLabel(shown.length - drawn, 'rows')} onShow={more} />
                            )}
                        </ol>
                    )}
                </>
            )}
        </Panel>
    )
}

/** The rows the page does not draw yet (`TRANSCRIPT_BUDGET`), and a button to draw the next of them. */
function Fold({ label, onShow }: { label: string; onShow: () => void }) {
    return (
        <li className="bg-surface-raised/50 px-1 py-0.5" data-testid="transcript-fold">
            <FoldButton label={label} onShow={onShow} />
        </li>
    )
}

/** Why a transcript shows no events: in a few words for its header, and whole for their hover. */
function empty(transcript: Transcript, running: boolean): { short: string; reason: string } {
    if (running) {
        // Its session is recorded at its first event, so before then there is none.
        return { short: 'no events yet', reason: 'no events yet: they show here as the agent prints them' }
    }
    switch (transcript.status) {
        case 'no_session': {
            return {
                short: 'no session',
                reason: 'the runtime reported no session: a template without --format json prints no events',
            }
        }
        case 'no_log': {
            return { short: 'log gone', reason: 'its log is gone, or is not a file canopy reads' }
        }
        case 'read': {
            return { short: 'no events', reason: 'the log holds none of the session’s events' }
        }
    }
}

/**
 * The transcript's search field: a magnifier, the field, how many lines and rows hold the query once there is one,
 * and a clear button. Escape empties it.
 */
function Find({
    value,
    onChange,
    lines,
    rows,
}: {
    value: string
    onChange: (value: string) => void
    lines: number | null
    rows: number
}) {
    return (
        <search className="ml-auto w-full @lg:w-72">
            <SearchField
                size="sm"
                aria-label="Find lines in the transcript"
                placeholder="Find lines"
                value={value}
                onChange={(event) => onChange(event.target.value)}
                onKeyDown={(event) => {
                    if (event.key === 'Escape') {
                        onChange('')
                    }
                }}
                onClear={() => onChange('')}
                clearLabel="Clear the transcript's search"
                end={
                    lines !== null && (
                        <span className="readout shrink-0 text-xs text-muted-foreground" data-testid="transcript-found">
                            {lines} {lines === 1 ? 'line' : 'lines'}, {rows} {rows === 1 ? 'row' : 'rows'}
                        </span>
                    )
                }
            />
        </search>
    )
}

/**
 * One event's row. In order, `calls` and `prompt` are the session's, so a model call's line opens to what that call
 * was sent and what it did; inside a call, which holds no model call's line, they are left out.
 */
function Entry({
    entry,
    start,
    open,
    words = NO_WORDS,
    targeted = false,
    calls = NO_CALLS,
    prompt = null,
}: {
    entry: TranscriptEntry
    start: string | null
    open: boolean
    words?: readonly string[]
    targeted?: boolean
    calls?: readonly Call[]
    prompt?: TranscriptPrompt | null
}) {
    switch (entry.kind) {
        case 'text': {
            return (
                <Row at={entry.at} start={start} targeted={targeted}>
                    <p
                        className={cn(
                            'min-w-0 flex-1 text-sm break-words whitespace-pre-wrap',
                            entry.reasoning && 'text-muted-foreground italic',
                        )}
                    >
                        {entry.reasoning && <span className="panel-label mr-2 not-italic">thinking</span>}
                        <MarkedText text={entry.text} words={words} />
                    </p>
                    {entry.cut && <Chip>cut</Chip>}
                </Row>
            )
        }
        case 'tool': {
            return <Tool entry={entry} start={start} open={open} words={words} targeted={targeted} />
        }
        case 'step': {
            const call = calls.find((c) => c.n === entry.call) ?? null
            return <ModelCall entry={entry} start={start} call={call} prompt={prompt} />
        }
        case 'error': {
            return (
                <Row at={entry.at} start={start} targeted={targeted} className={cn(!targeted && 'bg-status-failed/8')}>
                    <span className="font-mono text-xs text-status-failed">
                        <MarkedText text={entry.name} words={words} />
                    </span>
                    <p className="min-w-0 flex-1 text-sm break-words whitespace-pre-wrap">
                        <MarkedText text={entry.message} words={words} />
                    </p>
                </Row>
            )
        }
    }
}

/**
 * An entry's line: when it was printed, from the session's first event, then the entry. The one last shown, by the
 * context chart or the Run panel's `ended on`, sits on the accent's tint, scrolled to and focused.
 */
function Row({
    at,
    start,
    targeted = false,
    className,
    children,
}: {
    at: string | null
    start: string | null
    targeted?: boolean
    className?: string
    children: ReactNode
}) {
    return (
        <li
            ref={targeted ? reveal : undefined}
            tabIndex={targeted ? -1 : undefined}
            className={cn('flex items-baseline gap-3 px-3 py-2 outline-none', targeted && 'bg-accent/14', className)}
        >
            <When at={at} start={start} />
            {children}
        </li>
    )
}

/** Scrolls the row last shown to the middle of the window, and gives it the focus. */
function reveal(element: HTMLElement | null) {
    element?.scrollIntoView({ block: 'center' })
    element?.focus({ preventScroll: true })
}

function When({ at, start }: { at: string | null; start: string | null }) {
    return (
        <span
            className="readout w-14 shrink-0 text-xs text-muted-foreground"
            title={at === null ? undefined : localTime(at)}
        >
            {elapsed(at, start)}
        </span>
    )
}

/**
 * A tool call: one line, its name, what it did, and how it ended (refused, or what it printed when that is short),
 * that opens to its input and its output or error.
 */
function Tool({
    entry,
    start,
    open,
    words,
    targeted,
}: {
    entry: TranscriptTool
    start: string | null
    open: boolean
    words: readonly string[]
    targeted: boolean
}) {
    const { verdict, guard, line } = outcome(entry)
    const failed = verdict !== 'done'
    const did = summary(entry)
    return (
        <li data-testid="transcript-tool" className={cn(targeted && 'bg-accent/14')}>
            <details open={open} className="group">
                <summary
                    ref={targeted ? reveal : undefined}
                    className={cn(
                        'flex cursor-pointer list-none items-center gap-3 px-3 py-2 hover:bg-surface-raised',
                        '[&::-webkit-details-marker]:hidden',
                    )}
                >
                    <When at={entry.at} start={start} />
                    <RunDot state={failed ? 'failed' : 'done'} />
                    {/* The name takes its own width up to 14rem and gives way first; the command takes the rest. */}
                    <span className="max-w-56 truncate font-mono text-xs" title={entry.tool}>
                        <MarkedText text={entry.tool} words={words} />
                    </span>
                    <span className="flex min-w-40 flex-1 flex-col">
                        {/* A shell call's title is what the agent said it was for: the command is what it did. */}
                        <span className="truncate font-mono text-xs" title={entry.title ?? did}>
                            <MarkedText text={did} words={words} />
                        </span>
                        {line !== null && (
                            <span
                                className={cn('truncate text-xs text-muted-foreground', failed && 'text-status-failed')}
                                title={line}
                            >
                                <MarkedText text={line} words={words} />
                            </span>
                        )}
                    </span>
                    {verdict === 'refused' && (
                        <Chip tone="failed" className="min-w-0 shrink" word={`refused:${guard ?? ''}`} />
                    )}
                    {entry.cut && <Chip>cut</Chip>}
                    <span className="readout w-14 shrink-0 text-right text-xs text-muted-foreground">
                        {entry.duration_ms === null ? '' : duration(entry.duration_ms)}
                    </span>
                    <ChevronRight
                        className={cn(
                            'size-3 shrink-0 text-muted-foreground',
                            'transition-transform group-open:rotate-90',
                        )}
                    />
                </summary>
                <RowGrid kind="transcript" className="pb-3">
                    <RowLine from="text" className="flex flex-col gap-2">
                        <Block label="input" words={words}>
                            {entry.input}
                        </Block>
                        <Block label={entry.status === 'error' ? 'error' : 'output'} failed={failed} words={words}>
                            {shownOutput(entry)}
                        </Block>
                    </RowLine>
                </RowGrid>
            </details>
        </li>
    )
}

/**
 * A model call's end: one muted line, its number, its reason, its tokens in and out as By call says them, and its
 * cost, that opens to its tokens by kind and then to what the call was sent and what it did, as By call shows them.
 * The body is built only once opened, as By call's is: a long session's calls would hold every output twice.
 */
function ModelCall({
    entry,
    start,
    call,
    prompt,
}: {
    entry: TranscriptStep
    start: string | null
    call: Call | null
    prompt: TranscriptPrompt | null
}) {
    const [open, setOpen] = useState(false)
    const line = (
        <>
            <When at={entry.at} start={start} />
            <span>model call{entry.call === null ? '' : ` ${entry.call}`}</span>
            {/* Every call but the last ends in tool calls: only another reason says something. */}
            {entry.reason && entry.reason !== 'tool-calls' && <Chip word={entry.reason} />}
            <span className="readout ml-auto">
                {entry.split === null
                    ? ''
                    : `${tokenCount(sentTokens(entry.split))} in · ${tokenCount(wroteTokens(entry.split))} out`}
            </span>
            <Cost usd={entry.cost_usd} className="w-14 shrink-0 text-right" />
        </>
    )
    const muted = 'flex items-center gap-3 px-3 py-1 font-mono text-xs text-muted-foreground'
    const split = entry.split
    if (split === null && call === null) {
        return (
            <li className={muted}>
                {line}
                <span className="size-3 shrink-0" />
            </li>
        )
    }
    return (
        <li data-testid="transcript-step">
            <details className="group" onToggle={(e) => setOpen(e.currentTarget.open)}>
                <summary
                    className={cn(
                        muted,
                        'cursor-pointer list-none hover:bg-surface-raised',
                        '[&::-webkit-details-marker]:hidden',
                    )}
                >
                    {line}
                    <ChevronRight
                        className={cn(
                            'size-3 shrink-0 text-muted-foreground',
                            'transition-transform group-open:rotate-90',
                        )}
                    />
                </summary>
                {open && split !== null && (
                    <RowGrid kind="transcript" className="pb-2">
                        <dl className={cn(rowLineFrom('text'), 'flex flex-wrap gap-x-6 gap-y-1 font-mono text-xs')}>
                            {TOKEN_KINDS.map(([key, label]) => (
                                <div key={key} className="flex items-baseline gap-2">
                                    <dt className="panel-label">{label}</dt>
                                    <dd className="readout" title={`${split[key]} tokens`}>
                                        {tokenCount(split[key])}
                                    </dd>
                                </div>
                            ))}
                        </dl>
                    </RowGrid>
                )}
                {open && call !== null && <CallBody call={call} prompt={prompt} start={start} split={split} />}
            </details>
        </li>
    )
}

/** A model call's token kinds, in the order the runtime reports them, as the page labels them. */
const TOKEN_KINDS = [
    ['input', 'input'],
    ['cache_read', 'cache read'],
    ['cache_write', 'cache write'],
    ['output', 'output'],
    ['reasoning', 'reasoning'],
] as const

/**
 * A model call, by call: one line, its number, what it did, and its tokens in and out and its cost, that opens to its
 * input and its output. The first call's input is the prompt canopy kept; what is new in a later call's is what its
 * tools returned to the call before it. Ahead of all of it the runtime sends the agent's definition and its own
 * system prompt and tools, which no file records. The body is built only once opened: a long session's calls would
 * hold every output twice.
 */
function CallRow({
    call,
    step,
    prompt,
    start,
    open,
}: {
    call: Call
    step: number | null
    prompt: TranscriptPrompt | null
    start: string | null
    open: boolean
}) {
    const end = call.end
    const split = end?.split ?? null
    const first = call.output[0]?.at ?? end?.at ?? null
    // Its step on the call before, after its input: `30.2k in (+4.3k)`.
    const grew = step === null ? '' : ` (${signed(step)})`
    return (
        <Collapsible asChild defaultOpen={open}>
            <li data-testid="transcript-call" className="group/call">
                <CollapsibleTrigger
                    className={cn(
                        'flex w-full cursor-pointer items-center gap-3 px-3 py-2 text-left hover:bg-surface-raised',
                    )}
                >
                    <When at={first} start={start} />
                    <span className="w-14 shrink-0 font-mono text-xs">call {call.n}</span>
                    <span className="min-w-0 flex-1 truncate text-xs text-muted-foreground" title={callLine(call)}>
                        {callLine(call)}
                    </span>
                    {end === null && <Chip word="unfinished" />}
                    {end?.reason && end.reason !== 'tool-calls' && <Chip word={end.reason} />}
                    <span
                        className="readout hidden shrink-0 text-xs text-muted-foreground @lg:inline"
                        title={step === null ? undefined : `in: ${signed(step)} on call ${call.n - 1}`}
                    >
                        {split === null
                            ? ''
                            : `${tokenCount(sentTokens(split))} in${grew} · ${tokenCount(wroteTokens(split))} out`}
                    </span>
                    <Cost
                        usd={end?.cost_usd ?? null}
                        className="w-14 shrink-0 text-right text-xs text-muted-foreground"
                    />
                    <ChevronRight
                        className={cn(
                            'size-3 shrink-0 text-muted-foreground',
                            'transition-transform group-data-[state=open]/call:rotate-90',
                        )}
                    />
                </CollapsibleTrigger>
                <CollapsibleContent>
                    <CallBody call={call} prompt={prompt} start={start} split={split} />
                </CollapsibleContent>
            </li>
        </Collapsible>
    )
}

function CallBody({
    call,
    prompt,
    start,
    split,
}: {
    call: Call
    prompt: TranscriptPrompt | null
    start: string | null
    split: TranscriptTokens | null
}) {
    return (
        // In a narrow panel the body takes the row's whole width; in a wider one it starts under the text.
        <RowGrid kind="transcript" className="pb-3" data-testid="transcript-call-body">
            <RowLine from="text" className="flex flex-col gap-3 @max-lg:col-[time/end]">
                <section className="flex flex-col gap-2" aria-label={`call ${call.n} input`}>
                    <Heading
                        label="input"
                        tokens={split === null ? null : sentTokens(split)}
                        detail={split === null ? null : `${tokenCount(split.cache_read)} read from the cache`}
                    />
                    {call.n === 1 ? (
                        prompt === null ? (
                            <p className="text-xs text-muted-foreground">canopy kept no prompt for this session</p>
                        ) : (
                            <Block label={prompt.truncated ? 'prompt, cut' : 'prompt'}>{prompt.text}</Block>
                        )
                    ) : (
                        <>
                            <p className="text-xs text-muted-foreground">
                                {call.returned.length === 0
                                    ? `call ${call.n - 1}’s input and output, and nothing returned since`
                                    : `call ${call.n - 1}’s input and output, then what its tools returned:`}
                            </p>
                            {call.returned.map((tool, i) => (
                                // oxlint-disable-next-line react/no-array-index-key -- a call's tools never reorder
                                <Returned key={i} tool={tool} />
                            ))}
                        </>
                    )}
                    {call.n === 1 && (
                        <p className="text-xs text-muted-foreground">
                            sent after the agent’s definition and the runtime’s own system prompt and tools, which no
                            file records
                        </p>
                    )}
                </section>
                <section className="flex flex-col gap-2" aria-label={`call ${call.n} output`}>
                    <Heading
                        label="output"
                        tokens={split === null ? null : wroteTokens(split)}
                        detail={
                            split === null || split.reasoning === 0 ? null : `${tokenCount(split.reasoning)} reasoning`
                        }
                    />
                    {call.output.length === 0 ? (
                        <p className="text-xs text-muted-foreground">nothing printed</p>
                    ) : (
                        <ol className="divide-y rounded-sm border">
                            {call.output.map((entry, i) => (
                                // oxlint-disable-next-line react/no-array-index-key -- a call's entries never reorder
                                <Entry key={i} entry={entry} start={start} open={false} />
                            ))}
                        </ol>
                    )}
                </section>
            </RowLine>
        </RowGrid>
    )
}

/** A call's input or output label, with its tokens when the runtime counted them. */
function Heading({ label, tokens, detail }: { label: string; tokens: number | null; detail: string | null }) {
    return (
        <span className="flex items-baseline gap-3">
            <span className="panel-label">{label}</span>
            {tokens !== null && (
                <span className="readout text-xs text-muted-foreground" title={`${tokens} tokens`}>
                    {tokenCount(tokens)} tokens{detail === null ? '' : `, ${detail}`}
                </span>
            )}
        </span>
    )
}

/** What one tool call returned, as the next model call was sent it: the call on one line, then its output or error. */
function Returned({ tool }: { tool: TranscriptTool }) {
    const failed = outcome(tool).verdict !== 'done'
    return (
        <div className="flex flex-col gap-1">
            <span className="flex min-w-0 items-baseline gap-2 font-mono text-xs">
                <RunDot state={failed ? 'failed' : 'done'} />
                <span className="shrink-0">{tool.tool}</span>
                <span className="truncate text-muted-foreground" title={summary(tool)}>
                    {summary(tool)}
                </span>
            </span>
            <Pre failed={failed}>{shownOutput(tool)}</Pre>
        </div>
    )
}

function Block({
    label,
    failed = false,
    words = NO_WORDS,
    children,
}: {
    label: string
    failed?: boolean
    words?: readonly string[]
    children: string
}) {
    return (
        <div className="flex flex-col gap-1">
            <span className={cn('panel-label', failed && 'text-status-failed')}>{label}</span>
            <Pre failed={failed} words={words}>
                {children}
            </Pre>
        </div>
    )
}

function Pre({
    failed = false,
    words = NO_WORDS,
    children,
}: {
    failed?: boolean
    words?: readonly string[]
    children: string
}) {
    return (
        <pre
            className={cn(
                'max-h-96 overflow-auto rounded-sm border bg-background p-2',
                'font-mono text-xs break-words whitespace-pre-wrap',
                failed && 'border-status-failed/40',
            )}
        >
            <JsonTokens tokens={markedTokens(tokenize(children), words)} />
        </pre>
    )
}
