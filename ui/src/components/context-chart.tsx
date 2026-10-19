import { useState } from 'react'

import { ToggleGroup, ToggleGroupItem } from '@/components/ui/toggle-group'
import { axisNames, axisStep } from '@/lib/chart'
import { signed, summary, tokenCount } from '@/lib/transcript'
import type { Addition, CallContext, ContextShape } from '@/lib/transcript'
import { cn } from '@/lib/utils'

// How many of a step's additions it lists, before a line for the rest.
const MAX_ADDITIONS = 5
// Above this many calls, the axis names every fifth, back from the last, as the spend chart's does over 30 days.
const AXIS_ALL = 12
// The chart's top is the peak and this much over it, the room the peak's label sits in.
const HEADROOM = 1.25

/**
 * A transcript's context by model call (ui/DESIGN.md): its peak and its largest single addition on one line, then a
 * bar per call, as tall as what it was sent, the part it carried from the call before in a neutral and what it added
 * in a hue, the first call's split into the runtime's own overhead and canopy's prompt, and the peak's size over its
 * bar. Each bar is a segmented control's item: the one picked, at first the call the largest addition grew, names
 * under the chart what grew it, largest first, each a button that shows its row in the transcript (`onShow`, by its
 * place in the entries). A session of one call has its line alone, with no bars.
 */
export function ContextChart({ shape, onShow }: { shape: ContextShape; onShow: (i: number) => void }) {
    const [picked, setPicked] = useState<number | null>(null)
    const { calls, peak, largest } = shape
    const top = (peak?.sent ?? 0) * HEADROOM
    const shown = calls.find((c) => c.n === picked) ?? largest?.call ?? peak ?? calls[0]
    // One call's bar says nothing its line does not.
    const chart = calls.length > 1
    if (peak === null || shown === undefined) {
        return null
    }
    return (
        <section
            aria-label="Context by model call"
            className="flex flex-col gap-2 border-b px-3 py-2"
            data-testid="transcript-context"
        >
            <div className="flex flex-wrap items-baseline gap-x-4 gap-y-1 text-xs text-muted-foreground">
                <span className="panel-label">context</span>
                <span className="readout" title={`${peak.sent} tokens`}>
                    peak {tokenCount(peak.sent ?? 0)} at call {peak.n}
                </span>
                {largest !== null && (
                    <span className="flex min-w-0 items-baseline gap-2" data-testid="context-largest">
                        <span className="shrink-0">largest addition</span>
                        <ShowButton addition={largest.addition} onShow={onShow} />
                        <span className="readout shrink-0">
                            ≈{tokenCount(largest.addition.tokens)} into call {largest.call.n}
                        </span>
                    </span>
                )}
                {chart && (
                    <ul aria-hidden className="ml-auto flex gap-3">
                        <li className="flex items-center gap-1.5">
                            <span className="size-2.5 rounded-xs bg-context-carried" />
                            overhead, then carried
                        </li>
                        <li className="flex items-center gap-1.5">
                            <span className="size-2.5 rounded-xs bg-context-added" />
                            prompt, then added
                        </li>
                    </ul>
                )}
            </div>
            {chart && (
                <>
                    <ToggleGroup
                        type="single"
                        aria-label="Model calls"
                        value={String(shown.n)}
                        // The picked call stays picked: pressing it again would leave nothing to name.
                        onValueChange={(value) => {
                            if (value !== '') {
                                setPicked(Number(value))
                            }
                        }}
                        className={cn(
                            'flex h-20 w-full items-stretch gap-1',
                            'rounded-none border-0 border-b bg-transparent p-0',
                        )}
                    >
                        {calls.map((call) => (
                            <ToggleGroupItem
                                key={call.n}
                                value={String(call.n)}
                                aria-label={callLabel(call)}
                                title={callLabel(call)}
                                className={cn(
                                    'relative flex h-full max-w-6 min-w-px flex-1 flex-col justify-end',
                                    'rounded-t-xs p-0 hover:bg-surface-raised',
                                )}
                                data-testid={`context-call-${call.n}`}
                            >
                                <Bar call={call} top={top} peak={call === peak} />
                            </ToggleGroupItem>
                        ))}
                    </ToggleGroup>
                    <div aria-hidden className="-mt-1 flex gap-1">
                        {calls.map((call, i) => (
                            <span
                                key={call.n}
                                className="readout max-w-6 min-w-px flex-1 text-center text-2xs text-muted-foreground"
                            >
                                {axisNames(i, calls.length, axisStep(calls.length, AXIS_ALL)) ? call.n : ''}
                            </span>
                        ))}
                    </div>
                </>
            )}
            <Grew call={shown} before={calls[calls.indexOf(shown) - 1]} shape={shape} onShow={onShow} />
        </section>
    )
}

