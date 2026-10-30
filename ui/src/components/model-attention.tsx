import { useQuery } from '@tanstack/react-query'

import { freshModelsQuery } from '@/api/queries'
import type { AgentModel } from '@/api/types'
import { TicketModels } from '@/components/ticket-models'

/**
 * A ticket's run refused its model (`model_missing`, `model_list_failed`, DESIGN §13): the ticket's models as its page
 * shows them (`ModelChoice`), each a menu to choose another the runtime lists or clear the override, the fix the item
 * asks for. The runtime's list is read as the item opens rather than when a menu does, so the model it no longer lists
 * is marked before the operator goes looking for it; a list that cannot be read says why in the menu.
 */
export function ModelAttention({ ticketKey, models }: { ticketKey: string; models: readonly AgentModel[] }) {
    // A read can start the runtime, which is why the ticket's page waits for a menu to open; here the read is the
    // point, and the menus find it in the cache. Read fresh, not the server's kept list: a run has just found a model
    // gone, which a list read minutes ago may still name.
    useQuery(freshModelsQuery)
    return (
        <section aria-label="Models" className="border-b" data-testid="attention-models">
            <TicketModels ticketKey={ticketKey} models={models} />
        </section>
    )
}
