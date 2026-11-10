// shadcn/ui Table, ported by hand as button.tsx was: its parts and slots, styled as canopy's report tables are
// (ui/DESIGN.md, "A table of figures"). canopy's tables draw no rule between rows and no hover, so shadcn's go.
import type { ComponentProps } from 'react'

import { cn } from '@/lib/utils'

/** A table of figures: its own width, its cells collapsed together. A `PanelScroll` around it scrolls it. */
function Table({ className, ...props }: ComponentProps<'table'>) {
    return <table data-slot="table" className={cn('border-collapse text-sm', className)} {...props} />
}

/** The table's head rows. */
function TableHeader({ className, ...props }: ComponentProps<'thead'>) {
    return <thead data-slot="table-header" className={className} {...props} />
}

/** The table's rows, or a group of them. */
function TableBody({ className, ...props }: ComponentProps<'tbody'>) {
    return <tbody data-slot="table-body" className={cn('text-xs', className)} {...props} />
}

/** A row. */
function TableRow({ className, ...props }: ComponentProps<'tr'>) {
    return <tr data-slot="table-row" className={className} {...props} />
}

/** A column's head, in `panel-label` type. */
function TableHead({ className, ...props }: ComponentProps<'th'>) {
    return (
        <th
            data-slot="table-head"
            className={cn('pb-1.5 panel-label font-normal whitespace-nowrap', className)}
            {...props}
        />
    )
}

/** A cell. */
function TableCell({ className, ...props }: ComponentProps<'td'>) {
    return <td data-slot="table-cell" className={cn('py-0.5', className)} {...props} />
}

export { Table, TableBody, TableCell, TableHead, TableHeader, TableRow }
