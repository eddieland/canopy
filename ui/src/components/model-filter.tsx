import { useState } from 'react'

import { PickerButton, PickerItem, PickerList } from '@/components/picker'
import { CommandSeparator } from '@/components/ui/command'
import { Popover } from '@/components/ui/popover'

// The item that stands for every model: words no model's id has, since an id holds no space.
const EVERY = 'every model'

/**
 * A filter by the model that ran a run, as the repository picker filters by repository (DESIGN.md): a button saying
 * the model chosen, or `every model`, quiet, while it narrows nothing, opening `models` whole, as `provider/model`, in
 * a list a field narrows, under `every model`, which clears it. Picking one sets it and closes the list.
 */
export function ModelFilter({
    models,
    chosen,
    onChoose,
}: {
    /** The models to offer, sorted, the one chosen among them. */
    models: readonly string[]
    /** The model chosen; undefined filters nothing. */
    chosen: string | undefined
    /** Hears the model picked, or undefined for every model. */
    onChoose: (model: string | undefined) => void
}) {
    const [open, setOpen] = useState(false)
    const summary = chosen ?? EVERY

    function choose(model: string | undefined) {
        setOpen(false)
        onChoose(model)
    }

    return (
        <Popover open={open} onOpenChange={setOpen}>
            <PickerButton label={`Filter by model: ${summary}`} quiet={chosen === undefined}>
                {summary}
            </PickerButton>
            <PickerList find="Find a model" label="Models" empty="no model has that name">
                <PickerItem value={EVERY} checked={chosen === undefined} onSelect={() => choose(undefined)}>
                    {EVERY}
                </PickerItem>
                <CommandSeparator />
                {models.map((m) => (
                    <PickerItem key={m} value={m} checked={m === chosen} onSelect={() => choose(m)}>
                        {m}
                    </PickerItem>
                ))}
            </PickerList>
        </Popover>
    )
}
