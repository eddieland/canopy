import { Field } from '@/components/fields'
import { None } from '@/components/none'
import { TicketLink } from '@/components/ticket-link'
import { TicketTitle } from '@/components/ticket-title'
import { NO_TICKET } from '@/lib/words'

/**
 * A detail page's ticket field, one way on every page whose subject has a ticket but is not the ticket's own work (a
 * review's, a PR's): the key, opening the ticket's page, then the ticket's title. A PR canopy only reviews has none,
 * and says why. A run's page names its ticket in its header instead, where its title is the page's.
 */
export function TicketField({
    ticketKey,
    title,
}: {
    /** The ticket's key, or null for a PR canopy only reviews. */
    ticketKey: string | null
    /** The ticket's title, as the overseer named it; null until it has one. */
    title: string | null
}) {
    return (
        <Field label="ticket">
            {ticketKey === null ? (
                <None reason={NO_TICKET} />
            ) : (
                <span className="flex min-w-0 items-center gap-2">
                    <TicketLink ticketKey={ticketKey} className="shrink-0" />
                    <TicketTitle title={title} />
                </span>
            )}
        </Field>
    )
}
