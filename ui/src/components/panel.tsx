import { useQuery } from '@tanstack/react-query'
import { Link, useMatchRoute } from '@tanstack/react-router'
import { ChevronRight } from 'lucide-react'
import { Children } from 'react'
import type { ComponentProps, ReactNode } from 'react'

import { attentionQuery } from '@/api/queries'
import { useSection } from '@/hooks/use-section'
import { blocking } from '@/lib/attention'
import { pageTitle } from '@/lib/page-title'
import { SECTION_LABEL, SECTION_TEXT } from '@/lib/sections'
import { cn, isBlank } from '@/lib/utils'

/**
 * A page's title block: the trail to it, the title, any chips that qualify it, one line of description, and the page
 * subject's links out. The trail starts at the page's section, in the section's color (the accent on a page in no
 * section). On the section's own list that is all it is; on any page under it, the section links to its list, then
 * come `parents`, plain router `Link`s the trail styles, to the pages between it and this one, and every step ends in
 * a chevron. The title is the trail's last step, so the trail never repeats it. The header also names the browser
 * tab (`pageTitle`): `tab`, or the title when it is plain text, after the count of attention items that block work.
 */
export function PageHeader({
    title,
    tab,
    parents,
    root,
    chips,
    links,
    children,
}: {
    /** The page's name. */
    title: ReactNode
    /** The page's name in the browser tab, when `title` is not plain text or the tab wants other words. */
    tab?: string
    /**
     * Links to the pages between the section and this one, outermost first, such as a chore run's chore. Each takes
     * `activeOptions={{ exact: true }}`, so a page under it does not mark it the current one.
     */
    parents?: ReactNode
    /** The trail's first step on a page in no section, such as search; a page in a section takes its name. */
    root?: string
    /** `Chip`s beside the title that qualify the page, such as `private`. */
    chips?: ReactNode
    /** The page subject's links out, under the description, such as a ticket's `TicketLinks`. */
    links?: ReactNode
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
    const attention = useQuery(attentionQuery).data?.filter(blocking).length
    return (
        <header className="flex flex-col gap-1">
            {/* React puts it in the document's head, ahead of index.html's, so it names the tab. */}
            <title>{pageTitle(tab ?? (typeof title === 'string' ? title : undefined), attention)}</title>
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
                <h1 className="min-w-0 text-xl font-semibold tracking-tight break-words">{title}</h1>
                {chips}
            </div>
            {!isBlank(children) && (
                // Balanced, so a two-line description splits evenly rather than leaving a word or two on its last line,
                // and a command in it never breaks across lines.
                <p className="max-w-3xl text-sm text-balance text-muted-foreground [&_code]:whitespace-nowrap">
                    {children}
                </p>
            )}
            {links}
        </header>
    )
}

/** A bordered panel on the surface color. Give it a fixed or minimum height when its content is async. */
export function Panel({ className, ...props }: ComponentProps<'section'>) {
    return <section className={cn('rounded-md border bg-surface', className)} {...props} />
}

/**
 * A panel's title row: a label on the left, anything on the right. Half a step toward `surface-raised`, with its label
 * in `foreground`, so it reads as the head of the rows under it; half, so a ghost button's hover in it still shows.
 */
export function PanelHeader({ label, children }: { label: string; children?: ReactNode }) {
    return (
        <div
            className={cn(
                'flex h-9 items-center justify-between gap-3 border-b bg-surface-raised/50 px-3',
                // Inside the panel's border, so a radius a pixel smaller than the panel's.
                'first:rounded-t-[calc(var(--radius-md)-1px)]',
            )}
        >
            <span className="panel-label font-medium text-foreground">{label}</span>
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
