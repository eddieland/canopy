import { useMutation, useQueryClient } from '@tanstack/react-query'
import { Plus } from 'lucide-react'
import { useState } from 'react'

import { grantLimit, refreshLimits } from '@/api/mutations'
import type { Limit } from '@/api/types'
import { Notice } from '@/components/notice'
import { Button } from '@/components/ui/button'
import { limitCount, limitLabel, stuck } from '@/lib/limits'
import { grantedText } from '@/lib/outcomes'
import { cn } from '@/lib/utils'

/**
 * `canopy grant` on what is stuck at a limit (DESIGN §22): a row for each of `limits` whose runs have reached it, a
 * ticket's unit's runs of one kind or a PR's review runs, with a button that allows one more. Every run still counts,
 * and the grant dispatches nothing: the next tick decides. Nothing at all while nothing is at its limit and nothing
 * was granted here. `ticketKey` is the ticket the units are of; a PR's own page has none.
 */
export function GrantLimits({
    limits,
    ticketKey,
    className,
}: {
    limits: readonly Limit[]
    ticketKey: string | null
    className?: string
}) {
    const client = useQueryClient()
    const [said, setSaid] = useState<string | null>(null)
    const grant = useMutation({
        mutationFn: (limit: Limit) => grantLimit(ticketKey, limit),
        onSuccess: (granted, limit) => {
            setSaid(grantedText(limit.kind === 'review' ? (limit.pr_url ?? '') : (ticketKey ?? ''), granted))
            void refreshLimits(client, ticketKey, limit)
        },
    })
    const atLimit = stuck(limits)
    if (atLimit.length === 0 && said === null && grant.error === null) {
        return null
    }
    return (
        <div
            // Tinted while something is stuck, in the failure color its `attempt_limit` chip wears, so it stands out.
            className={cn('flex flex-col gap-2 p-3', atLimit.length > 0 && 'bg-status-failed/8', className)}
            data-testid="grant-limits"
        >
            {atLimit.length > 0 && (
                <>
                    <p className="text-sm">
                        <span className="font-medium text-status-failed">At its limit.</span> The loop does no more of
                        it until you allow another; every run still counts.
                    </p>
                    <ul className="flex flex-col gap-1">
                        {atLimit.map((limit) => (
                            <li
                                key={`${limit.kind} ${limit.repo ?? ''} ${limit.pr_url ?? ''}`}
                                className="flex flex-wrap items-center gap-x-3 gap-y-1 text-sm"
                            >
                                <span className="font-mono text-xs font-medium">{limitLabel(limit)}</span>
                                <span className="readout text-xs text-status-failed">{limitCount(limit)}</span>
                                <Button
                                    variant="outline"
                                    size="sm"
                                    className="ml-auto"
                                    title={command(ticketKey, limit)}
                                    onClick={() => grant.mutate(limit)}
                                    disabled={grant.isPending}
                                    data-testid={`grant-${limitLabel(limit)}`}
                                >
                                    <Plus />
                                    Allow one more
                                </Button>
                            </li>
                        ))}
                    </ul>
                </>
            )}
            <Notice error={grant.error}>{said}</Notice>
        </div>
    )
}

/** The CLI's command for the same grant, shown on hover so it can be found or typed there. */
function command(ticketKey: string | null, limit: Limit): string {
    if (limit.kind === 'review') {
        return `canopy grant ${limit.pr_url ?? 'URL'} review`
    }
    const repo = limit.repo === null ? '' : ` --repo ${limit.repo}`
    return `canopy grant ${ticketKey ?? 'KEY'} ${limit.kind}${repo}`
}
