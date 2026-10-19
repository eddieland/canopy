import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { Pause, Play } from 'lucide-react'

import { pauseLoop, resumeLoop, showLoop } from '@/api/mutations'
import { loopQuery } from '@/api/queries'
import type { Pause as Paused } from '@/api/types'
import { Age } from '@/components/age'
import { Button } from '@/components/ui/button'
import { LOOP_DOWN_TITLE, useLoopDown } from '@/hooks/use-loop-down'
import { failedText } from '@/lib/outcomes'
import { useClock } from '@/lib/clock'
import { localTime } from '@/lib/time'
import { cn } from '@/lib/utils'

// Where a pause came from, in the words the loop's terminal and `canopy status` use.
const CHANNEL: Record<Paused['channel'], string> = {
    loop: "the loop's terminal",
    cli: '`canopy pause`',
    web: 'the web UI',
}

/**
 * The header's pause: `canopy pause` and `canopy resume` (docs/DESIGN.md §6). Running, a Pause button; paused, how
 * long it has been and a Resume button. The pause is the journal's, so a pause from the loop's terminal or the CLI
 * shows here as the stream sends it. A failure colors the button and says why on hover and to a screen reader. While
 * the loop isn't answering, it waits, and says so on hover.
 */
export function LoopPause() {
    const clock = useClock()
    const client = useQueryClient()
    const loop = useQuery(loopQuery)
    const down = useLoopDown().offline
    const toggle = useMutation({
        mutationFn: (pause: boolean) => (pause ? pauseLoop() : resumeLoop()),
        onSuccess: (changed) => showLoop(client, changed.loop),
    })
    // The button's width, held before the state arrives, so the readouts beside it do not move.
    if (loop.data === undefined) {
        return <span aria-hidden className="w-20" />
    }
    const paused = loop.data.paused
    const failed = toggle.error === null ? null : failedText(toggle.error)
    return (
        <div className="flex items-center gap-2" data-testid="loop-pause" data-paused={paused !== null}>
            {paused !== null && (
                <span
                    className="readout text-xs whitespace-nowrap text-status-blocked"
                    title={`Paused at ${localTime(paused.since, clock)} from ${CHANNEL[paused.channel]}`}
                >
                    paused · <Age at={paused.since} className="text-inherit" />
                </span>
            )}
            <Button
                variant="ghost"
                size="sm"
                className={cn('w-20', failed !== null && 'text-status-failed')}
                title={
                    (down ? LOOP_DOWN_TITLE : failed) ??
                    (paused === null
                        ? 'Pause the loop: no tick starts until you resume it. A tick already running finishes.'
                        : 'Resume the loop: it ticks when its wait runs out, at once if it already has.')
                }
                disabled={down || toggle.isPending}
                onClick={() => toggle.mutate(paused === null)}
            >
                {paused === null ? <Pause /> : <Play />}
                {paused === null ? 'Pause' : 'Resume'}
            </Button>
            {failed !== null && (
                <span role="alert" className="sr-only">
                    {failed}
                </span>
            )}
        </div>
    )
}
