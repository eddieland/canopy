import { useState } from 'react'

import { PickerButton, PickerItem, PickerList } from '@/components/picker'
import { CommandSeparator } from '@/components/ui/command'
import { Popover } from '@/components/ui/popover'

/**
 * A filter by one of a list's names, as the repository picker filters by repository (DESIGN.md): a button saying the
 * name chosen, or `every NOUN`, quiet, while it narrows nothing, opening `choices` whole in a list a field narrows,
 * under `every NOUN`, which clears it. Picking one sets it and closes the list. The runs page filters by model with
 * it, and the reviews page by author.
 */
export function ChoiceFilter({
    noun,
    find,
    label,
    choices,
    chosen,
    onChoose,
}: {
    /** What a choice is, in the singular: `model`, `author`. */
    noun: string
    /** What the field that narrows the list is named: `Find a model`. */
    find: string
    /** What the list is named: `Models`. */
    label: string
    /** The names to offer, sorted, the one chosen among them. */
    choices: readonly string[]
    /** The name chosen; undefined filters nothing. */
    chosen: string | undefined
    /** Hears the name picked, or undefined for every one. */
    onChoose: (choice: string | undefined) => void
}) {
    const [open, setOpen] = useState(false)
    // The item that stands for every choice: words no name offered has, since a model's id and a login hold no space.
    const every = `every ${noun}`
    const summary = chosen ?? every

    function choose(choice: string | undefined) {
        setOpen(false)
        onChoose(choice)
    }

    return (
        <Popover open={open} onOpenChange={setOpen}>
            <PickerButton label={`Filter by ${noun}: ${summary}`} quiet={chosen === undefined}>
                {summary}
            </PickerButton>
            <PickerList find={find} label={label} empty={`no ${noun} has that name`}>
                <PickerItem value={every} checked={chosen === undefined} onSelect={() => choose(undefined)}>
                    {every}
                </PickerItem>
                <CommandSeparator />
                {choices.map((c) => (
                    <PickerItem key={c} value={c} checked={c === chosen} onSelect={() => choose(c)}>
                        {c}
                    </PickerItem>
                ))}
            </PickerList>
        </Popover>
    )
}
