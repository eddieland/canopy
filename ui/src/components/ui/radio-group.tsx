// shadcn/ui RadioGroup, Radix base, ported by hand because the registry was unreachable; see checkbox.tsx. Its style
// classes are inlined and its per-theme overrides replaced with tokens (ui/DESIGN.md). Its item is a whole row rather
// than shadcn's round well: the caller draws what the row holds and how it shows being picked.
import { RadioGroup as RadioGroupPrimitive } from 'radix-ui'
import type { ComponentProps } from 'react'

import { cn } from '@/lib/utils'

/**
 * A choice of one among options too long for a segmented control, a column of them. Radix gives it the `radiogroup`
 * role and each item `radio`: the arrow keys move the pick between them, and Tab leaves the group.
 */
function RadioGroup({ className, ...props }: ComponentProps<typeof RadioGroupPrimitive.Root>) {
    return <RadioGroupPrimitive.Root data-slot="radio-group" className={cn('grid gap-0.5', className)} {...props} />
}

/**
 * One option in a RadioGroup, a row that is the radio, so a click anywhere on it picks it. Its children are what it
 * shows, picked or not, and name it unless an `aria-label` does.
 */
function RadioGroupRow({ className, ...props }: ComponentProps<typeof RadioGroupPrimitive.Item>) {
    return (
        <RadioGroupPrimitive.Item
            data-slot="radio-group-row"
            className={cn('disabled:cursor-not-allowed', className)}
            {...props}
        />
    )
}

export { RadioGroup, RadioGroupRow }
