import { useMutation, useQueryClient } from '@tanstack/react-query'
import { Send } from 'lucide-react'
import { useState } from 'react'

import { newSubmission, refreshTicket, sendLeftFeedback } from '@/api/mutations'
import type { LeftFeedback } from '@/api/types'
import { LinkOutIcon } from '@/components/link-out-icon'
import { LinkedText } from '@/components/linked-text'
import { ListPanel } from '@/components/list-panel'
import { Notice } from '@/components/notice'
import { ListRow } from '@/components/rows'
import { Chip } from '@/components/status'
import { TickLink } from '@/components/tick-link'
import { Clipped } from '@/components/tip'
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
 * its own, `Left feedback`: each item a row of why it was left, its author, its first line, where it is, linking out to
 * it, the tick that left it, and a button that sends it to a worker, as `canopy send KEY N` does: a reply on the ticket
 * naming it, which the next tick reads as your go-ahead. With none, its header alone, as every list's (`ListPanel`).
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
            <ul className="divide-y" data-testid="left-feedback">
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

/**
 * One item, in the columns of its kind (`left-feedback`): why it was left, who wrote it and its first line, where it
 * is, linking out to it, the tick that left it, and its button. The comment is the reviewer's text, never markup.
 */
function LeftRow({ item, pending, onSend }: { item: LeftFeedback; pending: boolean; onSend: () => void }) {
    const where = item.path !== null && item.line !== null ? `${item.path}:${item.line}` : item.item
    const author = item.author ?? 'unknown'
    return (
        <ListRow kind="left-feedback" className="text-sm">
            <span>
                <Chip className="whitespace-nowrap">{LEFT_REASONS[item.reason]}</Chip>
            </span>
            {/* Its author leads its text, as a message's does in a conversation, so every width shows both. */}
            <span className="flex min-w-0 items-baseline gap-2">
                <span className="shrink-0 text-xs text-muted-foreground">{author}</span>
                <Clipped text={item.body.trim()}>
                    <LinkedText text={firstLine(item.body)} />
                </Clipped>
            </span>
            <Where item={item} where={where} />
            <span className="text-right">
                <TickLink id={item.tick_id} />
            </span>
            <Button
                size="icon-xs"
                variant="ghost"
                className="-my-1 justify-self-end"
                onClick={onSend}
                disabled={pending}
                title="Send to a worker: a reply on the ticket naming it, which the next tick reads as your go-ahead"
                aria-label={`send ${where} to a worker`}
            >
                <Send aria-hidden />
            </Button>
        </ListRow>
    )
}

/**
 * Where an item is, in a column too narrow for a whole path: its file's name and line (`client.ts:42`), or `review`
 * for a review's own text, linking out to it on GitHub, the whole path on hover and to a screen reader.
 */
function Where({ item, where }: { item: LeftFeedback; where: string }) {
    const shown = item.path !== null && item.line !== null ? `${baseName(item.path)}:${item.line}` : item.item
    if (item.url === null) {
        return <Clipped text={where} mono className="font-mono text-xs text-muted-foreground" />
    }
    return (
        <a
            href={item.url}
            target="_blank"
            rel="noreferrer noopener"
            title={`${where} on GitHub`}
            aria-label={`${where} on GitHub`}
            className="flex min-w-0 items-center gap-1 font-mono text-xs text-accent underline-offset-4 hover:underline"
        >
            <span className="truncate">{shown}</span>
            <LinkOutIcon href={item.url} className="shrink-0" />
        </a>
    )
}

/** A comment's first line with any text, as its row shows it. */
function firstLine(body: string): string {
    return body.split('\n').find((line) => line.trim() !== '') ?? ''
}

/** A path's last part, the file's own name. */
function baseName(path: string): string {
    return path.slice(path.lastIndexOf('/') + 1)
}
