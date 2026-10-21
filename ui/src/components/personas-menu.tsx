import { ChevronDown } from 'lucide-react'

import type { PersonaList } from '@/api/types'
import { Button } from '@/components/ui/button'
import {
    DropdownMenu,
    DropdownMenuCheckboxItem,
    DropdownMenuContent,
    DropdownMenuItem,
    DropdownMenuSeparator,
    DropdownMenuTrigger,
} from '@/components/ui/dropdown-menu'
import { MAX_PERSONAS } from '@/lib/review-personas'

/**
 * The personas a review is written in, as `--persona NAME` given once for each: a menu of every persona a run could
 * get, any number checked, or none for `[personas] reviewer`'s, which the trigger names. A persona canopy would refuse
 * to run is shown, disabled, with why. The review request form and Settings both choose with it.
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
                    className="font-mono"
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
                    <DropdownMenuCheckboxItem
                        key={p.name}
                        className="font-mono text-xs"
                        checked={chosen.includes(p.name)}
                        disabled={p.error !== null || (chosen.length >= MAX_PERSONAS && !chosen.includes(p.name))}
                        title={p.error ?? undefined}
                        // Kept open, so several can be checked for a review in each.
                        onSelect={(event) => event.preventDefault()}
                        onCheckedChange={(checked) =>
                            onChange(checked ? [...chosen, p.name] : chosen.filter((name) => name !== p.name))
                        }
                    >
                        {p.name}
                    </DropdownMenuCheckboxItem>
                ))}
                <DropdownMenuSeparator />
                <DropdownMenuItem disabled={chosen.length === 0} onSelect={() => onChange([])}>
                    Use the default
                </DropdownMenuItem>
            </DropdownMenuContent>
        </DropdownMenu>
    )
}
