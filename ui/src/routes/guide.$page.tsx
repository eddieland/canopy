import { createFileRoute, Link, notFound } from '@tanstack/react-router'
import { ChevronDown } from 'lucide-react'

import { GuideLines, GuideText } from '@/components/guide-text'
import { PageHeader } from '@/components/panel'
import { Collapsible, CollapsibleContent, CollapsibleTrigger } from '@/components/ui/collapsible'
import { GUIDE_GROUPS, guideNeighbours, guidePage } from '@/lib/guide'
import type { GuidePage } from '@/lib/guide'
import { cn } from '@/lib/utils'

/**
 * A page of the guide (ui/DESIGN.md, "The guide"), laid out as a documentation site: the guide's pages by group on the
 * left, the page in the middle with Previous and Next at its foot, and its headings on the right. Each column comes in
 * by the pane's width, not the window's, and only once the article keeps its whole measure beside it, so the article
 * never narrows as the window widens. A page the guide has none of is the 404.
 */
export const Route = createFileRoute('/guide/$page')({
    loader: ({ params }) => {
        const page = guidePage(params.page)
        if (page === undefined) {
            // oxlint-disable-next-line typescript/only-throw-error -- the router's own not-found signal is not an Error
            throw notFound()
        }
        return page
    },
    component: GuidePageView,
})

function GuidePageView() {
    const page = Route.useLoaderData()
    return (
        // The pane is the container, so the rail's width counts. The page list comes in when the pane holds it, its
        // gap, and the article's whole 48rem (62.5rem); On this page when it holds that and 12rem and a gap more
        // (76.5rem). A 1280px window gives the pane just over 62.5rem.
        <div className="@container" data-testid="guide">
            <div
                className={cn(
                    'mx-auto grid w-full max-w-7xl grid-cols-1 gap-x-8 gap-y-6',
                    '@min-[62.5rem]:grid-cols-[12.5rem_minmax(0,1fr)]',
                    '@min-[76.5rem]:grid-cols-[12.5rem_minmax(0,1fr)_12rem]',
                )}
            >
                <GuideSidebar page={page} />
                <article className="flex max-w-3xl min-w-0 flex-col gap-8" data-testid="guide-page">
                    <PageHeader root={page.group} title={page.title} tab={`${page.title} · Guide`}>
                        <GuideLines lines={page.lead} />
                    </PageHeader>
                    <GuideText blocks={page.body} page={page.slug} />
                    <PreviousNext page={page} />
                </article>
                <OnThisPage page={page} />
            </div>
        </div>
    )
}

/**
 * The guide's pages, by group, this one marked. Beside the page once the pane has room for it and the article's whole
 * measure, sticking as it scrolls; short of that, a toggle above the page that opens the same list.
 */
function GuideSidebar({ page }: { page: GuidePage }) {
    return (
        <>
            <Collapsible className="rounded-md border @min-[62.5rem]:hidden">
                <CollapsibleTrigger
                    className={cn(
                        'group flex w-full items-center justify-between px-3 py-2 text-sm font-medium',
                        'rounded-md outline-none focus-visible:ring-3 focus-visible:ring-ring/50',
                    )}
                >
                    Guide pages
                    <ChevronDown
                        aria-hidden
                        className="size-4 transition-transform group-data-[state=open]:rotate-180"
                    />
                </CollapsibleTrigger>
                <CollapsibleContent className="border-t px-3 py-3">
                    <GuideTree page={page} />
                </CollapsibleContent>
            </Collapsible>
            <aside className="sticky top-0 hidden self-start @min-[62.5rem]:block">
                <GuideTree page={page} />
            </aside>
        </>
    )
}

function GuideTree({ page }: { page: GuidePage }) {
    return (
        <nav aria-label="Guide" className="flex flex-col gap-6">
            {GUIDE_GROUPS.map((group) => (
                <section key={group.title} aria-label={group.title} className="flex flex-col gap-2">
                    {/* Not a heading: its section is named for it, and the page's outline starts at its h1. */}
                    <p className="text-sm font-semibold">{group.title}</p>
                    <ul className="flex flex-col border-l">
                        {group.pages.map((other) => (
                            <li key={other.slug}>
                                <Link
                                    to="/guide/$page"
                                    params={{ page: other.slug }}
                                    activeOptions={{ includeHash: false }}
                                    aria-current={other.slug === page.slug ? 'page' : undefined}
                                    className={cn(
                                        '-ml-px block border-l border-transparent py-1 pl-3 text-sm',
                                        'text-muted-foreground hover:border-muted-foreground hover:text-foreground',
                                        'aria-[current=page]:border-accent aria-[current=page]:font-medium',
                                        'aria-[current=page]:text-accent',
                                    )}
                                >
                                    {other.title}
                                </Link>
                            </li>
                        ))}
                    </ul>
                </section>
            ))}
        </nav>
    )
}

/** The page's `##` headings, beside it once the pane has room for them too, sticking as it scrolls. */
function OnThisPage({ page }: { page: GuidePage }) {
    if (page.headings.length === 0) {
        return null
    }
    return (
        <nav aria-label="On this page" className="sticky top-0 hidden flex-col gap-2 self-start @min-[76.5rem]:flex">
            <h2 className="text-sm font-semibold">On this page</h2>
            <ul className="flex flex-col gap-1">
                {page.headings.map((heading) => (
                    <li key={heading.id}>
                        <Link
                            to="/guide/$page"
                            params={{ page: page.slug }}
                            hash={heading.id}
                            className="block py-0.5 text-sm text-muted-foreground hover:text-foreground"
                        >
                            {heading.text}
                        </Link>
                    </li>
                ))}
            </ul>
        </nav>
    )
}

/** The pages before and after this one, at its foot: a documentation site's Previous and Next. */
function PreviousNext({ page }: { page: GuidePage }) {
    const { previous, next } = guideNeighbours(page.slug)
    if (previous === undefined && next === undefined) {
        return null
    }
    return (
        <nav aria-label="Previous and next" className="grid grid-cols-2 gap-4 border-t pt-6">
            {previous === undefined ? <span /> : <Neighbour page={previous} rel="Previous" />}
            {next === undefined ? <span /> : <Neighbour page={next} rel="Next" />}
        </nav>
    )
}

function Neighbour({ page, rel }: { page: GuidePage; rel: 'Previous' | 'Next' }) {
    return (
        <Link
            to="/guide/$page"
            params={{ page: page.slug }}
            className={cn(
                'flex flex-col gap-0.5 rounded-md border px-4 py-3 hover:bg-surface-raised',
                rel === 'Next' && 'col-start-2 items-end text-right',
            )}
        >
            <span className="text-xs text-muted-foreground">{rel}</span>
            <span className="text-sm font-medium text-accent">{page.title}</span>
        </Link>
    )
}
