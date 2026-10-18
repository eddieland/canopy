import { Unplug } from 'lucide-react'

import { Age } from '@/components/age'
import { useLoopDown } from '@/hooks/use-loop-down'
import { cn } from '@/lib/utils'

/**
 * The band over every page while the loop isn't answering (ui/DESIGN.md, the header): once the stream has been down
 * BAND_MS, it says so, that the page shows what the loop last said and how long ago, and how to start the loop again.
 * Only `canopy loop` serves the UI (D073), so a stream that will not come back almost always means it stopped. It goes
 * the moment the stream opens again, with no reload.
 */
export function LoopDownBand() {
    const down = useLoopDown()
    if (!down.band || down.since === null) {
        return null
    }
    return (
        <section
            aria-label="The loop isn't answering"
            data-testid="loop-down"
            className={cn(
                'mx-auto mb-6 flex max-w-[112rem] items-start gap-3 rounded-md border px-3 py-2',
                'border-status-blocked/40 bg-status-blocked/8',
            )}
        >
            <Unplug aria-hidden className="mt-0.5 size-4 shrink-0 text-status-blocked" />
            <div className="flex min-w-0 flex-1 flex-col gap-0.5">
                <p className="text-sm">
                    <span className="font-medium text-status-blocked">The loop isn&apos;t answering. </span>
                    This page shows what it last said,{' '}
                    <Age at={new Date(down.since).toISOString()} variant="ago" className="text-sm" />.
                </p>
                <p className="text-xs text-muted-foreground">
                    Start it again with <code className="font-mono">canopy loop</code>, or{' '}
                    <code className="font-mono">canopy daemon start</code> to run it detached. This band goes when it
                    answers.
                </p>
            </div>
        </section>
    )
}
