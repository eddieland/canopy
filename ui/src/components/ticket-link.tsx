import { Link } from '@tanstack/react-router'

import { LinkOut } from '@/components/link-out-icon'
import { Tip } from '@/components/tip'
import { useTicketUrl } from '@/hooks/use-ticket-url'
import { cn } from '@/lib/utils'

/**
 * A ticket key that opens the ticket's page, then, when `tracker.ticket_url` is set, a small icon opening it in the
 * tracker: the key goes in, the icon out, as a PR's link does. A key cut to fit its cell is whole on hover. `plan`
 * opens the ticket's plan page instead, where its plan is approved; `tracker={false}` leaves the icon out, for a dense
 * list of keys where it would repeat on every one.
 */
export function TicketLink({
    ticketKey,
    className,
    plan = false,
    tracker: withTracker = true,
}: {
    ticketKey: string
    className?: string
    plan?: boolean
    tracker?: boolean
}) {
    const tracker = useTicketUrl(ticketKey)
    const linkClass = 'truncate text-accent underline-offset-4 hover:underline'
    return (
        <span className={cn('inline-flex min-w-0 items-center gap-1 font-mono text-xs', className)}>
            <Tip fact={ticketKey} mono whenCut>
                {plan ? (
                    <Link to="/tickets/$key/plan" params={{ key: ticketKey }} className={linkClass}>
                        {ticketKey}
                    </Link>
                ) : (
                    <Link to="/tickets/$key" params={{ key: ticketKey }} className={linkClass}>
                        {ticketKey}
                    </Link>
                )}
            </Tip>
            {withTracker && tracker && <LinkOut href={tracker} label={`${ticketKey} in the tracker`} />}
        </span>
    )
}
