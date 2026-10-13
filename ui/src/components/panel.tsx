import { Link, useMatchRoute } from '@tanstack/react-router'
import { ChevronRight } from 'lucide-react'
import { Children, type ComponentProps, type ReactNode } from 'react'

import { useSection } from '@/hooks/use-section'
import { SECTION_LABEL, SECTION_TEXT } from '@/lib/sections'
import { cn } from '@/lib/utils'

/**
 * A page's title block: the trail to it, the title, any chips that qualify it, and one line of description. The trail
 * starts at the page's section, in the section's color (the accent on a page in no section). On the section's own list
 * that is all it is; on any page under it, the section links to its list, then come `parents`, plain router `Link`s
 * the trail styles, to the pages between it and this one, and every step ends in a chevron. The title is the trail's
 * last step, so the trail never repeats it.
 */
export function PageHeader({
    title,
    parents,
    root,
    chips,
    children,
}: {
    /** The page's name. */
    title: ReactNode
    /**
     * Links to the pages between the section and this one, outermost first, such as a chore run's chore. Each takes
     * `activeOptions={{ exact: true }}`, so a page under it does not mark it the current one.
     */
    parents?: ReactNode
    /** The trail's first step on a page in no section, such as search; a page in a section takes its name. */
    root?: string
    /** `Chip`s beside the title that qualify the page, such as `private`. */
    chips?: ReactNode
    /** One line of description. */
    children?: ReactNode
}) {
    const section = useSection()
    const matchRoute = useMatchRoute()
    const steps = Children.toArray(parents)
    // On a section's own list the trail is just its name; under it, every step links up and ends in a chevron.
    const atSection = section !== undefined && steps.length === 0 && matchRoute({ to: section }) !== false
    const linked = section !== undefined && !atSection
    const end = linked && <ChevronRight aria-hidden className="size-3 shrink-0" />
    return (
        <header className="flex flex-col gap-1">
            <nav aria-label="Breadcrumb">
                <ol className="flex flex-wrap items-center gap-1 panel-label">
                    <li
                        className={cn(
                            'flex items-center gap-1',
                            section === undefined ? 'text-accent' : SECTION_TEXT[section],
                        )}
                    >
                        {section === undefined ? (
                            root
                        ) : linked ? (
                            <Link
                                to={section}
                                activeOptions={{ exact: true }}
                                className="underline-offset-4 hover:underline"
                            >
                                {SECTION_LABEL[section]}
                            </Link>
                        ) : (
                            SECTION_LABEL[section]
                        )}
                        {end}
                    </li>
                    {steps.map((step, i) => (
                        // The parents never reorder: their place is their identity.
                        // oxlint-disable-next-line react/no-array-index-key
                        <li
                            key={i}
                            className={cn(
                                'flex min-w-0 items-center gap-1 normal-case',
                                '[&_a]:truncate [&_a]:underline-offset-4 [&_a:hover]:text-foreground',
                                '[&_a:hover]:underline',
                            )}
                        >
                            {step}
                            {end}
                        </li>
                    ))}
                </ol>
            </nav>
            <div className="flex flex-wrap items-center gap-x-2 gap-y-1">
                <h1 className="text-xl font-semibold tracking-tight">{title}</h1>
                {chips}
            </div>
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
