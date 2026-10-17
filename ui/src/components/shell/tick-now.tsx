import { useMutation, useQuery } from '@tanstack/react-query'
import { FastForward } from 'lucide-react'

import { tickNow } from '@/api/mutations'
import { tickQuery } from '@/api/queries'
import { Button } from '@/components/ui/button'
import { cn } from '@/lib/utils'

/**
 * The header's Tick now: `t` at the loop's terminal (docs/DESIGN.md §6). The loop's wait ends at once, before its
 * least gap and while it is paused, which it stays. While the latest tick runs, the button waits for it: the tick
 * starting and ending is the state the readouts beside it show, so it has no `Notice`. A failure colors the button and
 * says why on hover and to a screen reader.
 */
export function TickNow() {
    const running = useQuery(tickQuery).data?.tick?.status === 'running'
    const ask = useMutation({ mutationFn: tickNow })
    const failed = ask.error?.message ?? null
    return (
        <>
            <Button
                variant="ghost"
                size="sm"
                className={cn(failed !== null && 'text-status-failed')}
                title={
                    failed ??
                    (running
                        ? 'A tick is running now.'
                        : 'Tick now: the loop runs its next tick at once, as `t` at its terminal does, paused or not.')
                }
                disabled={running || ask.isPending}
                onClick={() => ask.mutate()}
            >
                <FastForward />
                Tick now
            </Button>
            {failed !== null && (
                <span role="alert" className="sr-only">
                    {failed}
                </span>
            )}
        </>
    )
}
