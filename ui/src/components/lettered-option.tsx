import { Check } from 'lucide-react'
import type { ReactNode } from 'react'

import { cn } from '@/lib/utils'

/**
 * One of an agent's lettered options, as a run's question (`ProgressQuestion`) and a plan's open decision
 * (`PlanDecisions`) both show them: its letter in a small well, or a check in `status-done` once it is the one chosen,
 * then its words, then a muted note when the agent recommends it, and `your answer` when the operator chose it over
 * that. The row around it is the caller's (`OPTION_ROW`), so the same option reads alike whether it is text, a button,
 * or a radio.
 */
export function LetteredOption({
    letter,
    chosen,
    recommended,
    recommendedNote = 'recommended',
    answered = chosen,
    children,
}: {
    /** Its letter. */
    letter: string
    /** Whether it is the one chosen, which its well marks with a check. */
    chosen: boolean
    /** Whether the agent recommends it. */
    recommended: boolean
    /** What the agent's recommendation says, when it says more than `recommended`. */
    recommendedNote?: string
    /** Whether to say `your answer` beside it: the operator chose it. Defaults to `chosen`. */
    answered?: boolean
    /** Its words. */
    children: ReactNode
}) {
    return (
        <>
            <span
                className={cn(
                    'grid size-5 shrink-0 place-items-center rounded-xs border font-mono text-xs',
                    chosen
                        ? 'border-status-done/40 bg-status-done/12 text-status-done'
                        : 'bg-surface text-muted-foreground',
                )}
            >
                {chosen ? <Check aria-hidden className="size-3" /> : letter}
            </span>
            {/* Its words' first line is level with the well, both 20px tall; a long option wraps under. */}
            <span className="min-w-0 flex-1 leading-5 break-words">{children}</span>
            {recommended && <span className="shrink-0 text-xs leading-5 text-muted-foreground">{recommendedNote}</span>}
            {answered && <span className="shrink-0 text-xs leading-5 text-status-done">your answer</span>}
        </>
    )
}
