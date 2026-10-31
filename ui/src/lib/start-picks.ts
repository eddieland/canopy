import type { AgentModel, StartRequest } from '@/api/types'

/** One of a ticket's agents a start chooses a persona and a model for: `worker` for its implement and resume runs. */
export type StartAgent = AgentModel['agent']

/** The agents a start chooses for, in the order a ticket meets them: its plan, its work, then its review. */
export const START_AGENTS: readonly StartAgent[] = ['planner', 'worker', 'reviewer']

/** The persona and the model picked for each of a ticket's agents as it starts; an agent left out takes its default. */
export interface StartPicks {
    /** The persona picked for each agent, by agent. */
    personas: Partial<Record<StartAgent, string>>
    /** The model picked for each agent, `provider/model[@variant]`, by agent. */
    models: Partial<Record<StartAgent, string>>
}

/** A start that picks nothing: each agent keeps the ticket's override, else config's, else canopy's default. */
export const NO_PICKS: StartPicks = { personas: {}, models: {} }

/** The start's request: each persona and model picked, set as the ticket's override with the start. */
export function startRequest(picks: StartPicks): StartRequest {
    return {
        personas: START_AGENTS.flatMap((agent) => {
            const persona = picks.personas[agent]
            return persona === undefined ? [] : [{ agent, persona }]
        }),
        models: START_AGENTS.flatMap((agent) => {
            const model = picks.models[agent]
            return model === undefined ? [] : [{ agent, model }]
        }),
    }
}

/**
 * What a start sends for `Plan it first`, checked as `plan` against `policy.plan` at `approve` (`policy`): true to ask
 * for a plan the policy would not, false to waive one it would, and null when it agrees with the policy, which leaves
 * the ticket's own setting alone. So a ticket started again under `approve`, with work on a branch, is not refused
 * for asking a plan of work already started.
 */
export function planAsked(plan: boolean, policy: boolean): boolean | null {
    return plan === policy ? null : plan
}

/** How many choices `picks` holds, a persona and a model counted apart, which the closed overrides say. */
export function pickCount(picks: StartPicks): number {
    return Object.keys(picks.personas).length + Object.keys(picks.models).length
}

/** `picks` with `agent`'s persona or model set to `value`, or dropped for the default with null. */
export function withPick(
    picks: StartPicks,
    kind: keyof StartPicks,
    agent: StartAgent,
    value: string | null,
): StartPicks {
    const { [agent]: _dropped, ...rest } = picks[kind]
    return { ...picks, [kind]: value === null ? rest : { ...rest, [agent]: value } }
}
