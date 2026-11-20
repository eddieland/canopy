import {
    ChevronRight,
    ChevronsUpDown,
    FilePen,
    FileText,
    Globe,
    Rows3,
    Search,
    Sprout,
    SquareTerminal,
    Wrench,
} from 'lucide-react'
import type { LucideIcon } from 'lucide-react'
import { useState } from 'react'
import type { ReactNode } from 'react'

import type {
    RunWorktree,
    Transcript,
    TranscriptEntry,
    TranscriptPrompt,
    TranscriptStep,
    TranscriptTokens,
    TranscriptTool,
} from '@/api/types'
import { CanopyBody, CanopyLine, DiffBlock } from '@/components/canopy-call'
import { ContextChart } from '@/components/context-chart'
import { Copyable } from '@/components/copy-button'
import { Cost } from '@/components/cost'
import { FoldButton } from '@/components/fold-button'
import { SearchField } from '@/components/input'
import { JsonTokens } from '@/components/json-text'
import { LetteredOption } from '@/components/lettered-option'
import { LinkedText } from '@/components/linked-text'
import { MarkedText } from '@/components/marked-text'
import { MoreLines } from '@/components/more-lines'
import { OrderToggle } from '@/components/order-toggle'
import { Empty, Panel, PanelHeader, PanelScroll, PanelSkeleton } from '@/components/panel'
import { RichText } from '@/components/rich-text'
import { RowGrid, RowLine } from '@/components/rows'
import { RunProgress } from '@/components/run-progress'
import { Chip, RunDot } from '@/components/status'
import { Collapsible, CollapsibleContent, CollapsibleTrigger } from '@/components/ui/collapsible'
import { Toggle } from '@/components/ui/toggle'
import { RunWorktreesContext, useRunWorktrees } from '@/hooks/use-run-worktrees'
import { useTranscriptView } from '@/hooks/use-transcript-view'
import type { TranscriptView } from '@/hooks/use-transcript-view'
import { canopyCall, diffLinesOf } from '@/lib/canopy-calls'
import { useClock } from '@/lib/clock'
import { setContextChartOpen, useContextChartOpen } from '@/lib/context-chart-open'
import type { TranscriptPage } from '@/lib/context-chart-open'
import { tokenize } from '@/lib/json-lines'
import { LETTERS } from '@/lib/lettered-options'
import { ordered, useListOrder } from '@/lib/list-order'
import { removedAfter } from '@/lib/retention'
import { rowLineFrom } from '@/lib/rows'
import { marked, markedTokens } from '@/lib/search'
import { localTime } from '@/lib/time'
import {
    byCall,
    callLine,
    cardOf,
    contextShape,
    decisionsOf,
    drawnRows,
    duration,
    elapsed,
    findQueryOf,
    foldText,
    heardOf,
    hitsIn,
    moreLabel,
    namedModels,
    outcome,
    resultOf,
    sentTokens,
    settingsOf,
    settingSubject,
    shellCall,
    shownOutput,
    signed,
    startOf,
    summary,
    summaryTitle,
    tally,
    THINKING_LINES,
    THIS_TICK,
    tokenCount,
    toolKind,
    TRANSCRIPT_BUDGET,
    wroteTokens,
} from '@/lib/transcript'
import type {
    CallCard,
    CallContext,
    CallDecision,
    CallResult,
    CallSetting,
    ContextShape,
    ModelCall as Call,
    ShellCall,
    ToolKind,
} from '@/lib/transcript'
import { cn } from '@/lib/utils'

// What a row marks with no search: one stable value, as a default prop must be.
const NO_WORDS: readonly string[] = []
// The calls a row inside a call is given: none, since it holds no model call's line.
const NO_CALLS: readonly Call[] = []
// The models a row inside a call is given: none, for the same reason.
const NO_MODELS: ReadonlyMap<number, string> = new Map()
// The worktrees of a transcript that is not a run's: none, so a shell call's directory stays whole.
const NO_WORKTREES: readonly RunWorktree[] = []

/**
 * A session's transcript (DESIGN §22): the agent's text, each tool call (what it did and how it ended on its line,
 * its input and output open on a click), each model call's cost, and the runtime's errors, in the order the runtime
 * printed them. Above them, a line naming the session's peak context and largest addition, which opens to a chart
 * of each model call's context and what grew it, whose entries show their rows; `page` is the kind of page it sits
 * on, each of which keeps the chart open or closed (src/lib/context-chart-open.ts). With two model calls or more, By
 * call, the same entries are grouped by the model call they came from, each opening to what it was sent and what it
 * did. A run more than one model served names the model on its first call's line, and on each later call's whose
 * model is not the call before's (`namedModels`), so the switch shows where it happened. In order, a search keeps the
 * rows with a line that holds it, its matches marked, and opens a tool call whose input or output holds it. A long
 * transcript draws a page of its rows, or of its calls By call, and a fold after them draws more (`TRANSCRIPT_BUDGET`),
 * in a region that scrolls inside the panel past most of the window's height.
 * All of it is agent output, rendered as text. `running` says the session has not ended: its events reach the log as
 * the runtime prints them, so it is what the agent has done so far. Its header names the session, on every page that
 * shows one. With no events, it is its header alone, which says why in a few words (`log gone`), the whole reason on
 * hover. A page that shows a row from outside the panel passes the `view` it holds (`useTranscriptView`). A run's page
 * passes its `worktrees`, which a shell call's line reads its directory against (`summary`); other pages pass none.
 */
