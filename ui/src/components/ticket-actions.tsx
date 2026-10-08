import { useMutation, useQueryClient } from '@tanstack/react-query'
import { Octagon, Play, Square } from 'lucide-react'
import { useState } from 'react'

import { refreshTicket, startTicket, stopTicket } from '@/api/mutations'
import type { TicketSummary } from '@/api/types'
import { Notice } from '@/components/notice'
import { Button } from '@/components/ui/button'
import { startedText, stoppedText } from '@/lib/outcomes'

/**
 * The CLI's verbs on one ticket: start, stop, and stop now (DESIGN §22). Stop now kills the running run, so it asks
 * once more before it does.
 */
export function TicketActions({ ticket }: { ticket: TicketSummary }) {
    const client = useQueryClient()
    const key = ticket.key
    const [said, setSaid] = useState<string | null>(null)
    const [confirming, setConfirming] = useState(false)
    const start = useMutation({
        mutationFn: () => startTicket(key),
        onSuccess: (started) => {
            setSaid(startedText(key, started))
            void refreshTicket(client, key)
        },
    })
    const stop = useMutation({
        mutationFn: (now: boolean) => stopTicket(key, now),
        onSuccess: (stopped, now) => {
            setSaid(stoppedText(key, stopped, now))
            setConfirming(false)
            void refreshTicket(client, key)
        },
    })
    const started = ticket.start === 'started'
    const pending = start.isPending || stop.isPending
    return (
        <div className="flex flex-col gap-2 p-3">
            <div className="flex flex-wrap items-center gap-2">
                {!started && (
                    <Button variant="outline" onClick={() => start.mutate()} disabled={pending}>
                        <Play />
                        {ticket.private ? 'Start again' : 'Start privately'}
                    </Button>
                )}
                {started && (
                    <Button variant="outline" onClick={() => stop.mutate(false)} disabled={pending}>
                        <Square />
                        Stop
                    </Button>
                )}
                {ticket.private && ticket.running_run !== null && !confirming && (
                    <Button variant="destructive" onClick={() => setConfirming(true)} disabled={pending}>
                        <Octagon />
                        Stop now
                    </Button>
                )}
                {confirming && (
                    <>
                        <Button variant="destructive" onClick={() => stop.mutate(true)} disabled={pending}>
                            <Octagon />
                            End run {ticket.running_run} now
                        </Button>
                        <Button variant="ghost" onClick={() => setConfirming(false)} disabled={pending}>
                            Keep it running
                        </Button>
                    </>
                )}
            </div>
            <Notice error={start.error ?? stop.error}>
                {said ??
                    (ticket.private
                        ? 'Private: workers read the ticket and write nothing to it.'
                        : 'Public: its queue label authorizes it. Starting it here makes it private from now on.')}
            </Notice>
        </div>
    )
}
