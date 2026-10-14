import type { ReactNode } from 'react'

import { ApiError } from '@/api/client'
import { cn, isBlank } from '@/lib/utils'

/**
 * What an action said: a refusal in the failure color, naming its guard as the CLI does, or a plain outcome. Any other
 * error, an `Error` or the words of one, shows the same way.
 */
export function Notice({ error, children, className }: { error?: unknown; children?: ReactNode; className?: string }) {
    if (error !== undefined && error !== null) {
        const guard = error instanceof ApiError ? error.guard : null
        const text = error instanceof Error ? error.message : typeof error === 'string' ? error : 'the request failed'
        return (
            <p role="alert" className={cn('text-xs text-status-failed', className)}>
                {guard ? <span className="font-mono">refused ({guard}): </span> : null}
                {text}
            </p>
        )
    }
    if (isBlank(children)) {
        return null
    }
    return <output className={cn('block text-xs text-muted-foreground', className)}>{children}</output>
}