export function TranscriptPanel({
    transcript,
    running,
    page,
    view,
    worktrees = NO_WORKTREES,
}: {
    transcript: Transcript | undefined
    running: boolean
    page: TranscriptPage
    view?: TranscriptView
    worktrees?: readonly RunWorktree[]
}) {
    const own = useTranscriptView()
    const { grouped, setGrouped, typed, found, setTyped, target, show } = view ?? own
    const entries = transcript?.entries ?? []
    const counts = tally(entries)
    const calls = byCall(entries)
    const models = namedModels(entries)
    const shape = contextShape(entries, transcript?.prompt ?? null)
    const chartOpen = useContextChartOpen(page)
    // One model call grouped is the events in order again.
    const groups = counts.calls > 1
    const callView = grouped && groups
    // The search is the events' in order: By call keeps its own, whole.
    const query = callView ? null : findQueryOf(found)
    const words = query === null ? [] : [query]
    // The rows catch up with the search typed behind the field (`found`), which on a long transcript takes a while:
    // until they do, they are the last search's, dimmed, and the count says the next is still being searched.
    const next = callView ? null : findQueryOf(typed)
    const searching = next !== query
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
    // The budget is read here, where a test can set its own (`TRANSCRIPT_BUDGET`).
    const drawn = callView
        ? drawnRows(callRows, rows, 0, TRANSCRIPT_BUDGET)
        : drawnRows(shown.length, rows, through, TRANSCRIPT_BUDGET)
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
        <RunWorktreesContext value={worktrees}>
            <Panel className={cn(transcript === undefined && 'min-h-40')} data-testid="transcript">
                <PanelHeader label="Transcript">
                    <span className="flex flex-wrap items-center gap-3">
                        {transcript?.session_id && (
                            <Copyable
                                text={transcript.session_id}
                                label="session id"
                                className="hidden readout text-xs text-muted-foreground @lg:inline-flex"
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
                                    onPressedChange={(on) =>
                                        setOpened((o) => ({ open: on, round: o.round + 1, query }))
                                    }
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
                                {transcript.unreadable > 0 && (
                                    <span>{transcript.unreadable} events could not be read</span>
                                )}
                            </p>
                            {!callView && (
                                <Find
                                    value={typed}
                                    onChange={setTyped}
                                    // Cleared, it says nothing, though the rows still hold the last search.
                                    lines={query === null || next === null ? null : lines}
                                    rows={shown.length}
                                    searching={searching && next !== null}
                                />
                            )}
                        </div>
                        <ContextChart
                            shape={shape}
                            onShow={show}
                            open={chartOpen}
                            onOpenChange={(open) => setContextChartOpen(page, open)}
                        />
                        <PanelScroll
                            label="transcript rows"
                            // Most of the window, so a page of rows scrolls under the header, its counts, and its
                            // search.
                            className={cn('max-h-[max(24rem,80dvh)] transition-opacity', searching && 'opacity-60')}
                            data-testid="transcript-scroll"
                        >
                            {callView ? (
                                <ol className="divide-y" data-testid="transcript-calls">
                                    {ordered('transcript', order, [
                                        ...calls.before.map((entry, i) => (
                                            <Entry
                                                key={`before-${i}`}
                                                entry={entry}
                                                start={startOf(entries)}
                                                open={false}
                                            />
                                        )),
                                        ...calls.calls.map((call) => (
                                            <CallRow
                                                key={`${call.n}-${opened.round}`}
                                                call={call}
                                                model={models.get(call.n) ?? null}
                                                step={shape.calls.find((c) => c.n === call.n)?.step ?? null}
                                                prompt={transcript.prompt}
                                                start={startOf(entries)}
                                                open={opened.open}
                                            />
                                        )),
                                    ]).slice(0, drawn)}
                                    {drawn < callRows && (
                                        <Fold
                                            label={moreLabel(callRows - drawn, 'calls', TRANSCRIPT_BUDGET)}
                                            onShow={more}
                                        />
                                    )}
                                </ol>
                            ) : shown.length === 0 ? (
                                <Empty>no line holds “{query}”</Empty>
                            ) : (
                                <ol data-testid="transcript-entries">
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
                                                models={models}
                                                prompt={transcript.prompt}
                                                shape={shape}
                                            />
                                        )
                                    })}
                                    {drawn < shown.length && (
                                        <Fold
                                            label={moreLabel(shown.length - drawn, 'rows', TRANSCRIPT_BUDGET)}
                                            onShow={more}
                                        />
                                    )}
                                </ol>
                            )}
                        </PanelScroll>
                    </>
                )}
            </Panel>
        </RunWorktreesContext>
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
            if (transcript.removed_after_days !== null) {
                const removed = removedAfter(transcript.removed_after_days)
                return { short: removed, reason: `${removed}: your [retention] keeps a log that long once it ends` }
            }
            return { short: 'log gone', reason: 'its log is gone, or is not a file canopy reads' }
        }
        case 'read': {
            return { short: 'no events', reason: 'the log holds none of the session’s events' }
        }
    }
}

