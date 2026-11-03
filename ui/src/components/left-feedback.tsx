import { useMutation, useQueryClient } from '@tanstack/react-query'
import { Send } from 'lucide-react'
import { useState } from 'react'

import { newSubmission, refreshTicket, sendLeftFeedback } from '@/api/mutations'
import type { LeftFeedback } from '@/api/types'
import { LinkOut } from '@/components/link-out-icon'
import { ListPanel } from '@/components/list-panel'
import { Notice } from '@/components/notice'
import { Chip } from '@/components/status'
import { TickLink } from '@/components/tick-link'
import { Button } from '@/components/ui/button'
import { leftSentText } from '@/lib/outcomes'

// Why the loop left an item, in the words a row shows, by the reason canopy records (`vocab.PassReason`).
const LEFT_REASONS: Record<LeftFeedback['reason'], string> = {
    optional: 'optional',
    would_reset_approval: 'would reset approval',
    question: 'a question',
    already_done: 'already done',
    out_of_scope: 'out of scope',
    operator_said: 'you said to leave it',
    resolved: 'resolved',
}

/**
 * The feedback on a ticket's PRs its review cursors passed with no worker, still left (DESIGN §7), in a list panel of
 * its own, `Left feedback`: each item's author, where it is, linking out to it, why it was left and the tick that left
 * it, and a button that sends it to a worker, as `canopy send KEY N` does: a reply on the ticket naming it, which the
 * next tick reads as your go-ahead. With none, its header alone, as every list's (`ListPanel`).
 */
export function LeftFeedbackList({
    ticketKey,
    items,
    className,
}: {
    /** The ticket the items are on. */
    ticketKey: string
    /** What is left, oldest first, as the ticket's page reads it. */
    items: LeftFeedback[]
    /** Classes for the panel, such as its place in the page's grid. */
    className?: string
}) {
    const client = useQueryClient()
    // Drawn anew after each send, so a retry of the same one records nothing new (DESIGN §22).
    const [submission, setSubmission] = useState(newSubmission)
    const [said, setSaid] = useState<string | null>(null)
    const send = useMutation({
        mutationFn: (number: number) => sendLeftFeedback(ticketKey, [number], submission),
        onSuccess: (sent) => {
            setSaid(leftSentText(ticketKey, sent))
            setSubmission(newSubmission())
            void refreshTicket(client, ticketKey)
        },
    })
    return (
        <ListPanel
            label="Left feedback"
            count={items.length}
            aria-label="Left feedback"
            className={className}
            data-testid="ticket-left-feedback"
        >
            <ul className="flex flex-col gap-2 p-3" data-testid="left-feedback">
                {items.map((item) => (
                    <LeftRow
                        key={`${item.pr_url}-${item.id}`}
                        item={item}
                        pending={send.isPending}
                        onSend={() => send.mutate(item.number)}
                    />
                ))}
            </ul>
            <Notice error={send.error} className="mx-3 mb-3">
                {said}
            </Notice>
        </ListPanel>
    )
}

/** One item: who wrote it and where, why it was left and by which tick, and its button. */
function LeftRow({ item, pending, onSend }: { item: LeftFeedback; pending: boolean; onSend: () => void }) {
    const where = item.path !== null && item.line !== null ? `${item.path}:${item.line}` : item.item
    return (
        <li className="flex flex-wrap items-center gap-x-2 gap-y-1 text-sm">
            <span className="min-w-0 truncate font-mono text-xs">{where}</span>
            {item.url !== null && <LinkOut href={item.url} label={`open ${item.item} ${item.id} on GitHub`} />}
            <span className="text-xs text-muted-foreground">by {item.author ?? 'unknown'}</span>
            <Chip>{LEFT_REASONS[item.reason]}</Chip>
            <span className="text-xs text-muted-foreground">
                left by <TickLink id={item.tick_id} />
            </span>
            <Button
                size="sm"
                variant="outline"
                className="ml-auto"
                onClick={onSend}
                disabled={pending}
                title="Reply on the ticket naming it: the next tick reads it as your go-ahead"
                aria-label={`send ${where} to a worker`}
            >
                <Send />
                send to a worker
            </Button>
        </li>
    )
}
