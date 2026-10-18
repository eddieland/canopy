import { useMutation, useQuery } from '@tanstack/react-query'
import { FastForward } from 'lucide-react'

import { tickNow } from '@/api/mutations'
import { tickQuery } from '@/api/queries'
import { Button } from '@/components/ui/button'
import { LOOP_DOWN_TITLE, useLoopDown } from '@/hooks/use-loop-down'
import { failedText } from '@/lib/outcomes'
import { cn } from '@/lib/utils'

/**
 * The header's Tick now: `t` at the loop's terminal (docs/DESIGN.md §6). The loop's wait ends at once, before its
 * least gap and while it is paused, which it stays. While the latest tick runs, the button waits for it: the tick
 * starting and ending is the state the readouts beside it show, so it has no `Notice`. A failure colors the button and
 * says why on hover and to a screen reader. While the loop isn't answering, it waits, and says so on hover. `inline`,
 * it is a link's words in an `Empty`'s sentence that names it as the next step, and does the same.
 */
export function TickNow({
    inline = false,
}: {
    /** In a sentence, as a link's words, with no icon. */
    inline?: boolean
}) {
    const running = useQuery(tickQuery).data?.tick?.status === 'running'
    // Nothing would hear it while the loop is down: it waits, and says why, rather than fail with the browser's words.
    const down = useLoopDown().offline
    const ask = useMutation({ mutationFn: tickNow })
    const failed = ask.error === null ? null : failedText(ask.error)
    return (
        <>
            <Button
                variant={inline ? 'link' : 'ghost'}
                size="sm"
                // Inline, it sits on the sentence's baseline in its type, as a link there does.
                className={cn(
                    inline && 'h-auto p-0 align-baseline font-normal',
                    failed !== null && 'text-status-failed',
                )}
                title={
                    (down ? LOOP_DOWN_TITLE : failed) ??
                    (running
                        ? 'A tick is running now.'
                        : 'Tick now: the loop runs its next tick at once, as `t` at its terminal does, paused or not.')
                }
                disabled={down || running || ask.isPending}
                onClick={() => ask.mutate()}
            >
                {!inline && <FastForward />}
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