/**
 * The transcript's search field: a magnifier, the field, how many lines and rows hold the query once there is one,
 * or `searching…` while the rows are still being searched for what was typed, so the last search's count never reads
 * as the answer to this one, and a clear button. Escape empties it.
 */
function Find({
    value,
    onChange,
    lines,
    rows,
    searching,
}: {
    value: string
    onChange: (value: string) => void
    lines: number | null
    rows: number
    searching: boolean
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
                    // A live region from the first render, so a screen reader hears the count, and that the next is
                    // being searched, as they change; `contents`, so it takes no gap in the field while empty.
                    <output className="contents">
                        {(searching || lines !== null) && (
                            <span
                                className="shrink-0 readout text-xs text-muted-foreground"
                                data-testid="transcript-found"
                            >
                                {searching || lines === null ? 'searching…' : foundCount(lines, rows)}
                            </span>
                        )}
                    </output>
                }
            />
        </search>
    )
}

/** How many lines and rows hold a search: `5 lines, 2 rows`. */
function foundCount(lines: number, rows: number): string {
    return `${lines} ${lines === 1 ? 'line' : 'lines'}, ${rows} ${rows === 1 ? 'row' : 'rows'}`
}

/**
 * One event's row. In order, `calls` and `prompt` are the session's, so a model call's line opens to what that call
 * was sent and what it did, and `models` the model each call's line names; inside a call, which holds no model
 * call's line, they are left out.
 */
function Entry({
    entry,
    start,
    open,
    words = NO_WORDS,
    targeted = false,
    calls = NO_CALLS,
    models = NO_MODELS,
    prompt = null,
    shape = null,
}: {
    entry: TranscriptEntry
    start: string | null
    open: boolean
    words?: readonly string[]
    targeted?: boolean
    calls?: readonly Call[]
    models?: ReadonlyMap<number, string>
    prompt?: TranscriptPrompt | null
    shape?: ContextShape | null
}) {
    switch (entry.kind) {
        case 'text': {
            return (
                <Row at={entry.at} start={start} targeted={targeted} mark={entry.reasoning ? 'thinking' : 'said'}>
                    {entry.reasoning ? (
                        <Thinking text={entry.text} open={open} words={words} />
                    ) : (
                        <Said text={entry.text} words={words} />
                    )}
                    {entry.cut && <Chip>cut</Chip>}
                </Row>
            )
        }
        case 'tool': {
            return <Tool entry={entry} start={start} open={open} words={words} targeted={targeted} />
        }
        case 'step': {
            const call = calls.find((c) => c.n === entry.call) ?? null
            const model = entry.call === null ? null : (models.get(entry.call) ?? null)
            const context = shape?.calls.find((c) => c.n === entry.call) ?? null
            // One call's bar says nothing its tokens do not, as one bar of the chart does not.
            const metered = (shape?.calls.filter((c) => c.sent !== null).length ?? 0) > 1
            return (
                <ModelCall
                    entry={entry}
                    start={start}
                    call={call}
                    model={model}
                    prompt={prompt}
                    context={context}
                    peak={metered ? (shape?.peak?.sent ?? null) : null}
                />
            )
        }
        case 'error': {
            return (
                <Row
                    at={entry.at}
                    start={start}
                    targeted={targeted}
                    mark="error"
                    className={cn(!targeted && 'bg-status-failed/8')}
                >
                    <span className="font-mono text-xs text-status-failed">
                        <MarkedText text={entry.name} words={words} />
                    </span>
                    <p className="min-w-0 flex-1 text-sm wrap-break-word whitespace-pre-wrap">
                        <MarkedText text={entry.message} words={words} />
                    </p>
                </Row>
            )
        }
    }
}

/**
 * What the agent said, its line breaks kept, held to a measure a paragraph reads at. Text that is JSON whole, as a
 * worker's final result is, is colored as a call's output is, every value as written.
 */
function Said({ text, words }: { text: string; words: readonly string[] }) {
    const tokens = tokenize(text)
    if (tokens.some((token) => token.kind !== 'text')) {
        return (
            <p className="min-w-0 flex-1 font-mono text-xs/5 wrap-break-word whitespace-pre-wrap">
                <JsonTokens tokens={markedTokens(tokens, words)} />
            </p>
        )
    }
    return (
        <p className="min-w-0 flex-1 text-sm wrap-break-word whitespace-pre-wrap">
            <span className="block max-w-[96ch]">
                <MarkedText text={text} words={words} />
            </span>
        </p>
    )
}

