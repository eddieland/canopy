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
 * spaces for underscores, and keeps its spelling, the one the CLI prints, on hover.
 */
export function Chip({ className, word, children }: { className?: string; word?: string; children?: ReactNode }) {
    const text = word === undefined ? undefined : readable(word)
    return (
        <span
            title={word !== undefined && word !== text ? word : undefined}
            className={cn(
                'inline-flex h-5 shrink-0 items-center gap-1 rounded-sm border px-1.5 font-mono text-[0.6875rem]',
                'text-muted-foreground',
                className,
            )}
        >
            {text ?? children}
        </span>
    )
}
