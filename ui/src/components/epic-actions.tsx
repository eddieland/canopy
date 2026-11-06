import { useMutation, useQueryClient } from '@tanstack/react-query'
import { Octagon, Square } from 'lucide-react'
import { useState } from 'react'
import type { ReactNode } from 'react'

import { stopEpic } from '@/api/mutations'
import { keys } from '@/api/queries'
import type { EpicSummary } from '@/api/types'
import { Notice } from '@/components/notice'
import { Button } from '@/components/ui/button'
import { epicStoppedText } from '@/lib/outcomes'
import { epicRef } from '@/lib/refs'

/**
 * The CLI's stop on one epic (DESIGN §43), at its page's title's right, after `Open plan` (`plan`): Stop, and Stop now
 * while a plan run of it works, which also ends that run, as a task's are (`TaskActions`). Each asks once more inline
 * before it acts: nothing undoes a stop, and Stop now kills the run. Asking, Stop says that its members and their work
 * are left as they are, since a stop ends only its planning. Stopped while its plan run still works, it keeps Stop now
 * alone, as `canopy stop epic:N --now` still ends the run. What the stop did stays under the buttons, in the CLI's
 * words. `running` is the plan run at work on it now, if one is.
 */
export function EpicActions({ epic, running, plan }: { epic: EpicSummary; running: number | null; plan?: ReactNode }) {
    const client = useQueryClient()
    const [said, setSaid] = useState<string | null>(null)
    const [confirming, setConfirming] = useState<'stop' | 'now' | null>(null)
    const stop = useMutation({
        mutationFn: (now: boolean) => stopEpic(epic.id, now),
        onSuccess: (stopped, now) => {
            setSaid(epicStoppedText(epic.id, stopped, now))
            setConfirming(null)
        },
        // No stream event carries an epic: its page and the list read it again, refused or not.
        onSettled: () => {
            void client.invalidateQueries({ queryKey: keys.epic(epic.id) })
            void client.invalidateQueries({ queryKey: keys.epics })
        },
    })
    const stopped = epic.stopped_at !== null
    const pending = stop.isPending
    // A question the page has overtaken (the run ended, or the epic was stopped elsewhere) is no longer asked.
    let asking = confirming
    if ((asking === 'now' && running === null) || (asking === 'stop' && stopped)) {
        asking = null
    }
    const acts = !stopped || running !== null
    if (plan === undefined && !acts && said === null && stop.error === null) {
        return null
    }
    return (
        <div className="flex flex-col items-end gap-1.5" data-testid="epic-actions">
            <div className="flex flex-wrap items-center justify-end gap-2">
                {plan}
                {asking === null && !stopped && (
                    <Button variant="outline" size="sm" onClick={() => setConfirming('stop')} disabled={pending}>
                        <Square />
                        Stop
                    </Button>
                )}
                {asking === null && running !== null && (
                    <Button variant="destructive" size="sm" onClick={() => setConfirming('now')} disabled={pending}>
                        <Octagon />
                        Stop now
                    </Button>
                )}
                {asking === 'stop' && (
                    <>
                        <Button variant="destructive" size="sm" onClick={() => stop.mutate(false)} disabled={pending}>
                            <Square />
                            Stop {epicRef(epic.id)}
                        </Button>
                        <Button variant="ghost" size="sm" onClick={() => setConfirming(null)} disabled={pending}>
                            Keep it
                        </Button>
                    </>
                )}
                {asking === 'now' && running !== null && (
                    <>
                        <Button variant="destructive" size="sm" onClick={() => stop.mutate(true)} disabled={pending}>
                            <Octagon />
                            End plan run {running} now
                        </Button>
                        <Button variant="ghost" size="sm" onClick={() => setConfirming(null)} disabled={pending}>
                            Keep it running
                        </Button>
                    </>
                )}
            </div>
            {asking === 'stop' && (
                <p className="max-w-md text-right text-xs text-balance text-muted-foreground">
                    {running === null
                        ? 'No plan run of it starts again, and it takes no more replies.'
                        : `No plan run of it starts again; plan run ${running} finishes its work.`}{' '}
                    Its members and their work are left as they are.
                </p>
            )}
            <Notice error={stop.error} className="max-w-md text-right text-balance">
                {said}
            </Notice>
        </div>
    )
}
