import { useMutation, useQueryClient } from '@tanstack/react-query'
import { Eraser, Octagon, Play, Square } from 'lucide-react'
import { useState } from 'react'
import type { SubmitEvent } from 'react'

import { forgetTicket, refreshTicket, startTicket, stopTicket } from '@/api/mutations'
import type { TicketSummary } from '@/api/types'
import { Input } from '@/components/input'
import { Notice } from '@/components/notice'
import { Button } from '@/components/ui/button'
import { forgotText, startedText, stoppedText } from '@/lib/outcomes'

/**
 * The CLI's verbs on one ticket: start, stop, stop now, and forget (DESIGN §22). Stop now kills the running run, so it
 * asks once more before it does. Forget cannot be undone here, so it asks for the ticket's key typed out.
 */
export function TicketActions({ ticket }: { ticket: TicketSummary }) {
    const client = useQueryClient()
    const key = ticket.key
    const [said, setSaid] = useState<string | null>(null)
    const [confirming, setConfirming] = useState<'stop' | 'forget' | null>(null)
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
            setConfirming(null)
            void refreshTicket(client, key)
        },
    })
    const forget = useMutation({
        mutationFn: (typed: string) => forgetTicket(key, typed),
        onSuccess: (forgot) => {
            setSaid(forgotText(key, forgot))
            setConfirming(null)
            void refreshTicket(client, key)
        },
    })
    const started = ticket.start === 'started'
    const pending = start.isPending || stop.isPending || forget.isPending
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
                {ticket.private && ticket.running_run !== null && confirming === null && (
                    <Button variant="destructive" onClick={() => setConfirming('stop')} disabled={pending}>
                        <Octagon />
                        Stop now
                    </Button>
                )}
                {confirming === 'stop' && (
                    <>
                        <Button variant="destructive" onClick={() => stop.mutate(true)} disabled={pending}>
                            <Octagon />
                            End run {ticket.running_run} now
                        </Button>
                        <Button variant="ghost" onClick={() => setConfirming(null)} disabled={pending}>
                            Keep it running
                        </Button>
                    </>
                )}
                {confirming === null && (
                    <Button variant="destructive" onClick={() => setConfirming('forget')} disabled={pending}>
                        <Eraser />
                        Forget
                    </Button>
                )}
            </div>
            {confirming === 'forget' && (
                <ForgetChallenge
                    ticketKey={key}
                    pending={pending}
                    onForget={(typed) => forget.mutate(typed)}
                    onCancel={() => setConfirming(null)}
                />
            )}
            <Notice error={start.error ?? stop.error ?? forget.error}>
                {said ??
                    (ticket.private
                        ? 'Private: workers read the ticket and write nothing to it.'
                        : 'Public: its queue label authorizes it. Starting it here makes it private from now on.')}
            </Notice>
        </div>
    )
}

/** What forgetting does, and a field the ticket's key must be typed into before the button that forgets is enabled. */
function ForgetChallenge({
    ticketKey,
    pending,
    onForget,
    onCancel,
}: {
    ticketKey: string
    pending: boolean
    onForget: (typed: string) => void
    onCancel: () => void
}) {
    const [typed, setTyped] = useState('')
    const matches = typed === ticketKey

    function submit(event: SubmitEvent<HTMLFormElement>) {
        event.preventDefault()
        if (matches) {
            onForget(typed)
        }
    }

    return (
        <form
            onSubmit={submit}
            aria-label="Forget"
            className="flex flex-col gap-2 rounded-md border border-status-failed/40 bg-status-failed/5 p-3"
        >
            <p className="text-xs text-foreground">
                canopy drops what it knows of {ticketKey}&apos;s branch, PRs, and phase, and its next implement starts
                over on a new branch. Its runs and conversation stay, and its runs still count toward the attempt
                limits. Closing its PRs and deleting its branch on origin stay yours. This cannot be undone here.
            </p>
            <label className="panel-label" htmlFor="forget-confirm">
                Type {ticketKey} to confirm
            </label>
            <div className="flex flex-wrap items-center gap-2">
                <Input
                    id="forget-confirm"
                    value={typed}
                    onChange={(event) => setTyped(event.target.value)}
                    placeholder={ticketKey}
                    autoComplete="off"
                    spellCheck={false}
                    className="max-w-56 font-mono"
                />
                <Button type="submit" variant="destructive" disabled={pending || !matches}>
                    <Eraser />
                    Forget {ticketKey}
                </Button>
                <Button type="button" variant="ghost" onClick={onCancel} disabled={pending}>
                    Keep it
                </Button>
            </div>
        </form>
    )
}
