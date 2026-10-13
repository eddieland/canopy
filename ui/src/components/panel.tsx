import type { ComponentProps, ReactNode } from 'react'

import { useSection } from '@/hooks/use-section'
import { SECTION_TEXT } from '@/lib/sections'
import { cn } from '@/lib/utils'

/**
 * A page's title block: a small panel label in its section's color (the accent on a page in no section), the title,
 * and one line of description.
 */
export function PageHeader({ label, title, children }: { label: string; title: ReactNode; children?: ReactNode }) {
    const section = useSection()
    return (
        <header className="flex flex-col gap-1">
            <span className={cn('panel-label', section === undefined ? 'text-accent' : SECTION_TEXT[section])}>
                {label}
            </span>
            <h1 className="text-xl font-semibold tracking-tight">{title}</h1>
            {children && <p className="max-w-prose text-sm text-muted-foreground">{children}</p>}
        </header>
    )
}

/** A bordered panel on the surface color. Give it a fixed or minimum height when its content is async. */
export function Panel({ className, ...props }: ComponentProps<'section'>) {
    return <section className={cn('rounded-md border bg-surface', className)} {...props} />
}

/** A panel's title row: a label on the left, anything on the right. */
export function PanelHeader({ label, children }: { label: string; children?: ReactNode }) {
    return (
        <div className="flex h-9 items-center justify-between gap-3 border-b px-3">
            <span className="panel-label">{label}</span>
            {children}
        </div>
    )
}

/**
 * A panel's list that grows without bound (decisions, runs, findings): past a fixed height it scrolls inside the panel,
 * so the panels under it stay in reach. A focusable region, so the keyboard scrolls it too; `label` names it.
 */
export function PanelScroll({ label, className, ...props }: ComponentProps<'section'> & { label: string }) {
    return (
        <section
            aria-label={label}
            // A scrolling region takes focus so the keyboard can scroll it (axe's scrollable-region-focusable).
            // oxlint-disable-next-line jsx-a11y/no-noninteractive-tabindex
            tabIndex={0}
            className={cn('panel-scroll max-h-[28rem] focus-visible:-outline-offset-2', className)}
            {...props}
        />
    )
}

/** Where a feature will go: reserves its space so the page does not move when the feature lands. */
export function Placeholder({ className, children }: { className?: string; children: ReactNode }) {
    return (
        <div
            className={cn(
                'grid min-h-72 place-items-center p-6 text-center font-mono text-xs text-muted-foreground',
                className,
            )}
        >
            {children}
        </div>
    )
}
