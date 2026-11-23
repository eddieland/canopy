import { useQuery } from '@tanstack/react-query'
import { Link } from '@tanstack/react-router'
import { MessageSquareReply } from 'lucide-react'

import { unsentDraftsQuery } from '@/api/queries'
import { Chip } from '@/components/status'
import { Tip } from '@/components/tip'
import { DRAFTS_ANCHOR, draftsText, unsentAnchor, unsentCount } from '@/lib/drafts'
import { cn } from '@/lib/utils'

/**
 * How many drafts wait on the operator for a PR (`url`) or for a ticket and its PRs (`ticketKey`), as a list's row
 * says it (DESIGN.md, Drafts): a chip in `status-blocked`, the color of what waits on them, which opens where the
 * drafts are read and sent: a PR's on its page, at its list of them, a ticket's on the drafts page, at the ticket.
 * In a narrow list it is its icon and count. Nothing when none waits, which is most rows.
 */
export function UnsentDraftsChip({
    url,
    ticketKey,
    className,
}: {
    url?: string
    ticketKey?: string
    className?: string
}) {
    const { data } = useQuery(unsentDraftsQuery)
    const count = unsentCount(data ?? [], { url, ticket: ticketKey })
    if (count === 0) {
        return null
    }
    const said = `${draftsText(count)} ${count === 1 ? 'waits' : 'wait'} on you to send`
    const chip = (
        <Chip tone="blocked">
            <MessageSquareReply className="size-3" aria-hidden />
            {count}
            {/* In a narrow list the count alone, so a title keeps its room; the word is still said. */}
            <span className="@max-4xl:sr-only">{count === 1 ? 'draft' : 'drafts'}</span>
        </Chip>
    )
    const link = cn('inline-flex shrink-0 rounded-sm hover:brightness-110', className)
    return (
        <Tip fact={said}>
            {url === undefined ? (
                <Link
                    to="/pull-requests/drafts"
                    hash={ticketKey === undefined ? undefined : unsentAnchor(ticketKey)}
                    className={link}
                    data-testid="unsent-drafts-chip"
                >
                    {chip}
                </Link>
            ) : (
                <Link
                    to="/pull-requests/pr"
                    search={{ url }}
                    hash={DRAFTS_ANCHOR}
                    className={link}
                    data-testid="unsent-drafts-chip"
                >
                    {chip}
                </Link>
            )}
        </Tip>
    )
}
