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
 * asks once more before it does. Forget cannot be undone here, so it asks for the ticket's key typed out; until then it
 * is the quietest of them, at the row's end, since what is said loudest is clicked first. A public ticket has no Stop,
 * since its queue label authorizes it: while a worker runs on one, a line in Stop's place says how to stop it. Whether
 * the ticket is private is a chip, beside its page's title or over its attention item's conversation, so nothing here
 * says it again. `quiet` sets Start and Stop as ghost buttons, for an attention item whose reason asks for something
 * else, where they are a row under its thread (ui/DESIGN.md, "The attention detail").
 */
export function TicketActions({ ticket, quiet = false }: { ticket: TicketSummary; quiet?: boolean }) {
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
                    <Button variant={quiet ? 'ghost' : 'outline'} onClick={() => start.mutate()} disabled={pending}>
                        <Play />
                        {ticket.private ? 'Start again' : 'Start privately'}
                    </Button>
                )}
                {started && (
                    <Button variant={quiet ? 'ghost' : 'outline'} onClick={() => stop.mutate(false)} disabled={pending}>
                        <Square />
                        Stop
                    </Button>
                )}
                {!ticket.private && ticket.running_run !== null && (
                    <span className="text-xs text-muted-foreground" data-testid="public-stop">
                        Public: remove its queue label to stop it, or start it privately.
                    </span>
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
                    <Button
                        variant="ghost"
                        className="ml-auto text-status-failed hover:text-status-failed"
                        onClick={() => setConfirming('forget')}
                        disabled={pending}
                    >
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
            <Notice error={start.error ?? stop.error ?? forget.error} reserve>
                {said}
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
                over on a new branch. Its runs stay, and still count toward the attempt limits. Its conversation stays
                too, folded away on its page, since no worker reads it again. Closing its PRs and deleting its branch on
                origin stay yours. This cannot be undone here.
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
