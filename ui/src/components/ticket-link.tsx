import { Link } from '@tanstack/react-router'

import { LinkOut } from '@/components/link-out-icon'
import { Tip } from '@/components/tip'
import { useTicketUrl } from '@/hooks/use-ticket-url'
import { cn } from '@/lib/utils'

/**
 * A ticket key that opens the ticket's page, then, when `tracker.ticket_url` is set, a small icon opening it in the
 * tracker: the key goes in, the icon out, as a PR's link does. A key cut to fit its cell is whole on hover.
 */
export function TicketLink({ ticketKey, className }: { ticketKey: string; className?: string }) {
    const tracker = useTicketUrl(ticketKey)
    return (
        <span className={cn('inline-flex min-w-0 items-center gap-1 font-mono text-xs', className)}>
            <Tip fact={ticketKey} mono whenCut>
                <Link
                    to="/tickets/$key"
                    params={{ key: ticketKey }}
                    className="truncate text-accent underline-offset-4 hover:underline"
                >
                    {ticketKey}
                </Link>
            </Tip>
            {tracker && <LinkOut href={tracker} label={`${ticketKey} in the tracker`} />}
        </span>
    )
}
