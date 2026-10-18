import { Field } from '@/components/fields'
import { None } from '@/components/none'
import { Chip } from '@/components/status'
import { TicketLink } from '@/components/ticket-link'
import { TicketTitle } from '@/components/ticket-title'
import { NO_TICKET } from '@/lib/words'

/**
 * A detail page's ticket field, one way on every page whose subject has a ticket (a run's, a review's, a PR's): the
 * key, opening the ticket's page, then a run's kind as a chip, then the ticket's title. A PR canopy only reviews has
 * none, and says why, but on a PR's own page, whose description says it (`why={false}`). A private run says so once,
 * in the chip beside its page's title.
 */
export function TicketField({
    ticketKey,
    title,
    kind,
    why = true,
}: {
    /** The ticket's key, or null for a PR canopy only reviews. */
    ticketKey: string | null
    /** The ticket's title, as the overseer named it; null until it has one. */
    title: string | null
    /** The kind of run the page is, as its chip says it. */
    kind?: string
    /** Whether no ticket says why, false where the page already does. */
    why?: boolean
}) {
    return (
        <Field label="ticket">
            {ticketKey === null ? (
                <None reason={why ? NO_TICKET : undefined} />
            ) : (
                <span className="flex min-w-0 items-center gap-2">
                    <TicketLink ticketKey={ticketKey} className="shrink-0" />
                    {kind !== undefined && <Chip word={kind} />}
                    <TicketTitle title={title} />
                </span>
            )}
        </Field>
    )
}
