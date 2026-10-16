// shadcn/ui Switch, Radix base, ported by hand because the registry was unreachable; see checkbox.tsx. Reshaped into
// the one look canopy uses, a wall light switch (ui/DESIGN.md, Fun): a plate on the raised surface with a lever in it,
// up when off, down and in the accent when on. shadcn's sliding pill is left out until a second switch needs it.
import { Switch as SwitchPrimitive } from 'radix-ui'
import type { ComponentProps } from 'react'

import { cn } from '@/lib/utils'

/** A switch that is on or off. Radix gives it the `switch` role and keeps `aria-checked` in step; Space flips it. */
function Switch({ className, ...props }: ComponentProps<typeof SwitchPrimitive.Root>) {
    return (
        <SwitchPrimitive.Root
            data-slot="switch"
            className={cn(
                'peer inline-flex h-7 w-5 shrink-0 flex-col items-center rounded-xs border border-border',
                'bg-surface-raised px-1 py-1.5 outline-none transition-[border-color,box-shadow]',
                'focus-visible:border-ring focus-visible:ring-3 focus-visible:ring-ring/50',
                'disabled:cursor-not-allowed disabled:opacity-50',
                className,
            )}
            {...props}
        >
            <SwitchPrimitive.Thumb
                data-slot="switch-thumb"
                className={cn(
                    'pointer-events-none block h-2 w-2.5 rounded-xs bg-muted-foreground',
                    'transition-[translate,background-color]',
                    'data-[state=checked]:translate-y-1.5 data-[state=checked]:bg-accent',
                )}
            />
        </SwitchPrimitive.Root>
    )
}

export { Switch }
