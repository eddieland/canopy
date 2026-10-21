import { useMutation, useQueryClient } from '@tanstack/react-query'
import { ChevronDown } from 'lucide-react'
import { useState } from 'react'

import { chooseTicketPersona } from '@/api/mutations'
import { keys } from '@/api/queries'
import type { AgentPersona } from '@/api/types'
import { Field, Fields } from '@/components/fields'
import { Notice } from '@/components/notice'
import { Button } from '@/components/ui/button'
import {
    DropdownMenu,
    DropdownMenuContent,
    DropdownMenuItem,
    DropdownMenuRadioGroup,
    DropdownMenuRadioItem,
    DropdownMenuSeparator,
    DropdownMenuTrigger,
} from '@/components/ui/dropdown-menu'
import { PERSONA_SOURCES, personaText } from '@/lib/outcomes'

/** A choice the menu makes: a persona's name, or null to clear the ticket's override. */
interface Choice {
    /** The agent the choice is for. */
    agent: AgentPersona['agent']
    /** The persona's name, or null to clear the override. */
    persona: string | null
}

/**
 * The persona each of a ticket's agents writes in at its next run (DESIGN §31), and where that comes from: a row for
 * its workers, its planner, and its reviewer, each a menu that sets the ticket's override to one of `names`, or clears
 * it, as `canopy persona KEY NAME --agent AGENT` and `--clear` do. A persona the operator chose for the agent's next
 * run alone, with `--next`, is named under it, and so are the reviewer's personas when `[personas] reviewers` has a
 * review in each. A run whose persona's file has gone is refused, not run in another voice: its row says why, in the
 * failure color.
 */
export function TicketPersonas({
    ticketKey,
    personas,
    names,
    className,
}: {
    ticketKey: string
    personas: readonly AgentPersona[]
    names: readonly string[]
    className?: string
}) {
    const client = useQueryClient()
    const [said, setSaid] = useState<string | null>(null)
    const choose = useMutation({
        mutationFn: ({ agent, persona }: Choice) => chooseTicketPersona(ticketKey, agent, persona),
        onSuccess: (now) => {
            setSaid(personaText(ticketKey, now))
            void client.invalidateQueries({ queryKey: keys.ticket(ticketKey) })
        },
    })
    if (personas.length === 0) {
        return null
    }
    return (
        <div className={className} data-testid="ticket-personas">
            <Fields className="pb-1.5">
                {personas.map((p) => (
                    <Field key={p.agent} label={`${p.agent} persona`}>
                        <span className="flex flex-wrap items-baseline gap-x-2">
                            <PersonaMenu
                                current={p}
                                names={names}
                                disabled={choose.isPending}
                                onChoose={(persona) => choose.mutate({ agent: p.agent, persona })}
                            />
                            <span className="text-xs text-muted-foreground">{PERSONA_SOURCES[p.source]}</span>
                        </span>
                        {p.several.length > 0 && (
                            <span className="block text-xs text-muted-foreground">
                                One review each in: <span className="font-mono">{p.several.join(', ')}</span>
                            </span>
                        )}
                        {p.once !== null && (
                            <span className="block text-xs text-muted-foreground">
                                Its next run alone: <span className="font-mono">{p.once}</span>
                            </span>
                        )}
                        {p.error !== null && (
                            <span className="block text-xs text-status-failed">Its next run is refused: {p.error}</span>
                        )}
                    </Field>
                ))}
            </Fields>
            <Notice error={choose.error} className="px-3 pb-3">
                {said}
            </Notice>
        </div>
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
                        <DropdownMenuRadioItem key={name} value={name} className="font-mono text-xs">
                            {name}
                        </DropdownMenuRadioItem>
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
