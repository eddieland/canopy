import { useQuery } from '@tanstack/react-query'
import { ChevronDown } from 'lucide-react'

import { personasQuery } from '@/api/queries'
import type { AgentPersona } from '@/api/types'
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
import type { PersonaChoices } from '@/hooks/use-persona-choices'
import { PERSONA_SOURCES } from '@/lib/outcomes'

/**
 * The persona one of a ticket's agents writes in at its next run, and where that comes from: a menu that sets the
 * ticket's override to one of `names`, or clears it, through `choices`. A persona the operator chose for the agent's
 * next run alone, with `--next`, is named under it, and so are the reviewer's personas when `[personas] reviewers` has
 * a review in each. The menu lists every persona with its description, as the review request's does (`PersonasMenu`).
 * A run whose persona's file has gone is refused, not run in another voice: its row says why, in the failure color.
 */
export function PersonaChoice({
    current,
    names,
    choices,
}: {
    current: AgentPersona
    names: readonly string[]
    choices: PersonaChoices
}) {
    return (
        <>
            <span className="flex flex-wrap items-baseline gap-x-2">
                <PersonaMenu
                    current={current}
                    names={names}
                    disabled={choices.pending}
                    onChoose={(persona) => choices.choose(current.agent, persona)}
                />
                <span className="text-xs text-muted-foreground">{PERSONA_SOURCES[current.source]}</span>
            </span>
            {current.several.length > 0 && (
                <span className="block text-xs text-muted-foreground">
                    One review each in: <span className="font-mono">{current.several.join(', ')}</span>
                </span>
            )}
            {current.once !== null && (
                <span className="block text-xs text-muted-foreground">
                    Its next run alone: <span className="font-mono">{current.once}</span>
                </span>
            )}
            {current.error !== null && (
                <span className="block text-xs text-status-failed">Its next run is refused: {current.error}</span>
            )}
        </>
    )
}

function PersonaMenu({
    current,
    names,
    disabled,
    onChoose,
}: {
    current: AgentPersona
    names: readonly string[]
    disabled: boolean
    onChoose: (persona: string | null) => void
}) {
    // A persona whose file has gone is still the one chosen: it stays in the list so the menu shows it checked.
    const choices = names.includes(current.persona) ? names : [...names, current.persona]
    // Each one's description, as the review request's menu shows it: none until the list is read, or for a gone one.
    const { data: listed } = useQuery(personasQuery)
    const described = new Map(listed?.personas.map((p) => [p.name, p.description]))
    return (
        <DropdownMenu>
            <DropdownMenuTrigger asChild>
                <Button
                    variant="outline"
                    size="xs"
                    disabled={disabled}
                    aria-label={`${current.agent} persona: ${current.persona}`}
                >
                    {current.persona}
                    <ChevronDown aria-hidden />
                </Button>
            </DropdownMenuTrigger>
            <DropdownMenuContent align="start">
                <DropdownMenuRadioGroup
                    value={current.source === 'ticket' ? current.persona : ''}
                    onValueChange={(value) => onChoose(value)}
                >
                    {choices.map((name) => (
                        <PersonaRadioItem key={name} name={name} description={described.get(name) ?? null} />
                    ))}
                </DropdownMenuRadioGroup>
                <DropdownMenuSeparator />
                <DropdownMenuItem disabled={current.source !== 'ticket'} onSelect={() => onChoose(null)}>
                    Clear the override
                </DropdownMenuItem>
            </DropdownMenuContent>
        </DropdownMenu>
    )
}
