import { ChevronRight, Search, X } from 'lucide-react'
import { useDeferredValue, useState } from 'react'
import type { ReactNode } from 'react'

import type { Transcript, TranscriptEntry, TranscriptStep, TranscriptTool } from '@/api/types'
import { JsonTokens } from '@/components/json-text'
import { MarkedText } from '@/components/marked-text'
import { OrderToggle } from '@/components/order-toggle'
import { Panel, PanelHeader, Placeholder } from '@/components/panel'
import { Chip, RunDot } from '@/components/status'
import { Button } from '@/components/ui/button'
import { Skeleton } from '@/components/ui/skeleton'
import { ordered, useListOrder } from '@/lib/list-order'
import { tokenize } from '@/lib/json-lines'
import { markedTokens } from '@/lib/search'
import { localTime } from '@/lib/time'
import {
    duration,
    elapsed,
    findQueryOf,
    hitsIn,
    outcome,
    shownOutput,
    startOf,
    summary,
    tally,
    tokenCount,
} from '@/lib/transcript'
import { cn } from '@/lib/utils'

/**
 * A session's transcript (DESIGN §22): the agent's text, each tool call (what it did and how it ended on its line,
 * its input and output open on a click), each model call's cost, and the runtime's errors, in the order the runtime
 * printed them. All of it is agent output, rendered as text. A search keeps the rows with a line that holds it, its
 * matches marked, and opens a tool call whose input or output holds it. `running` says the session's events have not
 * reached the log yet: they do when its run or tick ends.
 */
export function TranscriptPanel({ transcript, running }: { transcript: Transcript | undefined; running: boolean }) {
    const [typed, setTyped] = useState('')
    // A long transcript is searched behind the field, so typing never waits on it.
    const query = findQueryOf(useDeferredValue(typed))
    // Bumped by Open all and Close all: each call remounts open or closed, then toggles on its own. It wins over the
    // search it was made under; a new search opens the calls it finds again.
    const [opened, setOpened] = useState<{ open: boolean; round: number; query: string | null }>({
        open: false,
        round: 0,
        query: null,
    })
    const words = query === null ? [] : [query]
    const entries = transcript?.entries ?? []
    const counts = tally(entries)
    const tools = entries.some((e) => e.kind === 'tool')
    const order = useListOrder('transcript')
    // Each entry with its place in the log, which is its identity: a log only ever grows at the end.
    const numbered = ordered(
        'transcript',
        order,
        entries.map((entry, i) => ({ entry, i, hits: query === null ? null : hitsIn(entry, query) })),
    )
    const shown = numbered.filter((n) => n.hits === null || n.hits.row + n.hits.body > 0)
    const lines = shown.reduce((sum, n) => sum + (n.hits === null ? 0 : n.hits.row + n.hits.body), 0)
    return (
        <Panel className="min-h-40" data-testid="transcript">
            <PanelHeader label="Transcript">
                <span className="flex items-center gap-3">
                    {entries.length > 1 && <OrderToggle list="transcript" />}
                    {transcript?.session_id && (
                        <span
                            className="readout hidden text-xs text-muted-foreground sm:inline"
                            title="open it with the runtime's tools too: opencode export <id>"
                        >
                            session {transcript.session_id}
                        </span>
                    )}
                    {tools && (
                        <span className="flex items-center">
                            {(['open', 'close'] as const).map((verb) => (
                                <Button
                                    key={verb}
                                    variant="ghost"
                                    size="xs"
                                    onClick={() =>
                                        setOpened((o) => ({ open: verb === 'open', round: o.round + 1, query }))
                                    }
                                >
                                    {verb === 'open' ? 'Open all' : 'Close all'}
                                </Button>
                            ))}
                        </span>
                    )}
                </span>
            </PanelHeader>
            {transcript === undefined ? (
                <div className="flex flex-col gap-2 p-3">
                    <Skeleton className="h-4 w-2/3" />
                    <Skeleton className="h-4 w-1/2" />
                </div>
            ) : entries.length === 0 ? (
                <Placeholder className="min-h-32">{empty(transcript, running)}</Placeholder>
            ) : (
                <>
                    <div className="flex flex-wrap items-center gap-x-4 gap-y-1.5 border-b px-3 py-1.5">
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
                        <Find
                            value={typed}
                            onChange={setTyped}
                            lines={query === null ? null : lines}
                            rows={shown.length}
                        />
                    </div>
                    {shown.length === 0 ? (
                        <Placeholder className="min-h-20">no line holds “{query}”</Placeholder>
                    ) : (
                        <ol className="divide-y" data-testid="transcript-entries">
                            {shown.map(({ entry, i, hits }) => {
                                // A search opens a call whose input or output holds it, until Open all or Close all is
                                // used under it; a row whose place changes remounts to it.
                                const inBody = hits !== null && hits.body > 0
                                const open = opened.open || (inBody && opened.query !== query)
                                return (
                                    <Entry
                                        key={`${i}-${opened.round}-${open}`}
                                        entry={entry}
                                        start={startOf(entries)}
                                        open={open}
                                        words={words}
                                    />
                                )
                            })}
                        </ol>
                    )}
                </>
            )}
        </Panel>
    )
}

