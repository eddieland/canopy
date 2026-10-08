import { Link } from '@tanstack/react-router'

import { cn } from '@/lib/utils'

/** A ticket key that opens the ticket's page. */
export function TicketLink({ ticketKey, className }: { ticketKey: string; className?: string }) {
    return (
        <Link
            to="/tickets/$key"
            params={{ key: ticketKey }}
            className={cn('font-mono text-xs text-accent underline-offset-4 hover:underline', className)}
        >
            {ticketKey}
        </Link>
    )
}
