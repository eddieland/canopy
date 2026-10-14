import { ChevronRight, Rows3 } from 'lucide-react'
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
import { JsonTokens } from '@/components/json-text'
import { OrderToggle } from '@/components/order-toggle'
import { Panel, PanelHeader, Placeholder } from '@/components/panel'
import { Chip, RunDot } from '@/components/status'
import { Button } from '@/components/ui/button'
import { Skeleton } from '@/components/ui/skeleton'
import { ordered, useListOrder } from '@/lib/list-order'
import { tokenize } from '@/lib/json-lines'
import { localTime } from '@/lib/time'
import {
    byCall,
    callLine,
    duration,
    elapsed,
    outcome,
    pretty,
    sentTokens,
    startOf,
    summary,
    tally,
    tokenCount,
    wroteTokens,
} from '@/lib/transcript'
import type { ModelCall as Call } from '@/lib/transcript'
import { cn } from '@/lib/utils'

/**
 * A session's transcript (DESIGN §22): the agent's text, each tool call (what it did and how it ended on its line,
 * its input and output open on a click), each model call's cost, and the runtime's errors, in the order the runtime
 * printed them. By call, the same entries are grouped by the model call they came from, each opening to what it was
 * sent and what it did. All of it is agent output, rendered as text. `running` says the session's events have not
 * reached the log yet: they do when its run or tick ends.
 */
