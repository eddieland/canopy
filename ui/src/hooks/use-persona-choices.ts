import { useMutation, useQueryClient } from '@tanstack/react-query'
import { useState } from 'react'

import { chooseTicketPersona } from '@/api/mutations'
import { keys } from '@/api/queries'
import type { AgentPersona } from '@/api/types'
import { personaText } from '@/lib/outcomes'

/** A choice a menu makes: an agent's persona by name, or null to clear the ticket's override. */
interface Choice {
    /** The agent the choice is for. */
    agent: AgentPersona['agent']
    /** The persona's name, or null to clear the override. */
    persona: string | null
}

/** The choices of persona a ticket's rows make, one at a time, and what the last one did. */
export interface PersonaChoices {
    /** Sets an agent's override to a persona, or clears it with null, as `canopy persona` does. */
    choose: (agent: AgentPersona['agent'], persona: string | null) => void
    /** Whether a choice is being saved, during which no other can be made. */
    pending: boolean
    /** Why the last choice was refused, or failed; null when it did not. */
    error: unknown
    /** What the last choice saved did, in the CLI's words; null before one is saved. */
    said: string | null
}

/**
 * The persona choices of a ticket's agents (DESIGN §31), as `canopy persona KEY NAME --agent AGENT` and `--clear` make
 * them, for its rows to share: what the last one did shows once, under them all (`Notice`).
 */
export function usePersonaChoices(ticketKey: string): PersonaChoices {
    const client = useQueryClient()
    const [said, setSaid] = useState<string | null>(null)
    const mutation = useMutation({
        mutationFn: ({ agent, persona }: Choice) => chooseTicketPersona(ticketKey, agent, persona),
        onSuccess: (now) => {
            setSaid(personaText(ticketKey, now))
            void client.invalidateQueries({ queryKey: keys.ticket(ticketKey) })
        },
    })
    return {
        choose: (agent, persona) => mutation.mutate({ agent, persona }),
        pending: mutation.isPending,
        error: mutation.error,
        said,
    }
}
