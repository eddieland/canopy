import type { ReactNode } from 'react'

import type { RunState } from '@/api/types'
import { Tip } from '@/components/tip'
import { useCut } from '@/hooks/use-cut'
import { RUN_DOT } from '@/lib/run-state'
import type { Tone } from '@/lib/tone'
import { cn } from '@/lib/utils'
import { readable } from '@/lib/words'

// Every chip's color, the one map of them (ui/DESIGN.md, "Chips"): its color's hairline at 40% over the same color at
// 10%, so it holds its edge on a selected row's tint too. Plain is muted-foreground's. Written out so Tailwind finds
// them.
const TONE: Record<Tone, string> = {
    plain: 'border-muted-foreground/40 bg-muted-foreground/10 text-muted-foreground',
    failed: 'border-status-failed/40 bg-status-failed/10 text-status-failed',
    blocked: 'border-status-blocked/40 bg-status-blocked/10 text-status-blocked',
    running: 'border-status-running/40 bg-status-running/10 text-status-running',
}

/** A small round marker in a run state's color. `running` pulses. */
export function RunDot({ state, className }: { state: RunState; className?: string }) {
    const tone = RUN_DOT[state]
    return (
        <span aria-hidden className={cn('relative inline-flex size-2 shrink-0', className)}>
            {state === 'running' && (
                <span
                    className={cn('absolute inset-0 animate-ping rounded-full opacity-40 motion-reduce:hidden', tone)}
                />
            )}
            <span className={cn('relative inline-flex size-2 rounded-full', tone)} />
        </span>
    )
}

/**
 * A small bordered label: a reason, a kind, private or public. Pass a word from the journal as `word`: it reads with
 * spaces for underscores, and keeps its spelling, the one the CLI prints, in a `Tip`. Its `tone` is plain, or the
 * status color of the state it marks. A chip given room to shrink (`min-w-0 shrink`) cuts its word to fit, and its
 * tip then holds the word whole.
 */
export function Chip({
    className,
    tone = 'plain',
    word,
    children,
}: {
    className?: string
    tone?: Tone
    word?: string
    children?: ReactNode
}) {
    const [cutRef, cut] = useCut()
    const text = word === undefined ? undefined : readable(word)
    const fact = word !== undefined && (word !== text || cut) ? word : null
    return (
        <Tip fact={fact} mono>
            <span
                className={cn(
                    'inline-flex h-5 shrink-0 items-center gap-1 rounded-sm border px-1.5 font-mono text-2xs',
                    TONE[tone],
                    className,
                )}
            >
                {text === undefined ? (
                    children
                ) : (
                    <span ref={cutRef} className="truncate">
                        {text}
                    </span>
                )}
            </span>
        </Tip>
    )
}

/**
 * A word from the journal in running text, not a chip: a phase, a status. It reads as words, as a chip's does
 * (`ci_failing` reads `ci failing`), with the CLI's spelling in a `Tip`. `text` stands in for a word already made
 * readable, such as a phase with what qualifies it.
 */
export function Word({ word, text, className }: { word: string; text?: string; className?: string }) {
    const shown = text ?? readable(word)
    return (
        <Tip fact={word === shown ? null : word} mono>
            <span className={className}>{shown}</span>
        </Tip>
    )
}
