import type { AgentModel } from '@/api/types'
import { TicketModels } from '@/components/ticket-models'

/**
 * A ticket's run refused its model (`model_missing`, `model_list_failed`, DESIGN §13): the ticket's models as its page
 * shows them (`ModelChoice`), each a menu to choose another the runtime lists or clear the override, the fix the item
 * asks for. The runtime's list is read as the item opens, as the ticket's page reads it, but fresh from the runtime
 * rather than the list the server kept: a run has just found a model gone, which a list read minutes ago may still
 * name. A list that cannot be read says why in the menu.
 */
export function ModelAttention({ ticketKey, models }: { ticketKey: string; models: readonly AgentModel[] }) {
    return (
        <section aria-label="Models" className="border-b" data-testid="attention-models">
            <TicketModels ticketKey={ticketKey} models={models} fresh />
        </section>
    )
}
