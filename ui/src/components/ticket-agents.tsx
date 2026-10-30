import { Fragment } from 'react'

import type { AgentModel, AgentPersona } from '@/api/types'
import { Notice } from '@/components/notice'
import { ModelChoice } from '@/components/ticket-models'
import { PersonaChoice } from '@/components/ticket-personas'
import { usePersonaChoices } from '@/hooks/use-persona-choices'
import { cn } from '@/lib/utils'

/**
 * Who each of a ticket's agents writes as and what it runs on, from its next run: one grid of a row per agent, its
 * workers, its planner, and its reviewer, the agent, then its persona (`PersonaChoice`), then its model
 * (`ModelChoice`), each yours to choose here or with `canopy persona` and `canopy model`. A grid too narrow for the
 * three puts each agent's model under its persona. What a choice of persona did shows under the rows; a choice of model
 * says so in its own row.
 */
export function TicketAgents({
    ticketKey,
    personas,
    names,
    models,
    className,
}: {
    ticketKey: string
    personas: readonly AgentPersona[]
    names: readonly string[]
    models: readonly AgentModel[]
    className?: string
}) {
    const choices = usePersonaChoices(ticketKey)
    const agents = [...new Set([...personas.map((p) => p.agent), ...models.map((m) => m.agent)])]
    if (agents.length === 0) {
        return null
    }
    return (
        <div
            className={cn(
                'grid grid-cols-[8rem_minmax(0,1fr)] gap-x-3 px-3 pt-3 pb-1.5 text-sm',
                // The persona's column as wide as its widest, up to a share that leaves the model room for its id.
                '@lg:grid-cols-[8rem_fit-content(45%)_minmax(0,1fr)]',
                className,
            )}
            data-testid="ticket-agents"
        >
            {/* Each menu's name says which it is to a screen reader. */}
            <div aria-hidden className="col-span-full hidden grid-cols-subgrid pb-1.5 @lg:grid">
                <span className="col-start-2 panel-label">persona</span>
                <span className="panel-label">model</span>
            </div>
            <dl className="col-span-full grid grid-cols-subgrid items-baseline gap-y-1.5">
                {agents.map((agent) => {
                    const persona = personas.find((p) => p.agent === agent)
                    const model = models.find((m) => m.agent === agent)
                    return (
                        <Fragment key={agent}>
                            <dt className="panel-label">{agent}</dt>
                            {persona !== undefined && (
                                <dd className="min-w-0 break-words">
                                    <PersonaChoice current={persona} names={names} choices={choices} />
                                </dd>
                            )}
                            {model !== undefined && (
                                <dd className="col-start-2 min-w-0 break-words @lg:col-start-3">
                                    <ModelChoice ticketKey={ticketKey} current={model} models={models} />
                                </dd>
                            )}
                        </Fragment>
                    )
                })}
            </dl>
            <Notice error={choices.error} className="col-span-full pt-1.5 pb-1.5">
                {choices.said}
            </Notice>
        </div>
    )
}
