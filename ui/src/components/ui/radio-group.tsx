// shadcn/ui RadioGroup, Radix base, ported by hand because the registry was unreachable; see checkbox.tsx. Its style
// classes are inlined and its per-theme overrides replaced with tokens (ui/DESIGN.md): a round well on the raised
// surface, its border and a dot in the accent when picked.
import { CircleIcon } from 'lucide-react'
import { RadioGroup as RadioGroupPrimitive } from 'radix-ui'
import type { ComponentProps } from 'react'

import { cn } from '@/lib/utils'

/**
 * A choice of one among options too long for a segmented control, a column of them. Radix gives it the `radiogroup`
 * role and each item `radio`: the arrow keys move the pick between them, and Tab leaves the group.
 */
function RadioGroup({ className, ...props }: ComponentProps<typeof RadioGroupPrimitive.Root>) {
    return <RadioGroupPrimitive.Root data-slot="radio-group" className={cn('grid gap-2', className)} {...props} />
}

/** One option in a RadioGroup, named by a `<label>` whose `htmlFor` is its `id`, so a click on the words picks it. */
function RadioGroupItem({ className, ...props }: ComponentProps<typeof RadioGroupPrimitive.Item>) {
    return (
        <RadioGroupPrimitive.Item
            data-slot="radio-group-item"
            className={cn(
                'aspect-square size-4 shrink-0 rounded-full border border-border bg-surface-raised text-accent',
                'outline-none transition-[color,border-color,box-shadow]',
                'focus-visible:border-ring focus-visible:ring-3 focus-visible:ring-ring/50',
                'disabled:cursor-not-allowed disabled:opacity-50',
                'data-[state=checked]:border-accent',
                className,
            )}
            {...props}
        >
            <RadioGroupPrimitive.Indicator
                data-slot="radio-group-indicator"
                className="relative flex items-center justify-center"
            >
                <CircleIcon className="absolute top-1/2 left-1/2 size-2 -translate-1/2 fill-current" />
            </RadioGroupPrimitive.Indicator>
        </RadioGroupPrimitive.Item>
    )
}

export { RadioGroup, RadioGroupItem }
