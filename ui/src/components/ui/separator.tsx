// shadcn/ui Separator, Radix base (components.json), ported by hand; see button.tsx.
import { Separator as SeparatorPrimitive } from 'radix-ui'
import type { ComponentProps } from 'react'

import { cn } from '@/lib/utils'

/** A thin rule between groups. Decorative by default, so assistive technology skips it. */
function Separator({
    className,
    orientation = 'horizontal',
    decorative = true,
    ...props
}: ComponentProps<typeof SeparatorPrimitive.Root>) {
    return (
        <SeparatorPrimitive.Root
            data-slot="separator"
            decorative={decorative}
            orientation={orientation}
            className={cn(
                'shrink-0 bg-border',
                'data-[orientation=horizontal]:h-px data-[orientation=horizontal]:w-full',
                'data-[orientation=vertical]:w-px data-[orientation=vertical]:self-stretch',
                className,
            )}
            {...props}
        />
    )
}

export { Separator }