function empty(transcript: Transcript, running: boolean): string {
    switch (transcript.status) {
        case 'no_session': {
            return 'the runtime reported no session: a template without --format json prints no events'
        }
        case 'no_log': {
            // A running tick knows its session before its output is written.
            return running
                ? 'the session’s events reach the log when it ends'
                : 'its log is gone, or is not a file canopy reads'
        }
        case 'read': {
            return running
                ? 'the session’s events reach the log when it ends'
                : 'the log holds none of the session’s events'
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
        <search
            className={cn(
                'ml-auto flex h-7 w-full items-center gap-2 rounded-md border bg-surface-raised px-2 sm:w-72',
                'focus-within:border-ring focus-within:ring-3 focus-within:ring-ring/50',
            )}
        >
            <Search aria-hidden className="size-3.5 shrink-0 text-muted-foreground" />
            <input
                type="search"
                aria-label="Find lines in the transcript"
                placeholder="Find lines"
                value={value}
                onChange={(event) => onChange(event.target.value)}
                onKeyDown={(event) => {
                    if (event.key === 'Escape') {
                        onChange('')
                    }
                }}
                className={cn(
                    'min-w-0 flex-1 bg-transparent text-xs text-foreground outline-none',
                    'placeholder:text-muted-foreground [&::-webkit-search-cancel-button]:hidden',
                )}
            />
            {lines !== null && (
                <span className="readout shrink-0 text-xs text-muted-foreground" data-testid="transcript-found">
                    {lines} {lines === 1 ? 'line' : 'lines'}, {rows} {rows === 1 ? 'row' : 'rows'}
                </span>
            )}
            {value !== '' && (
                <Button
                    type="button"
                    variant="ghost"
                    size="icon-xs"
                    aria-label="Clear the transcript's search"
                    onClick={() => onChange('')}
                    className="hover:bg-muted"
                >
                    <X aria-hidden />
                </Button>
            )}
        </search>
    )
}

function Entry({
    entry,
    start,
    open,
    words,
}: {
    entry: TranscriptEntry
    start: string | null
    open: boolean
    words: readonly string[]
}) {
    switch (entry.kind) {
        case 'text': {
            return (
                <Row at={entry.at} start={start}>
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
            return <Tool entry={entry} start={start} open={open} words={words} />
        }
        case 'step': {
            return <ModelCall entry={entry} start={start} />
        }
        case 'error': {
            return (
                <Row at={entry.at} start={start} className="bg-status-failed/8">
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

/** An entry's line: when it was printed, from the session's first event, then the entry. */
function Row({
    at,
    start,
    className,
    children,
}: {
    at: string | null
    start: string | null
    className?: string
    children: ReactNode
}) {
    return (
        <li className={cn('flex items-baseline gap-3 px-3 py-2', className)}>
            <When at={at} start={start} />
            {children}
        </li>
    )
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
}: {
    entry: TranscriptTool
    start: string | null
    open: boolean
    words: readonly string[]
}) {
    const { verdict, guard, line } = outcome(entry)
    const failed = verdict !== 'done'
    const did = summary(entry)
    return (
        <li data-testid="transcript-tool">
            <details open={open} className="group">
                <summary
                    className={cn(
                        'flex cursor-pointer list-none items-center gap-3 px-3 py-2 hover:bg-surface-raised',
                        '[&::-webkit-details-marker]:hidden',
                    )}
                >
                    <When at={entry.at} start={start} />
                    <RunDot state={failed ? 'failed' : 'done'} />
                    <span className="w-32 shrink-0 truncate font-mono text-xs sm:w-56" title={entry.tool}>
                        <MarkedText text={entry.tool} words={words} />
                    </span>
                    <span className="flex min-w-0 flex-1 flex-col">
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
                        <Chip className="border-status-failed/40 text-status-failed" word={`refused:${guard ?? ''}`} />
                    )}
                    {entry.cut && <Chip>cut</Chip>}
                    <span className="readout w-14 shrink-0 text-right text-xs text-muted-foreground">
                        {entry.duration_ms === null ? '' : duration(entry.duration_ms)}
                    </span>
                    <ChevronRight
                        className={cn(
                            'size-3.5 shrink-0 text-muted-foreground',
                            'transition-transform group-open:rotate-90',
                        )}
                    />
                </summary>
                <div className="flex flex-col gap-2 pr-3 pb-3 pl-[5.25rem]">
                    <Block label="input" words={words}>
                        {entry.input}
                    </Block>
                    <Block label={entry.status === 'error' ? 'error' : 'output'} failed={failed} words={words}>
                        {shownOutput(entry)}
                    </Block>
                </div>
            </details>
        </li>
    )
}

/**
 * A model call's end: one muted line, its reason, tokens, and cost, that opens to its tokens by kind. What it wrote and
 * ran are the rows above it; what it was sent, the runtime does not print.
 */
function ModelCall({ entry, start }: { entry: TranscriptStep; start: string | null }) {
    const line = (
        <>
            <When at={entry.at} start={start} />
            <span>model call</span>
            {/* Every call but the last ends in tool calls: only another reason says something. */}
            {entry.reason && entry.reason !== 'tool-calls' && <Chip word={entry.reason} />}
            <span className="readout ml-auto">{entry.tokens === null ? '' : `${tokenCount(entry.tokens)} tokens`}</span>
            <span className="readout w-14 shrink-0 text-right">
                {entry.cost_usd === null ? '' : `$${entry.cost_usd.toFixed(2)}`}
            </span>
        </>
    )
    const muted = 'flex items-center gap-3 px-3 py-1 font-mono text-xs text-muted-foreground'
    if (entry.split === null) {
        return (
            <li className={muted}>
                {line}
                <span className="size-3.5 shrink-0" />
            </li>
        )
    }
    const split = entry.split
    return (
        <li data-testid="transcript-step">
            <details className="group">
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
                            'size-3.5 shrink-0 text-muted-foreground',
                            'transition-transform group-open:rotate-90',
                        )}
                    />
                </summary>
                <dl className="flex flex-wrap gap-x-6 gap-y-1 pr-3 pb-2 pl-[5.25rem] font-mono text-xs">
                    {TOKEN_KINDS.map(([key, label]) => (
                        <div key={key} className="flex items-baseline gap-2">
                            <dt className="panel-label">{label}</dt>
                            <dd className="readout" title={`${split[key]} tokens`}>
                                {tokenCount(split[key])}
                            </dd>
                        </div>
                    ))}
                </dl>
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

function Block({
    label,
    failed = false,
    words,
    children,
}: {
    label: string
    failed?: boolean
    words: readonly string[]
    children: string
}) {
    return (
        <div className="flex flex-col gap-1">
            <span className={cn('panel-label', failed && 'text-status-failed')}>{label}</span>
            <pre
                className={cn(
                    'max-h-96 overflow-auto rounded-sm border bg-background p-2',
                    'font-mono text-xs break-words whitespace-pre-wrap',
                    failed && 'border-status-failed/40',
                )}
            >
                <JsonTokens tokens={markedTokens(tokenize(children), words)} />
            </pre>
        </div>
    )
}