export function TranscriptPanel({ transcript, running }: { transcript: Transcript | undefined; running: boolean }) {
    // Bumped by Open all and Close all: each call remounts open or closed, then toggles on its own.
    const [opened, setOpened] = useState({ open: false, round: 0 })
    const [grouped, setGrouped] = useState(false)
    const entries = transcript?.entries ?? []
    const counts = tally(entries)
    const calls = byCall(entries)
    const callView = grouped && calls.calls.length > 0
    const tools = entries.some((e) => e.kind === 'tool')
    const order = useListOrder('transcript')
    // Each entry with its place in the log, which is its identity: a log only ever grows at the end.
    const numbered = ordered(
        'transcript',
        order,
        entries.map((entry, i) => ({ entry, i })),
    )
    return (
        <Panel className="min-h-40" data-testid="transcript">
            <PanelHeader label="Transcript">
                <span className="flex items-center gap-3">
                    {entries.length > 1 && <OrderToggle list="transcript" />}
                    {calls.calls.length > 0 && (
                        <Button
                            variant="ghost"
                            size="xs"
                            aria-pressed={grouped}
                            title={grouped ? 'Show each event in order' : 'Group the events by model call'}
                            className="aria-pressed:bg-surface-raised aria-pressed:text-foreground"
                            onClick={() => setGrouped((g) => !g)}
                        >
                            <Rows3 />
                            By call
                        </Button>
                    )}
                    {transcript?.session_id && (
                        <span
                            className="readout hidden text-xs text-muted-foreground sm:inline"
                            title="open it with the runtime's tools too: opencode export <id>"
                        >
                            session {transcript.session_id}
                        </span>
                    )}
                    {(tools || callView) && (
                        <span className="flex items-center">
                            {(['open', 'close'] as const).map((verb) => (
                                <Button
                                    key={verb}
                                    variant="ghost"
                                    size="xs"
                                    onClick={() => setOpened((o) => ({ open: verb === 'open', round: o.round + 1 }))}
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
                    <p className="flex flex-wrap gap-x-4 border-b px-3 py-1.5 font-mono text-xs text-muted-foreground">
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
                                        prompt={transcript.prompt}
                                        start={startOf(entries)}
                                        open={opened.open}
                                    />
                                )),
                            ])}
                        </ol>
                    ) : (
                        <ol className="divide-y" data-testid="transcript-entries">
                            {numbered.map(({ entry, i }) => (
                                <Entry
                                    key={`${i}-${opened.round}`}
                                    entry={entry}
                                    start={startOf(entries)}
                                    open={opened.open}
                                />
                            ))}
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

function Entry({ entry, start, open }: { entry: TranscriptEntry; start: string | null; open: boolean }) {
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
                        {entry.text}
                    </p>
                    {entry.cut && <Chip>cut</Chip>}
                </Row>
            )
        }
        case 'tool': {
            return <Tool entry={entry} start={start} open={open} />
        }
        case 'step': {
            return <ModelCall entry={entry} start={start} />
        }
        case 'error': {
            return (
                <Row at={entry.at} start={start} className="bg-status-failed/8">
                    <span className="font-mono text-xs text-status-failed">{entry.name}</span>
                    <p className="min-w-0 flex-1 text-sm break-words whitespace-pre-wrap">{entry.message}</p>
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
function Tool({ entry, start, open }: { entry: TranscriptTool; start: string | null; open: boolean }) {
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
                        {entry.tool}
                    </span>
                    <span className="flex min-w-0 flex-1 flex-col">
                        {/* A shell call's title is what the agent said it was for: the command is what it did. */}
                        <span className="truncate font-mono text-xs" title={entry.title ?? did}>
                            {did}
                        </span>
                        {line !== null && (
                            <span
                                className={cn('truncate text-xs text-muted-foreground', failed && 'text-status-failed')}
                                title={line}
                            >
                                {line}
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
                    <Block label="input">{entry.input}</Block>
                    <Block label={entry.status === 'error' ? 'error' : 'output'} failed={failed}>
                        {entry.output ? pretty(entry.output) : 'no output'}
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

/**
 * A model call, by call: one line, its number, what it did, and its tokens in and out and its cost, that opens to its
 * input and its output. The first call's input is the prompt canopy kept; what is new in a later call's is what its
 * tools returned to the call before it. Ahead of all of it the runtime sends the agent's definition and its own
 * system prompt and tools, which no file records. The body is built only once opened: a long session's calls would
 * hold every output twice.
 */
function CallRow({
    call,
    prompt,
    start,
    open,
}: {
    call: Call
    prompt: TranscriptPrompt | null
    start: string | null
    open: boolean
}) {
    const [shown, setShown] = useState(open)
    const end = call.end
    const split = end?.split ?? null
    const first = call.output[0]?.at ?? end?.at ?? null
    return (
        <li data-testid="transcript-call">
            <details open={open} className="group/call" onToggle={(e) => setShown(e.currentTarget.open)}>
                <summary
                    className={cn(
                        'flex cursor-pointer list-none items-center gap-3 px-3 py-2 hover:bg-surface-raised',
                        '[&::-webkit-details-marker]:hidden',
                    )}
                >
                    <When at={first} start={start} />
                    <span className="w-14 shrink-0 font-mono text-xs">call {call.n}</span>
                    <span className="min-w-0 flex-1 truncate text-xs text-muted-foreground" title={callLine(call)}>
                        {callLine(call)}
                    </span>
                    {end === null && <Chip word="unfinished" />}
                    {end?.reason && end.reason !== 'tool-calls' && <Chip word={end.reason} />}
                    <span className="readout hidden shrink-0 text-xs text-muted-foreground sm:inline">
                        {split === null
                            ? ''
                            : `${tokenCount(sentTokens(split))} in · ${tokenCount(wroteTokens(split))} out`}
                    </span>
                    <span className="readout w-14 shrink-0 text-right text-xs text-muted-foreground">
                        {end === null || end.cost_usd === null ? '' : `$${end.cost_usd.toFixed(2)}`}
                    </span>
                    <ChevronRight
                        className={cn(
                            'size-3.5 shrink-0 text-muted-foreground',
                            'transition-transform group-open/call:rotate-90',
                        )}
                    />
                </summary>
                {shown && <CallBody call={call} prompt={prompt} start={start} split={split} />}
            </details>
        </li>
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
        <div className="flex flex-col gap-3 pr-3 pb-3 pl-3 sm:pl-[5.25rem]" data-testid="transcript-call-body">
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
                        sent after the agent’s definition and the runtime’s own system prompt and tools, which no file
                        records
                    </p>
                )}
            </section>
            <section className="flex flex-col gap-2" aria-label={`call ${call.n} output`}>
                <Heading
                    label="output"
                    tokens={split === null ? null : wroteTokens(split)}
                    detail={split === null || split.reasoning === 0 ? null : `${tokenCount(split.reasoning)} reasoning`}
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
        </div>
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
            <Pre failed={failed}>{tool.output ? pretty(tool.output) : 'no output'}</Pre>
        </div>
    )
}

function Block({ label, failed = false, children }: { label: string; failed?: boolean; children: string }) {
    return (
        <div className="flex flex-col gap-1">
            <span className={cn('panel-label', failed && 'text-status-failed')}>{label}</span>
            <Pre failed={failed}>{children}</Pre>
        </div>
    )
}

function Pre({ failed = false, children }: { failed?: boolean; children: string }) {
    return (
        <pre
            className={cn(
                'max-h-96 overflow-auto rounded-sm border bg-background p-2',
                'font-mono text-xs break-words whitespace-pre-wrap',
                failed && 'border-status-failed/40',
            )}
        >
            <JsonTokens tokens={tokenize(children)} />
        </pre>
    )
}
