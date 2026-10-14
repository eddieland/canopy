import type { ReactNode } from 'react'

import type { RunState } from '@/api/types'
import { RUN_DOT } from '@/lib/run-state'
import { cn } from '@/lib/utils'
import { readable } from '@/lib/words'

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
 * spaces for underscores, and keeps its spelling, the one the CLI prints, on hover. A chip given room to shrink
 * (`min-w-0 shrink`) cuts its word to fit.
 */
export function Chip({ className, word, children }: { className?: string; word?: string; children?: ReactNode }) {
    const text = word === undefined ? undefined : readable(word)
    return (
        <span
            title={word !== undefined && word !== text ? word : undefined}
            className={cn(
                'inline-flex h-5 shrink-0 items-center gap-1 rounded-sm border px-1.5 font-mono text-2xs',
                'text-muted-foreground',
                className,
            )}
        >
            {text === undefined ? children : <span className="truncate">{text}</span>}
        </span>
    )
}

/**
 * A word from the journal in running text, not a chip: a phase, a status. It reads as words, as a chip's does
 * (`ci_failing` reads `ci failing`), with the CLI's spelling on hover. `text` stands in for a word already made
 * readable, such as a phase with what qualifies it.
 */
export function Word({ word, text, className }: { word: string; text?: string; className?: string }) {
    const shown = text ?? readable(word)
    return (
        <span title={word === shown ? undefined : word} className={className}>
            {shown}
        </span>
    )
}
