// shadcn/ui Checkbox, Radix base, ported by hand because the registry was unreachable. Its style classes are inlined
// and its per-theme overrides replaced with tokens (ui/DESIGN.md): unchecked, a well on the raised surface; checked,
// the accent with its foreground's tick.
import { CheckIcon } from 'lucide-react'
import { Checkbox as CheckboxPrimitive } from 'radix-ui'
import type { ComponentProps } from 'react'

import { cn } from '@/lib/utils'

/** A box that is on or off. Space toggles it, and so does a click on a `<label>` around it. */
function Checkbox({ className, ...props }: ComponentProps<typeof CheckboxPrimitive.Root>) {
    return (
        <CheckboxPrimitive.Root
            data-slot="checkbox"
            className={cn(
                'peer size-4 shrink-0 rounded-xs border border-border bg-surface-raised outline-none',
                'transition-[color,background-color,border-color,box-shadow]',
                'focus-visible:border-ring focus-visible:ring-3 focus-visible:ring-ring/50',
                'disabled:cursor-not-allowed disabled:opacity-50',
                'data-[state=checked]:border-accent data-[state=checked]:bg-accent',
                'data-[state=checked]:text-accent-foreground',
                className,
            )}
            {...props}
        >
            <CheckboxPrimitive.Indicator
                data-slot="checkbox-indicator"
                className="grid place-content-center text-current transition-none"
            >
                <CheckIcon className="size-3.5" />
            </CheckboxPrimitive.Indicator>
        </CheckboxPrimitive.Root>
    )
}

export { Checkbox }
