import { ChevronRight } from 'lucide-react'
import { useState, type ReactNode } from 'react'

import type { Transcript, TranscriptEntry, TranscriptTool } from '@/api/types'
import { Panel, PanelHeader, Placeholder } from '@/components/panel'
import { Chip, RunDot } from '@/components/status'
import { Button } from '@/components/ui/button'
import { Skeleton } from '@/components/ui/skeleton'
import { localTime } from '@/lib/time'
import { duration, elapsed, hint, startOf, tally, tokenCount } from '@/lib/transcript'
import { cn } from '@/lib/utils'

/**
 * A session's transcript (DESIGN §22): the agent's text, each tool call (its input and output open on a click),
 * each model call's cost, and the runtime's errors, in the order the runtime printed them. All of it is agent
 * output, rendered as text. `running` says the session's events have not reached the log yet: they do when its run
 * or tick ends.
 */
export function TranscriptPanel({ transcript, running }: { transcript: Transcript | undefined; running: boolean }) {
    // Bumped by Open all and Close all: each call remounts open or closed, then toggles on its own.
    const [opened, setOpened] = useState({ open: false, round: 0 })
    const entries = transcript?.entries ?? []
    const counts = tally(entries)
    const tools = entries.some((e) => e.kind === 'tool')
    return (
        <Panel className="min-h-40" data-testid="transcript">
            <PanelHeader label="Transcript">
                <span className="flex items-center gap-3">
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
                    <ol className="divide-y" data-testid="transcript-entries">
                        {entries.map((entry, i) => (
                            <Entry
                                // An entry's place in its log is its identity: a log only ever grows at the end.
                                key={`${i}-${opened.round}`}
                                entry={entry}
                                start={startOf(entries)}
                                open={opened.open}
                            />
                        ))}
                    </ol>
                </>
            )}
        </Panel>
    )
}

function empty(transcript: Transcript, running: boolean): string {
    switch (transcript.status) {
        case 'no_session':
            return 'the runtime reported no session: a template without --format json prints no events'
        case 'no_log':
            return 'its log is gone, or is not a file canopy reads'
        case 'read':
            return running
                ? 'the session’s events reach the log when it ends'
                : 'the log holds none of the session’s events'
    }
}

function Entry({ entry, start, open }: { entry: TranscriptEntry; start: string | null; open: boolean }) {
    switch (entry.kind) {
        case 'text':
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
        case 'tool':
            return <Tool entry={entry} start={start} open={open} />
        case 'step':
            return (
                <Row at={entry.at} start={start} className="py-1.5 font-mono text-xs text-muted-foreground">
                    <span>model call</span>
                    {entry.reason && <Chip word={entry.reason} />}
                    <span className="readout ml-auto">
                        {entry.tokens === null ? '' : `${tokenCount(entry.tokens)} tokens`}
                    </span>
                    <span className="readout w-14 text-right">
                        {entry.cost_usd === null ? '' : `$${entry.cost_usd.toFixed(2)}`}
                    </span>
                </Row>
            )
        case 'error':
            return (
                <Row at={entry.at} start={start} className="bg-status-failed/8">
                    <span className="font-mono text-xs text-status-failed">{entry.name}</span>
                    <p className="min-w-0 flex-1 text-sm break-words whitespace-pre-wrap">{entry.message}</p>
                </Row>
            )
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

/** A tool call: one line, its name and what it was about, that opens to its input and its output or error. */
function Tool({ entry, start, open }: { entry: TranscriptTool; start: string | null; open: boolean }) {
    const failed = entry.status === 'error'
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
                    <span className="w-44 shrink-0 truncate font-mono text-xs" title={entry.tool}>
                        {entry.tool}
                    </span>
                    <span className="min-w-0 flex-1 truncate text-sm text-muted-foreground">
                        {entry.title ?? hint(entry.input)}
                    </span>
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
                    <Block label={failed ? 'error' : 'output'} failed={failed}>
                        {entry.output || 'no output'}
                    </Block>
                </div>
            </details>
        </li>
    )
}

function Block({ label, failed = false, children }: { label: string; failed?: boolean; children: string }) {
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
                {children}
            </pre>
        </div>
    )
}
