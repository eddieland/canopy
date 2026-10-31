import { useMutation, useQueryClient } from '@tanstack/react-query'
import { Octagon, Square } from 'lucide-react'
import { useState } from 'react'

import { refreshTask, stopTask } from '@/api/mutations'
import type { TaskSummary } from '@/api/types'
import { Notice } from '@/components/notice'
import { Button } from '@/components/ui/button'
import { taskStoppedText } from '@/lib/outcomes'
import { taskRef } from '@/lib/refs'

/**
 * The CLI's stop on one task (DESIGN §36), under its reply as a ticket's verbs are: Stop, and Stop now while a run of
 * it works, which also ends that run. Each asks once more inline before it acts: a task has no start, so nothing
 * undoes a stop, and Stop now kills the run. Stopped while its run still works, it keeps Stop now alone, as
 * `canopy stop task:N --now` still ends the run. What the stop did stays under the buttons, in the CLI's words, after
 * the page has dropped the reply it no longer takes. `running` is the run working it now, if one is.
 */
export function TaskActions({ task, running }: { task: TaskSummary; running: number | null }) {
    const client = useQueryClient()
    const [said, setSaid] = useState<string | null>(null)
    const [confirming, setConfirming] = useState<'stop' | 'now' | null>(null)
    const stop = useMutation({
        mutationFn: (now: boolean) => stopTask(task.id, now),
        onSuccess: (stopped, now) => {
            setSaid(taskStoppedText(task.id, stopped, now))
            setConfirming(null)
            void refreshTask(client, task.id)
        },
    })
    const stopped = task.stopped_at !== null
    if (stopped && running === null && said === null && stop.error === null) {
        return null
    }
    const pending = stop.isPending
    // A question the stream has overtaken (the run ended, or the task was stopped elsewhere) is no longer asked.
    let asking = confirming
    if ((asking === 'now' && running === null) || (asking === 'stop' && stopped)) {
        asking = null
    }
    return (
        <div className="flex flex-col gap-2 border-t p-3" data-testid="task-actions">
            {(!stopped || running !== null) && (
                <div className="flex flex-wrap items-center gap-2">
                    {asking === null && !stopped && (
                        <Button variant="outline" onClick={() => setConfirming('stop')} disabled={pending}>
                            <Square />
                            Stop
                        </Button>
                    )}
                    {asking === null && running !== null && (
                        <Button variant="destructive" onClick={() => setConfirming('now')} disabled={pending}>
                            <Octagon />
                            Stop now
                        </Button>
                    )}
                    {asking === 'stop' && (
                        <>
                            <Button variant="destructive" onClick={() => stop.mutate(false)} disabled={pending}>
                                <Square />
                                Stop {taskRef(task.id)}
                            </Button>
                            <Button variant="ghost" onClick={() => setConfirming(null)} disabled={pending}>
                                Keep it
                            </Button>
                            <span className="text-xs text-muted-foreground">
                                {running === null
                                    ? 'Nothing starts it again, and it takes no more replies.'
                                    : `Nothing starts it again; run ${running} finishes its work.`}
                            </span>
                        </>
                    )}
                    {asking === 'now' && running !== null && (
                        <>
                            <Button variant="destructive" onClick={() => stop.mutate(true)} disabled={pending}>
                                <Octagon />
                                End run {running} now
                            </Button>
                            <Button variant="ghost" onClick={() => setConfirming(null)} disabled={pending}>
                                Keep it running
                            </Button>
                        </>
                    )}
                </div>
            )}
            <Notice error={stop.error}>{said}</Notice>
        </div>
    )
}
