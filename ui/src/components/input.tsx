import type { ComponentProps } from 'react'

import { cn } from '@/lib/utils'

const FIELD = [
    'w-full rounded-md border bg-surface-raised px-2.5 text-sm text-foreground outline-none',
    'placeholder:text-muted-foreground focus-visible:border-ring focus-visible:ring-3 focus-visible:ring-ring/50',
    'disabled:opacity-50',
]

/** A one-line text field on the raised surface. */
export function Input({ className, ...props }: ComponentProps<'input'>) {
    return <input className={cn(FIELD, 'h-9', className)} {...props} />
}

/** A multi-line text field on the raised surface. */
export function Textarea({ className, ...props }: ComponentProps<'textarea'>) {
    return <textarea className={cn(FIELD, 'min-h-24 py-2 leading-relaxed', className)} {...props} />
}
