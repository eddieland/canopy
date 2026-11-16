import type { ReactNode } from 'react'

import type { RunState } from '@/api/types'
import { Tip } from '@/components/tip'
import { useCut } from '@/hooks/use-cut'
import { RUN_DOT } from '@/lib/run-state'
import type { ProposalTone, Tone } from '@/lib/tone'
import { cn } from '@/lib/utils'
import { readable } from '@/lib/words'

// Every chip's color, the one map of them (ui/DESIGN.md, "Chips"): its color's hairline at 40% (`--chip-line`) over
// the same color at 10% (a plain one's, `bg-chip-plain`, a palette's paper where it prints on one), so it holds its
// edge on a selected row's tint too. Plain is muted-foreground's, and so is a `leave` proposal's, which does nothing.
// Written out so Tailwind finds them. A palette that inks its chips (`shadow-chip`) draws its ink in place of the
// hairline, which it clears, so a chip is never two lines one inside the other.
const PLAIN = 'border-muted-foreground/(--chip-line) bg-chip-plain text-muted-foreground'
const TONE: Record<Tone | ProposalTone, string> = {
    plain: PLAIN,
    failed: 'border-status-failed/(--chip-line) bg-status-failed/10 text-status-failed',
    blocked: 'border-status-blocked/(--chip-line) bg-status-blocked/10 text-status-blocked',
    running: 'border-status-running/(--chip-line) bg-status-running/10 text-status-running',
    change: 'border-proposal-change/(--chip-line) bg-proposal-change/10 text-proposal-change',
    decline: 'border-proposal-decline/(--chip-line) bg-proposal-decline/10 text-proposal-decline',
    ask: 'border-proposal-ask/(--chip-line) bg-proposal-ask/10 text-proposal-ask',
    leave: PLAIN,
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
 * status color of the state it marks, or a feedback plan's proposal's own hue. A chip given room to shrink
 * (`min-w-0 shrink`) cuts its word to fit, and its tip then holds the word whole. `meaning` says in the tip, under the
 * word, what it means (`src/lib/meanings.ts`), and makes the tip open whatever the word.
 */
export function Chip({
    className,
    tone = 'plain',
    word,
    meaning,
    children,
}: {
    className?: string
    tone?: Tone | ProposalTone
    word?: string
    meaning?: string | null
    children?: ReactNode
}) {
    const [cutRef, cut] = useCut()
    const text = word === undefined ? undefined : readable(word)
    const fact = word !== undefined && (word !== text || cut || Boolean(meaning)) ? word : null
    return (
        <Tip fact={fact} mono detail={meaning}>
            <span
                className={cn(
                    'inline-flex h-5 shrink-0 items-center gap-1 rounded-sm border px-1.5 font-mono text-2xs',
                    'chip-case shadow-chip',
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
 * readable, such as a phase with what qualifies it. `meaning`, as a chip's, says in the tip what the word means.
 */
export function Word({
    word,
    text,
    meaning,
    className,
}: {
    word: string
    text?: string
    meaning?: string | null
    className?: string
}) {
    const shown = text ?? readable(word)
    return (
        <Tip fact={word === shown && !meaning ? null : word} mono detail={meaning}>
            <span className={className}>{shown}</span>
        </Tip>
    )
}