/**
 * The agent's reasoning, muted and italic under its `thinking` label. Past `THINKING_LINES` it shows its first lines
 * and a toggle for the rest (`foldText`), whole from the start when the row is opened (All open, or shown from the
 * chart) or the search holds a line the fold would hide. The toggle, once clicked, wins over both.
 */
function Thinking({ text, open, words }: { text: string; open: boolean; words: readonly string[] }) {
    const [toggled, setToggled] = useState<boolean | null>(null)
    // A model's thinking often ends on a blank line, and a fold can too; pre-wrap would show it as an empty line.
    const said = text.trimEnd()
    const fold = foldText(said, THINKING_LINES)
    const shown = fold.shown.trimEnd()
    const whole = toggled ?? (open || matches(said, words) > matches(shown, words))
    return (
        <div className="flex min-w-0 flex-1 flex-col gap-1.5 text-muted-foreground italic">
            <p className="max-w-[96ch] text-sm wrap-break-word whitespace-pre-wrap">
                <span className="mr-2 panel-label not-italic">thinking</span>
                <MarkedText text={whole ? said : shown} words={words} />
            </p>
            {fold.hidden > 0 && <MoreLines hidden={fold.hidden} open={whole} onToggle={() => setToggled(!whole)} />}
        </div>
    )
}

// How many matches of `words` `text` holds.
function matches(text: string, words: readonly string[]): number {
    return marked(text, words).filter((piece) => piece.mark).length
}

/**
 * An entry's line: when it was printed, from the session's first event, its `mark` on the thread, then the entry. The
 * one last shown, by the context chart or the Run panel's `ended on`, sits on the accent's tint, scrolled to and
 * focused.
 */
function Row({
    at,
    start,
    targeted = false,
    mark,
    className,
    children,
}: {
    at: string | null
    start: string | null
    targeted?: boolean
    mark: 'said' | 'thinking' | 'error'
    className?: string
    children: ReactNode
}) {
    return (
        <li
            ref={targeted ? reveal : undefined}
            tabIndex={targeted ? -1 : undefined}
            className={cn(
                'group/row flex items-baseline gap-3 px-3 py-2 outline-none',
                targeted && 'bg-accent/14',
                className,
            )}
        >
            <When at={at} start={start} />
            <Thread from="first line" className="-my-2">
                {mark === 'error' ? (
                    <RunDot state="failed" />
                ) : (
                    <span className="flex size-2 items-center justify-center">
                        <span
                            className={cn(
                                'rounded-full',
                                mark === 'said' ? 'size-2 border border-foreground/70' : 'size-1 bg-muted-foreground',
                            )}
                        />
                    </span>
                )}
            </Thread>
            {children}
        </li>
    )
}

/**
 * The thread the rows hang on: a hairline down the mark's column, from the row above to the row below, broken around
 * the row's own mark, so a session reads as one line of events. The mark sits beside the row's first line of text,
 * or at its middle; the thread starts at the first row's mark and ends at the last's. `className` takes back the
 * row's own padding, so the hairline meets the next row's.
 */
function Thread({
    from = 'middle',
    className,
    children,
}: {
    from?: 'first line' | 'middle'
    className?: string
    children: ReactNode
}) {
    return (
        <span aria-hidden className={cn('flex w-2 shrink-0 flex-col items-center gap-1 self-stretch', className)}>
            <span className={cn('w-px bg-border group-first/row:invisible', from === 'middle' ? 'flex-1' : 'h-2.5')} />
            {children}
            <span className="w-px flex-1 bg-border group-last/row:invisible" />
        </span>
    )
}

/** The thread under a row's line, beside what the row opens to: a cell of the mark's column in the body's grid. */
function ThreadOn({ className }: { className?: string }) {
    return (
        <span
            aria-hidden
            className={cn('col-[mark] w-px justify-self-center bg-border group-last/row:invisible', className)}
        />
    )
}

/** Scrolls the row last shown to the middle of the window, and gives it the focus. */
function reveal(element: HTMLElement | null) {
    element?.scrollIntoView({ block: 'center' })
    element?.focus({ preventScroll: true })
}

function When({ at, start }: { at: string | null; start: string | null }) {
    const clock = useClock()
    return (
        <span
            className="w-14 shrink-0 readout text-xs text-muted-foreground"
            title={at === null ? undefined : localTime(at, clock)}
        >
            {elapsed(at, start)}
        </span>
    )
}