/** A call's bar: what it carried on the baseline, what it added over that, and the peak's size over the peak's. */
function Bar({ call, top, peak }: { call: CallContext; top: number; peak: boolean }) {
    if (call.sent === null || top === 0) {
        return null
    }
    const height = (call.sent / top) * 100
    return (
        <>
            <span className="flex w-full shrink-0 flex-col-reverse gap-0.5" style={{ height: `${height}%` }}>
                {call.carried > 0 && (
                    <span
                        className="w-full last:rounded-t-xs bg-context-carried"
                        style={{ flexGrow: call.carried, flexBasis: 0 }}
                    />
                )}
                {call.added > 0 && (
                    <span
                        className="min-h-px w-full last:rounded-t-xs bg-context-added"
                        style={{ flexGrow: call.added, flexBasis: 0 }}
                    />
                )}
            </span>
            {peak && (
                <span
                    className="readout absolute inset-x-0 flex justify-center pb-0.5 text-2xs whitespace-nowrap"
                    style={{ bottom: `${height}%` }}
                >
                    {tokenCount(call.sent)}
                </span>
            )}
        </>
    )
}

function callLabel(call: CallContext): string {
    if (call.sent === null) {
        return `call ${call.n}: the runtime counted no tokens`
    }
    const step = call.step === null ? '' : `, ${signed(call.step)} on the call before`
    return `call ${call.n}: ${tokenCount(call.sent)} sent${step}`
}

/** What grew the picked call's context: the first call's prompt and overhead, or the entries of the call before. */
function Grew({
    call,
    before,
    shape,
    onShow,
}: {
    call: CallContext
    before: CallContext | undefined
    shape: ContextShape
    onShow: (i: number) => void
}) {
    const head = (
        <span className="readout text-foreground">
            call {call.n}
            {call.sent !== null && `, ${tokenCount(call.sent)} sent`}
        </span>
    )
    if (call.sent === null) {
        return <p className="text-xs text-muted-foreground">{head}: the runtime counted no tokens for it</p>
    }
    if (before === undefined) {
        const split = `≈${tokenCount(call.added)} canopy’s prompt, ≈${tokenCount(call.carried)} the runtime’s own`
        return (
            <p className="text-xs text-muted-foreground">
                {head}:{' '}
                {shape.prompt === null
                    ? 'canopy kept no prompt, so all of it reads as the runtime’s own'
                    : `${split}: the agent’s definition, its system prompt, and its tools`}
            </p>
        )
    }
    if (call.step === null) {
        return (
            <p className="text-xs text-muted-foreground">
                {head}: the runtime counted no tokens for call {before.n}, so nothing says what grew it
            </p>
        )
    }
    if (call.step <= 0) {
        return (
            <p className="text-xs text-muted-foreground">
                {head}, {signed(call.step)} on call {before.n}:{' '}
                {call.step === 0 ? 'nothing grew it' : 'the runtime dropped part of what it carried'}
            </p>
        )
    }
    const listed = call.additions.slice(0, MAX_ADDITIONS)
    const rest = call.additions.slice(MAX_ADDITIONS)
    return (
        <div className="flex flex-col gap-1 text-xs text-muted-foreground" data-testid="context-grew">
            <p>
                {head}, {signed(call.step)} on call {before.n}, from what call {before.n} printed, largest first:
            </p>
            <ol className="flex flex-col gap-0.5">
                {listed.map((addition) => (
                    <li key={addition.i} className="flex min-w-0 items-baseline gap-3">
                        <span
                            className="readout w-14 shrink-0 text-right"
                            title={`${addition.chars} characters: its share of the step by them`}
                        >
                            ≈{tokenCount(addition.tokens)}
                        </span>
                        <ShowButton addition={addition} onShow={onShow} />
                    </li>
                ))}
                {rest.length > 0 && (
                    <li className="flex items-baseline gap-3">
                        <span className="readout w-14 shrink-0 text-right">
                            ≈{tokenCount(rest.reduce((sum, a) => sum + a.tokens, 0))}
                        </span>
                        <span>
                            {rest.length} more {rest.length === 1 ? 'entry' : 'entries'}
                        </span>
                    </li>
                )}
            </ol>
        </div>
    )
}

/** An addition named on one line, a button that shows its row in the transcript. */
function ShowButton({ addition, onShow }: { addition: Addition; onShow: (i: number) => void }) {
    const { entry } = addition
    const name = entry.kind === 'tool' ? entry.tool : entry.reasoning ? 'thinking' : 'text'
    const what = entry.kind === 'tool' ? summary(entry) : entry.text.replaceAll(/\s+/gu, ' ').trim()
    return (
        <button
            type="button"
            onClick={() => onShow(addition.i)}
            title="Show it in the transcript"
            className={cn(
                'flex min-w-0 items-baseline gap-2 rounded-sm text-left font-mono text-xs text-accent',
                'underline-offset-4 outline-none hover:underline focus-visible:ring-3 focus-visible:ring-ring/50',
            )}
        >
            <span className="shrink-0">{name}</span>
            {what !== '' && <span className="truncate">{what}</span>}
        </button>
    )
}
