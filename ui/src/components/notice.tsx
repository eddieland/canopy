import type { ReactNode } from 'react'

import { ApiError } from '@/api/client'
import { InlineCode } from '@/components/rich-text'
import { failedText } from '@/lib/outcomes'
import { cn, isBlank } from '@/lib/utils'

/**
 * What an action said: a refusal in the failure color, naming its guard as the CLI does, or a plain outcome. Any other
 * error, an `Error` or the words of one, shows the same way. Its words' `code` spans are set as code, as an attention
 * item's detail is, so a guard's message reads the same in both. A failure that is not a refusal says what happened in
 * canopy's words (`failedText`), never the browser's. Nothing at all while it has nothing to say, so a panel holds no
 * empty line for it. A `subject` names what failed before it, as `reviewer: refused (unknown_model): …` names which of
 * a ticket's agents a choice was refused for.
 */
export function Notice({
    error,
    subject,
    children,
    className,
}: {
    error?: unknown
    subject?: string
    children?: ReactNode
    className?: string
}) {
    if (error !== undefined && error !== null) {
        const guard = error instanceof ApiError ? error.guard : null
        return (
            <p role="alert" className={cn('text-xs text-status-failed', className)}>
                {subject === undefined ? null : `${subject}: `}
                {guard ? <span className="font-mono">refused ({guard}): </span> : null}
                <InlineCode text={failedText(error)} />
            </p>
        )
    }
    if (isBlank(children)) {
        return null
    }
    return <output className={cn('block text-xs text-muted-foreground', className)}>{children}</output>
}
