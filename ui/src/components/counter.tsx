import type { ReactNode } from 'react'

import { RollingNumber } from '@/components/rolling-number'
import { Skeleton } from '@/components/ui/skeleton'
import { cn } from '@/lib/utils'

export type Tone = 'running' | 'blocked' | 'failed' | 'stopped' | 'accent' | 'plain'

// Written out so Tailwind finds them: each counter's top rule.
const RULE: Record<Tone, string> = {
    running: 'border-t-status-running',
    blocked: 'border-t-status-blocked',
    failed: 'border-t-status-failed',
    stopped: 'border-t-status-stopped',
    accent: 'border-t-accent',
    plain: 'border-t-border',
}

/**
 * One counter. Its value keeps a fixed width and rolls when it changes, and it shows a skeleton only until the first
 * data arrives. Its test id is `counter-` and the label's first word, unless `testId` names one.
 */
export function Counter({
    label,
    value,
    tone,
    testId,
    children,
}: {
    label: string
    value: number | string | undefined
    tone: Tone
    testId?: string
    children: ReactNode
}) {
    return (
        <div
            className={cn(
                'flex min-w-0 flex-col gap-1.5 rounded-md border border-t-2 bg-surface px-4 py-3',
                RULE[tone],
            )}
            data-testid={`counter-${testId ?? label.toLowerCase().split(/[ ,]+/)[0]}`}
        >
            <span className="panel-label">{label}</span>
            <span className="readout h-8 text-3xl leading-8 font-medium">
                {value === undefined ? <Skeleton className="h-7 w-12" /> : <RollingNumber value={String(value)} />}
            </span>
            <span className="truncate text-xs text-muted-foreground">{children}</span>
        </div>
    )
}