/**
 * A tool call: one line, its name, what it did, and how it ended (refused, or what it printed when that is short),
 * that opens to its input and its output or error. A `decide` call opens to its decisions first, each on a line of
 * its own with its rationale, and a `ticket-set` call to its settings, each on a line of its own with what it sets, as
 * several recorded together are hard to read apart in their input.
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
    const worktrees = useRunWorktrees()
    const did = summary(entry, worktrees)
    const shell = shellCall(entry, worktrees)
    const decisions = decisionsOf(entry)
    const settings = decisions === null ? settingsOf(entry) : null
    const card = cardOf(entry)
    const result = card === null ? resultOf(entry) : null
    const heard = heardOf(entry)
    // Any other tool of canopy's own, whose line says what it is about and what it does in place of its input's values.
    const own = card === null && result === null && decisions === null && settings === null ? canopyCall(entry) : null
    const diff = diffLinesOf(entry)
    // A call of canopy's that says something in prose, where another's line is a command or its input's values.
    const prose = card !== null || result !== null
    // A call of canopy's that worked says its own line under its summary, in place of what the tool answers every
    // such call; one that failed says its error, as any call does.
    const said = failed ? null : ownLine(card, result, heard)
    // What canopy lays out of its own call is built only once opened, as a model call's body is.
    const [shown, setShown] = useState(open)
    return (
        <li data-testid="transcript-tool" className={cn('group/row', targeted && 'bg-accent/14')}>
            <details open={open} className="group/tool" onToggle={(e) => setShown(e.currentTarget.open)}>
                <summary
                    ref={targeted ? reveal : undefined}
                    className={cn(
                        'flex cursor-pointer list-none items-center gap-3 px-3 py-2 hover:bg-surface-raised',
                        '[&::-webkit-details-marker]:hidden',
                    )}
                >
                    <When at={entry.at} start={start} />
                    <Thread className="-my-2">
                        <RunDot state={failed ? 'failed' : 'done'} />
                    </Thread>
                    {/* The name takes its own width up to 14rem and gives way first; the command takes the rest. */}
                    <span className="flex max-w-56 min-w-0 items-center gap-1.5" title={entry.tool}>
                        <ToolIcon kind={toolKind(entry)} />
                        <span className="truncate font-mono text-xs font-medium">
                            <MarkedText text={entry.tool} words={words} />
                        </span>
                    </span>
                    {result !== null && <Chip tone={RESULT_TONE[result.status] ?? 'plain'} word={result.status} />}
                    {own !== null && own.action !== null && <Chip tone={own.tone} word={own.action} />}
                    <span className="flex min-w-40 flex-1 flex-col">
                        {/* A shell call's title is what the agent said it was for: the command is what it did. Its
                            hover is the line whole, as the call named its directory, then that title. */}
                        <span
                            className={cn('truncate text-xs', !prose && own === null && 'font-mono')}
                            title={summaryTitle(entry)}
                        >
                            {own !== null && <CanopyLine call={own} words={words} />}
                            {own === null && shell !== null && <ShellLine call={shell} words={words} />}
                            {own === null && shell === null && <MarkedText text={did} words={words} />}
                        </span>
                        {line !== null && said === null && (
                            <span
                                className={cn('truncate text-xs text-muted-foreground', failed && 'text-status-failed')}
                                title={line}
                            >
                                <MarkedText text={line} words={words} />
                            </span>
                        )}
                        {said === 'card' && card !== null && <CardLine call={card} words={words} />}
                        {said === 'heard' && heard !== null && (
                            <span className="truncate text-xs text-muted-foreground">{heard}</span>
                        )}
                        {line === null && own !== null && own.told !== null && (
                            <span className="truncate text-xs text-muted-foreground" title={own.told}>
                                {own.told}
                            </span>
                        )}
                    </span>
                    {verdict === 'refused' && (
                        <Chip tone="failed" className="min-w-0 shrink" word={`refused:${guard ?? ''}`} />
                    )}
                    {entry.cut && <Chip>cut</Chip>}
                    <span className="w-14 shrink-0 text-right readout text-xs text-muted-foreground">
                        {entry.duration_ms === null ? '' : duration(entry.duration_ms)}
                    </span>
                    <ChevronRight
                        className={cn(
                            'size-3 shrink-0 text-muted-foreground',
                            'transition-transform group-open/tool:rotate-90',
                        )}
                    />
                </summary>
                <RowGrid kind="transcript" alone>
                    <ThreadOn />
                    <RowLine from="text" className="flex flex-col gap-2 pt-1 pb-3">
                        {shown && card !== null && <Posted call={card} />}
                        {shown && result !== null && <Reported result={result} />}
                        {shown && own !== null && <CanopyBody entry={entry} call={own} />}
                        {decisions !== null && <Decisions decisions={decisions} words={words} />}
                        {settings !== null && <Settings settings={settings} words={words} />}
                        <Block label="input" words={words}>
                            {entry.input}
                        </Block>
                        {diff === null ? (
                            <Block label={entry.status === 'error' ? 'error' : 'output'} failed={failed} words={words}>
                                {shownOutput(entry)}
                            </Block>
                        ) : (
                            <DiffBlock lines={diff} words={words} />
                        )}
                    </RowLine>
                </RowGrid>
            </details>
        </li>
    )
}

/**
 * Which line of canopy's own a call says under its summary: its card's, what it heard, nothing for a result, whose
 * summary and status are its line; null for any other call, which says how it ended.
 */
