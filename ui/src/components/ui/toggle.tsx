// shadcn/ui Toggle, Radix base, ported by hand; see button.tsx. Trimmed to the one look canopy uses, a ghost button
// that stays raised while it is on, as an open disclosure's button does. Its sizes are Button's, so it sits in a row
// of them; shadcn's own variants and sizes are left out until a second look needs them.
import type { VariantProps } from 'class-variance-authority'
import { Toggle as TogglePrimitive } from 'radix-ui'
import type { ComponentProps } from 'react'

import { buttonVariants } from '@/components/ui/button'
import { cn } from '@/lib/utils'

/**
 * A button that is on or off, such as a view's Pretty. Radix keeps `aria-pressed` and `data-state` in step with
 * `pressed`, and Space and Enter flip it.
 */
function Toggle({
    className,
    size = 'default',
    ...props
}: ComponentProps<typeof TogglePrimitive.Root> & Pick<VariantProps<typeof buttonVariants>, 'size'>) {
    return (
        <TogglePrimitive.Root
            data-slot="toggle"
            data-size={size}
            className={cn(
                buttonVariants({ variant: 'ghost', size }),
                'data-[state=on]:bg-surface-raised data-[state=on]:text-foreground',
                className,
            )}
            {...props}
        />
    )
}

export { Toggle }
