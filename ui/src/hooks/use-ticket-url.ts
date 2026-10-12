import { useQuery } from '@tanstack/react-query'

import { metaQuery } from '@/api/queries'
import { ticketUrl } from '@/lib/ticket-url'

/** The ticket's page in the tracker, from `tracker.ticket_url`; undefined when that is unset or not read yet. */
export function useTicketUrl(ticketKey: string): string | undefined {
    const meta = useQuery(metaQuery)
    return ticketUrl(meta.data?.ticket_url, ticketKey)
}
