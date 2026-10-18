import { useQuery } from '@tanstack/react-query'

import { attentionQuery } from '@/api/queries'

/**
 * Whether an untrusted review waits on the operator's go-ahead for the ticket (D089): the attention list, which every
 * page reads for the nav's count, holds an `untrusted_review` item about it.
 */
export function useUntrustedReview(ticketKey: string): boolean {
    const items = useQuery(attentionQuery).data
    return items?.some((item) => item.ticket_key === ticketKey && item.reason === 'untrusted_review') ?? false
}