function ownLine(
    card: CallCard | null,
    result: CallResult | null,
    heard: string | null,
): 'card' | 'result' | 'heard' | null {
    if (card !== null) {
        return 'card'
    }
    if (result !== null) {
        return 'result'
    }
    return heard === null ? null : 'heard'
}

/** A result's status as its chip's tone: what waits on the operator, what failed, and plain for the rest. */
const RESULT_TONE: Partial<Record<string, 'blocked' | 'failed'>> = { blocked: 'blocked', failed: 'failed' }

/** Under a progress update's summary: what the agent said it was doing, and how many of its steps were done. */
function CardLine({ call, words }: { call: CallCard; words: readonly string[] }) {
    const counted = call.card.steps.filter((step) => step.status !== 'skipped')
    const done = counted.filter((step) => step.status === 'done').length
    return (
        <span className="truncate text-xs text-muted-foreground" title={call.card.now}>
            now{' '}
            <span className="text-foreground">
                <MarkedText text={call.card.now} words={words} />
            </span>
            {counted.length > 0 && (
                <span>
                    {' '}
                    ·{' '}
                    <span className="readout">
                        {done}/{counted.length}
                    </span>{' '}
                    steps done
                </span>
            )}
            {call.question !== null && <span className="text-status-blocked"> · asks the operator</span>}
        </span>
    )
}

/**
 * A progress update as the operator read it: the run's card as it stood at that call (`RunProgress`), then the
 * question it asked, each option by its letter, the one the agent recommends marked. It is the record of one call, so
 * it answers nothing: the run's page has the card as it stands.
 */
function Posted({ call }: { call: CallCard }) {
    const question = call.question
    return (
        <div className="flex flex-col gap-1" data-testid="transcript-card">
            <span className="panel-label">progress posted</span>
            <div className="flex flex-col gap-3 rounded-sm border bg-background p-3">
                <RunProgress card={call.card} running={false} freshness={false} />
                {question !== null && (
                    <div className="flex max-w-3xl flex-col gap-2">
                        <p className="text-xs text-status-blocked">asks the operator</p>
                        <p className="text-sm font-medium text-pretty">
                            <LinkedText text={question.ask} />
                        </p>
                        <ol className="flex flex-col gap-1">
                            {/* A question's options never reorder. */}
                            {question.options.map((option, i) => (
                                <li key={i} className="flex gap-2 text-sm">
                                    <LetteredOption
                                        letter={LETTERS[i] ?? '?'}
                                        chosen={false}
                                        recommended={LETTERS[i] === question.recommend}
                                    >
                                        <LinkedText text={option} />
                                    </LetteredOption>
                                </li>
                            ))}
                        </ol>
                    </div>
                )}
            </div>
        </div>
    )
}

/**
 * A run's result as it reported it: its summary laid out as the agent wrote it, what it asks the operator, and each
 * repository's PR. Its status is on the call's line; the rest of what it reports is in its input.
 */
function Reported({ result }: { result: CallResult }) {
    return (
        <div className="flex flex-col gap-1" data-testid="transcript-result">
            <span className="panel-label">result reported</span>
            <div className="flex flex-col gap-3 rounded-sm border bg-background p-3">
                {result.summary === '' ? (
                    <p className="text-xs text-muted-foreground">no summary</p>
                ) : (
                    <RichText text={result.summary} pullRequests className="max-w-[96ch]" />
                )}
                {result.question !== null && (
                    <div className="flex flex-col gap-1">
                        <p className="text-xs text-status-blocked">asks the operator</p>
                        <RichText text={result.question} className="max-w-[96ch]" />
                    </div>
                )}
                {result.prs.length > 0 && (
                    <ul className="flex flex-col gap-1 text-xs">
                        {result.prs.map(([repo, url]) => (
                            <li key={repo} className="flex items-baseline gap-2">
                                <span className="shrink-0 font-mono">{repo}</span>
                                {url === null ? (
                                    <span className="text-muted-foreground">no PR</span>
                                ) : (
                                    <span className="min-w-0 wrap-break-word">
                                        <LinkedText text={url} pullRequests />
                                    </span>
                                )}
                            </li>
                        ))}
                    </ul>
                )}
            </div>
        </div>
    )
}

/** What a kind of tool call does, as the small icon before its name. */
const TOOL_ICONS: Record<ToolKind, LucideIcon> = {
    shell: SquareTerminal,
    write: FilePen,
    read: FileText,
    search: Search,
    web: Globe,
    canopy: Sprout,
    other: Wrench,
}

/** A tool call's kind (`toolKind`), as an icon before its name: decoration, since the name says it. */
function ToolIcon({ kind }: { kind: ToolKind }) {
    const Icon = TOOL_ICONS[kind]
    // The narrowest panel, a window under the rail's step, keeps the room for the command, which its line holds at
    // 300px there: the icon shows from just past that width, under any the whole rail leaves.
    return <Icon aria-hidden className="hidden size-3.5 shrink-0 text-muted-foreground @[45rem]:block" />
}

