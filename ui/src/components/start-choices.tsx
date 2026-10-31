import { useQuery } from '@tanstack/react-query'
import { ChevronDown } from 'lucide-react'
import { Fragment } from 'react'

import { configModelsQuery, personasQuery } from '@/api/queries'
import type { ConfigModels, PersonaList } from '@/api/types'
import { ModelPicker } from '@/components/model-picker'
import { PersonaRadioItem } from '@/components/personas-menu'
import { Button } from '@/components/ui/button'
import {
    DropdownMenu,
    DropdownMenuContent,
    DropdownMenuItem,
    DropdownMenuRadioGroup,
    DropdownMenuSeparator,
    DropdownMenuTrigger,
} from '@/components/ui/dropdown-menu'
import { pickerModel, RUNTIME_DEFAULT, withVariant } from '@/lib/models'
import { START_AGENTS, withPick } from '@/lib/start-picks'
import type { StartAgent, StartPicks } from '@/lib/start-picks'

/**
 * The persona and the model each of a ticket's agents takes as it starts (DESIGN §13, §31): a row for its planner,
 * its worker, and its reviewer, in the order the ticket meets them, each a persona menu and a model menu
 * (`ModelPicker`) that name the default until one is picked. A pick is the ticket's override for that
 * agent, as `canopy persona KEY NAME --agent AGENT` and `canopy model KEY MODEL --agent AGENT` set it, and is sent with
 * the start, which a refused pick stops. `Use the default` drops it. The menus read their lists only once shown.
 */
export function StartChoices({
    picks,
    disabled,
    onChange,
}: {
    /** What is picked so far. */
    picks: StartPicks
    /** Whether the menus are closed to choices, as while the start is sent. */
    disabled: boolean
    /** Hears each pick, or each dropped. */
    onChange: (picks: StartPicks) => void
}) {
    const { data: personas } = useQuery(personasQuery)
    const { data: config } = useQuery(configModelsQuery)
    return (
        <fieldset
            aria-label="Persona and model overrides"
            className="grid grid-cols-[auto_auto_minmax(0,1fr)] items-center gap-x-3 gap-y-1.5"
            data-testid="start-choices"
        >
            {START_AGENTS.map((agent) => (
                <Fragment key={agent}>
                    <span className="panel-label">{agent}</span>
                    <PersonaPick
                        agent={agent}
                        persona={picks.personas[agent] ?? null}
                        personas={personas}
                        disabled={disabled}
                        onChange={(persona) => onChange(withPick(picks, 'personas', agent, persona))}
                    />
                    <ModelPick
                        agent={agent}
                        model={picks.models[agent] ?? null}
                        config={config}
                        disabled={disabled}
                        onChange={(model) => onChange(withPick(picks, 'models', agent, model))}
                    />
                </Fragment>
            ))}
        </fieldset>
    )
}

/**
 * One agent's persona as the ticket starts: a menu of every persona a run could get, each with its description, as a
 * ticket's page lists them, and `Use the default` under them. Its trigger names the persona picked, or the agent's
 * default with `(default)` after it: `[personas]`' for the agent, the reviewer's several when it names several, else
 * `canopy`.
 */
function PersonaPick({
    agent,
    persona,
    personas,
    disabled,
    onChange,
}: {
    agent: StartAgent
    persona: string | null
    personas: PersonaList | undefined
    disabled: boolean
    onChange: (persona: string | null) => void
}) {
    const defaults = personas?.personas.filter((p) => p.defaults.includes(agent)).map((p) => p.name) ?? []
    const shown = persona ?? `${defaults.length > 0 ? defaults.join(', ') : 'canopy'} (default)`
    return (
        <DropdownMenu>
            <DropdownMenuTrigger asChild>
                <Button
                    variant="outline"
                    size="xs"
                    className="justify-self-start"
                    disabled={disabled || personas === undefined}
                    aria-label={`${agent} persona: ${shown}`}
                    title={`canopy persona KEY ${persona ?? 'NAME'} --agent ${agent}`}
                    data-testid={`start-persona-${agent}`}
                >
                    {shown}
                    <ChevronDown aria-hidden />
                </Button>
            </DropdownMenuTrigger>
            <DropdownMenuContent align="start">
                <DropdownMenuRadioGroup value={persona ?? ''} onValueChange={(value) => onChange(value)}>
                    {personas?.personas.map((p) => (
                        <PersonaRadioItem key={p.name} name={p.name} description={p.description} />
                    ))}
                </DropdownMenuRadioGroup>
                <DropdownMenuSeparator />
                <DropdownMenuItem disabled={persona === null} onSelect={() => onChange(null)}>
                    Use the default
                </DropdownMenuItem>
            </DropdownMenuContent>
        </DropdownMenu>
    )
}

/**
 * One agent's model as the ticket starts: the menu a ticket's agents choose theirs with (`ModelPicker`), `default`
 * until one is picked, and config's model for the agent named after it in muted text while none is, as the review
 * request's model menu does (`ReviewModelMenu`).
 */
function ModelPick({
    agent,
    model,
    config,
    disabled,
    onChange,
}: {
    agent: StartAgent
    model: string | null
    config: ConfigModels | undefined
    disabled: boolean
    onChange: (model: string | null) => void
}) {
    const row = config?.agents.find((r) => r.agent === agent)
    const id = row?.model ?? null
    const configured = id === null ? null : withVariant(id, row?.variant ?? null)
    return (
        <span className="flex min-w-0 flex-wrap items-center gap-2">
            <ModelPicker
                current={pickerModel(model ?? configured)}
                chosen={model !== null}
                source={sourceOf(model, configured)}
                label={`${agent} model`}
                agent={agent}
                clear="Use the default"
                unchosen="default"
                title={`canopy model KEY ${model ?? 'M'} --agent ${agent}`}
                eager={model !== null}
                disabled={disabled}
                onChoose={onChange}
                testId={`start-model-${agent}`}
            />
            {/* What the default is, once config is read: the agent's in `[runtime.models]`, or the runtime's. */}
            {model === null && config !== undefined && (
                <span className="min-w-0 truncate text-xs text-muted-foreground" title={configured ?? undefined}>
                    {configured === null ? (
                        RUNTIME_DEFAULT
                    ) : (
                        <>
                            config&apos;s <span className="font-mono">{configured}</span>
                        </>
                    )}
                </span>
            )}
        </span>
    )
}

/** Where the model chosen now comes from, after its id in the menu: this start, config, or nothing. */
function sourceOf(model: string | null, configured: string | null): string {
    if (model !== null) {
        return 'this start'
    }
    return configured === null ? 'nothing sets one' : '[runtime.models]'
}
