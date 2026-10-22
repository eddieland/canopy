import { ChevronDown } from 'lucide-react'
import { useId } from 'react'

import type { PersonaChoice, PersonaList } from '@/api/types'
import { Button } from '@/components/ui/button'
import {
    DropdownMenu,
    DropdownMenuCheckboxItem,
    DropdownMenuContent,
    DropdownMenuItem,
    DropdownMenuRadioItem,
    DropdownMenuSeparator,
    DropdownMenuTrigger,
} from '@/components/ui/dropdown-menu'
import { MAX_PERSONAS } from '@/lib/review-personas'

/**
 * The personas a review is written in, as `--persona NAME` given once for each: a menu of every persona a run could
 * get, each with its description (`PersonaCheckboxItem`), any number checked, or none for `[personas] reviewer`'s,
 * which the trigger names. A persona canopy would refuse to run is shown, disabled, with why. The review request form,
 * a PR's page, and Settings all choose with it.
 */
export function PersonasMenu({
    personas,
    chosen,
    disabled,
    onChange,
    title,
    testId,
}: {
    personas: PersonaList | undefined
    chosen: readonly string[]
    disabled: boolean
    onChange: (chosen: readonly string[]) => void
    title?: string
    testId: string
}) {
    const shown = chosen.length > 0 ? chosen.join(', ') : `${personas?.reviewer ?? 'canopy'} (default)`
    return (
        <DropdownMenu>
            <DropdownMenuTrigger asChild>
                <Button
                    variant="outline"
                    size="xs"
                    disabled={disabled || personas === undefined}
                    aria-label={`Persona: ${shown}`}
                    title={title}
                    data-testid={testId}
                >
                    {shown}
                    <ChevronDown aria-hidden />
                </Button>
            </DropdownMenuTrigger>
            <DropdownMenuContent align="start">
                {personas?.personas.map((p) => (
                    <PersonaCheckboxItem
                        key={p.name}
                        persona={p}
                        checked={chosen.includes(p.name)}
                        disabled={p.error !== null || (chosen.length >= MAX_PERSONAS && !chosen.includes(p.name))}
                        onCheckedChange={(checked) =>
                            onChange(checked ? [...chosen, p.name] : chosen.filter((name) => name !== p.name))
                        }
                    />
                ))}
                <DropdownMenuSeparator />
                <DropdownMenuItem disabled={chosen.length === 0} onSelect={() => onChange([])}>
                    Use the default
                </DropdownMenuItem>
            </DropdownMenuContent>
        </DropdownMenu>
    )
}

/**
 * One persona in a menu that checks several, kept open on a click so several can be checked for a review in each. Its
 * name is the item's, its description under it (`PersonaLabel`); one canopy would refuse says why on hover.
 */
export function PersonaCheckboxItem({
    persona,
    checked,
    disabled,
    onCheckedChange,
}: {
    persona: PersonaChoice
    checked: boolean
    disabled: boolean
    onCheckedChange: (checked: boolean) => void
}) {
    const id = useId()
    return (
        <DropdownMenuCheckboxItem
            className="items-start"
            checked={checked}
            disabled={disabled}
            title={persona.error ?? undefined}
            aria-describedby={persona.description === null ? undefined : id}
            onSelect={(event) => event.preventDefault()}
            onCheckedChange={onCheckedChange}
        >
            <PersonaLabel name={persona.name} description={persona.description} id={id} />
        </DropdownMenuCheckboxItem>
    )
}

/** One persona in a menu that picks one, as a ticket's agent's is: its name the item's, its description under it. */
export function PersonaRadioItem({ name, description }: { name: string; description: string | null }) {
    const id = useId()
    return (
        <DropdownMenuRadioItem
            value={name}
            className="items-start"
            aria-describedby={description === null ? undefined : id}
        >
            <PersonaLabel name={name} description={description} id={id} />
        </DropdownMenuRadioItem>
    )
}

/**
 * A persona as every persona menu lists it (ui/DESIGN.md, "A choice of persona"): its name in monospace, and under it,
 * in muted body text, its description, which says what the persona is: its file's own, else its opening sentence.
 * The description is the item's accessible description, not part of its name.
 */
function PersonaLabel({ name, description, id }: { name: string; description: string | null; id: string }) {
    return (
        <span className="flex min-w-0 flex-col gap-0.5">
            <span className="font-mono text-xs">{name}</span>
            {description !== null && (
                <span id={id} aria-hidden className="max-w-80 text-xs text-muted-foreground">
                    {description}
                </span>
            )}
        </span>
    )
}