/**
 * A model call's end: one muted line, its number, the `model` that made it where the line names one, its reason,
 * its tokens in and out as By call says them, and its cost, that opens to its tokens by kind and then to what the
 * call was sent and what it did, as By call shows them. The body is built only once opened, as By call's is: a long
 * session's calls would hold every output twice.
 */
function ModelCall({
    entry,
    start,
    call,
    model,
    prompt,
    context,
    peak,
}: {
    entry: TranscriptStep
    start: string | null
    call: Call | null
    model: string | null
    prompt: TranscriptPrompt | null
    context: CallContext | null
    peak: number | null
}) {
    const [open, setOpen] = useState(false)
    const line = (
        <>
            <When at={entry.at} start={start} />
            <Thread className="-my-1.5">
                <span className="flex size-2 items-center justify-center">
                    <span className="size-1.5 rotate-45 border border-muted-foreground" />
                </span>
            </Thread>
            <span>model call{entry.call === null ? '' : ` ${entry.call}`}</span>
            <CallModel model={model} />
            {/* Every call but the last ends in tool calls: only another reason says something. */}
            {entry.reason && entry.reason !== 'tool-calls' && <Chip word={entry.reason} />}
            <span className="ml-auto" />
            <ContextMeter context={context} peak={peak} />
            <span className="readout">
                {entry.split === null
                    ? ''
                    : `${tokenCount(sentTokens(entry.split))} in · ${tokenCount(wroteTokens(entry.split))} out`}
            </span>
            <Cost usd={entry.cost_usd} className="w-14 shrink-0 text-right" />
        </>
    )
    // A turn's end sits in a groove of the canvas's color, so the rows between two read as one turn.
    const muted = 'flex items-center gap-3 bg-background/60 px-3 py-1.5 font-mono text-xs text-muted-foreground'
    const split = entry.split
    if (split === null && call === null) {
        return (
            <li className={cn('group/row', muted)}>
                {line}
                <span className="size-3 shrink-0" />
            </li>
        )
    }
    return (
        <li data-testid="transcript-step" className="group/row">
            <details className="group/step" onToggle={(e) => setOpen(e.currentTarget.open)}>
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
                            'transition-transform group-open/step:rotate-90',
                        )}
                    />
                </summary>
                {open && split !== null && (
                    <RowGrid kind="transcript" alone>
                        <ThreadOn />
                        <dl
                            className={cn(rowLineFrom('text'), 'flex flex-wrap gap-x-6 gap-y-1 py-2 font-mono text-xs')}
                        >
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
                {open && call !== null && <CallBody call={call} prompt={prompt} start={start} split={split} thread />}
            </details>
        </li>
    )
}

/**
 * What a model call was sent beside the session's peak, on its line: a short bar in the context chart's fills, what
 * it carried and then what it added, so the context's growth reads down the transcript without the chart. Nothing
 * where the runtime counted no tokens.
 */
