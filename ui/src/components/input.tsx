import { Search, X } from 'lucide-react'
import type { ComponentProps, ReactNode } from 'react'

import { Button } from '@/components/ui/button'
import { cn } from '@/lib/utils'

const FIELD = [
    'w-full rounded-md border bg-surface-raised px-2.5 text-sm text-foreground outline-none',
    'placeholder:text-muted-foreground focus-visible:border-ring focus-visible:ring-3 focus-visible:ring-ring/50',
    'disabled:opacity-50',
]

// A search field's two sizes (ui/DESIGN.md, "Primitives"): in the rail or over a list, and in a panel's own line,
// beside `text-xs` data. Its icon follows its text's size, as every icon does. Written out so Tailwind finds them.
const SEARCH_SIZE = {
    default: { field: 'h-8 px-2.5', input: 'text-sm', icon: 'size-4' },
    sm: { field: 'h-7 px-2', input: 'text-xs', icon: 'size-3' },
} as const

/** A one-line text field on the raised surface, at one height everywhere: a form's, beside its default buttons. */
export function Input({ className, ...props }: ComponentProps<'input'>) {
    return <input className={cn(FIELD, 'h-9', className)} {...props} />
}

/** A multi-line text field on the raised surface. */
export function Textarea({ className, ...props }: ComponentProps<'textarea'>) {
    return <textarea className={cn(FIELD, 'min-h-24 py-2 leading-relaxed', className)} {...props} />
}

/**
 * A search field: a magnifier, the field, what it says at its end (`end`, such as how many lines hold the query), then
 * while it holds text a ghost clear button, named `clearLabel`, that calls `onClear`; while empty, `idle` (such as a
 * keycap) in its place. It is the field alone: the caller puts it in a `<search>` landmark, or a form in one. The rest
 * of its props are the input's.
 */
export function SearchField({
    size = 'default',
    value,
    onClear,
    clearLabel,
    end,
    idle,
    className,
    ...props
}: Omit<ComponentProps<'input'>, 'size' | 'type' | 'value' | 'className'> & {
    /** `default` in the rail or over a list; `sm` in a panel's line of `text-xs` data. */
    size?: keyof typeof SEARCH_SIZE
    /** What the field holds. */
    value: string
    /** Empties the field, from its clear button. */
    onClear: () => void
    /** The clear button's name, for a screen reader. */
    clearLabel: string
    /** What sits at the field's end, before the clear button. */
    end?: ReactNode
    /** What takes the clear button's place while the field is empty. */
    idle?: ReactNode
    /** Classes for the field's box, such as its width. */
    className?: string
}) {
    const sized = SEARCH_SIZE[size]
    return (
        <div
            className={cn(
                'flex items-center gap-2 rounded-md border bg-surface-raised',
                'focus-within:border-ring focus-within:ring-3 focus-within:ring-ring/50',
                sized.field,
                className,
            )}
        >
            <Search aria-hidden className={cn('shrink-0 text-muted-foreground', sized.icon)} />
            <input
                type="search"
                value={value}
                className={cn(
                    'min-w-0 flex-1 bg-transparent text-foreground outline-none',
                    'placeholder:text-muted-foreground [&::-webkit-search-cancel-button]:hidden',
                    sized.input,
                )}
                {...props}
            />
            {end}
            {value === '' ? (
                idle
            ) : (
                <Button
                    type="button"
                    variant="ghost"
                    size="icon-xs"
                    aria-label={clearLabel}
                    onClick={onClear}
                    className="hover:bg-muted"
                >
                    <X aria-hidden />
                </Button>
            )}
        </div>
    )
}