function ContextMeter({ context, peak }: { context: CallContext | null; peak: number | null }) {
    const sent = context?.sent ?? null
    if (context === null || sent === null || peak === null || peak <= 0) {
        return null
    }
    const share = (n: number) => `${Math.max(0, Math.min(100, (n / peak) * 100))}%`
    return (
        <span
            className="hidden h-1.5 w-20 shrink-0 overflow-hidden rounded-full bg-border/60 @lg:flex"
            title={`sent ${tokenCount(sent)}, ${Math.round((sent / peak) * 100)}% of the peak`}
            data-testid="transcript-context-meter"
        >
            <span className="bg-context-carried" style={{ width: share(context.carried) }} />
            <span className="bg-context-added" style={{ width: share(context.added) }} />
        </span>
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
 * A model call, by call: one line, its number, the `model` that made it where the line names one, what it did, and
 * its tokens in and out and its cost, that opens to its input and its output. The first call's input is the prompt
 * canopy kept; what is new in a later call's is what its tools returned to the call before it. Ahead of all of it the
 * runtime sends the agent's definition and its own system prompt and tools, which no file records. The body is built
 * only once opened: a long session's calls would hold every output twice.
 */
function CallRow({
    call,
    model,
    step,
    prompt,
    start,
    open,
}: {
    call: Call
    model: string | null
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
                    <CallModel model={model} />
                    <span className="min-w-0 flex-1 truncate text-xs text-muted-foreground" title={callLine(call)}>
                        {callLine(call)}
                    </span>
                    {end === null && <Chip word="unfinished" />}
                    {end?.reason && end.reason !== 'tool-calls' && <Chip word={end.reason} />}
                    <span
                        className="hidden shrink-0 readout text-xs text-muted-foreground @lg:inline"
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

/** The model that made a call, on its line where the transcript names it: whole on hover when cut. */
function CallModel({ model }: { model: string | null }) {
    if (model === null) {
        return null
    }
    return (
        <span className="max-w-56 min-w-0 shrink truncate font-mono text-xs text-foreground" title={`made by ${model}`}>
            {model}
        </span>
    )
}

function CallBody({
    call,
    prompt,
    start,
    split,
    thread = false,
}: {
    call: Call
    prompt: TranscriptPrompt | null
    start: string | null
    split: TranscriptTokens | null
    thread?: boolean
}) {
    return (
        // In a narrow panel the body takes the row's whole width; in a wider one it starts under the text.
        <RowGrid kind="transcript" alone data-testid="transcript-call-body">
            {thread && <ThreadOn className="@max-lg:hidden" />}
            <RowLine from="text" className="flex flex-col gap-3 pt-1 pb-3 @max-lg:col-[time/end]">
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
                        <ol className="overflow-hidden rounded-sm border">
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
    const worktrees = useRunWorktrees()
    const shell = shellCall(tool, worktrees)
    return (
        <div className="flex flex-col gap-1">
            <span className="flex min-w-0 items-baseline gap-2 font-mono text-xs">
                <RunDot state={failed ? 'failed' : 'done'} />
                <span className="shrink-0">{tool.tool}</span>
                <span className="truncate text-muted-foreground" title={summaryTitle(tool)}>
                    {shell === null ? summary(tool, worktrees) : <ShellLine call={shell} />}
                </span>
            </span>
            <Pre failed={failed}>{shownOutput(tool)}</Pre>
        </div>
    )
}

/**
 * A shell call's line: the directory it ran in, muted, then `$` and its command in the line's own color, so the eye
 * finds the command and the directory reads apart from it. A directory outside the run's worktrees is in
 * `status-blocked`, whole, so a call that wandered off stands out. Search marks hold in each part.
 */
function ShellLine({ call, words = NO_WORDS }: { call: ShellCall; words?: readonly string[] }) {
    return (
        <>
            {call.dir !== null && (
                <>
                    <span
                        className={call.outside ? 'text-status-blocked' : 'text-muted-foreground'}
                        data-testid="shell-dir"
                    >
                        <MarkedText text={call.dir} words={words} />
                    </span>
                    <span className="text-muted-foreground"> $ </span>
                </>
            )}
            <MarkedText text={call.command} words={words} />
        </>
    )
}

/** A `decide` call's decisions, in the order given: each its ticket, its action, and why. */
function Decisions({ decisions, words }: { decisions: readonly CallDecision[]; words: readonly string[] }) {
    return (
        <div className="flex flex-col gap-1">
            <span className="panel-label">{decisions.length === 1 ? 'decision' : `${decisions.length} decisions`}</span>
            <ol className="flex flex-col gap-1 rounded-sm border bg-background p-2 text-xs">
                {/* A call's decisions never reorder, and its keys may repeat in one the harness refused. */}
                {decisions.map((d, i) => (
                    <li key={i} className="flex flex-wrap items-baseline gap-x-2">
                        <span className="shrink-0 font-mono">
                            <MarkedText text={d.key ?? THIS_TICK} words={words} />
                        </span>
                        <span className="shrink-0 font-mono text-muted-foreground">
                            <MarkedText text={d.action} words={words} />
                        </span>
                        <span className="min-w-0 flex-1 wrap-break-word">
                            <MarkedText text={d.rationale} words={words} />
                        </span>
                    </li>
                ))}
            </ol>
        </div>
    )
}

/**
 * A `ticket-set` call's settings, in the order given: each its ticket, or unit, then what it sets: its phase, `done`,
 * each cursor with the newest item it passes, and the title.
 */
function Settings({ settings, words }: { settings: readonly CallSetting[]; words: readonly string[] }) {
    return (
        <div className="flex flex-col gap-1">
            <span className="panel-label">{settings.length === 1 ? 'setting' : `${settings.length} settings`}</span>
            <ol className="flex flex-col gap-1 rounded-sm border bg-background p-2 text-xs">
                {/* A call's settings never reorder, and its keys may repeat in one the harness refused. */}
                {settings.map((s, i) => (
                    <li key={i} className="flex flex-wrap items-baseline gap-x-2">
                        <span className="shrink-0 font-mono">
                            <MarkedText text={settingSubject(s)} words={words} />
                        </span>
                        {s.phase !== null && (
                            <span className="shrink-0 font-mono text-muted-foreground">
                                <MarkedText text={s.phase} words={words} />
                            </span>
                        )}
                        {s.done && <span className="shrink-0 font-mono text-muted-foreground">done</span>}
                        {s.cursors.map(([name, value]) => (
                            <span key={name} className="shrink-0 font-mono text-muted-foreground">
                                <MarkedText text={`${name} ${value}`} words={words} />
                            </span>
                        ))}
                        {s.title !== null && (
                            <span className="min-w-0 flex-1 wrap-break-word">
                                <MarkedText text={s.title} words={words} />
                            </span>
                        )}
                    </li>
                ))}
            </ol>
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
                'font-mono text-xs wrap-break-word whitespace-pre-wrap',
                failed && 'border-status-failed/40',
            )}
        >
            <JsonTokens tokens={markedTokens(tokenize(children), words)} />
        </pre>
    )
}
