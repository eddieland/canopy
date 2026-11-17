import { createFileRoute, Link, notFound, useLocation } from '@tanstack/react-router'
import { ChevronDown } from 'lucide-react'

import { GuideLines, GuideText } from '@/components/guide-text'
import { PageHeader } from '@/components/panel'
import { Collapsible, CollapsibleContent, CollapsibleTrigger } from '@/components/ui/collapsible'
import { useSectionRead } from '@/hooks/use-section-read'
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

// A column beside the article: it stays under the header as the page scrolls, a little clear of it, and is never
// taller than the window, so a list too long for it scrolls on its own and its last entry is always in reach. The
// padding, taken back by the margin, is the room a link's focus ring needs inside what clips it.
const BESIDE = cn(
    'sticky top-6 -m-1 max-h-[calc(100dvh-6rem)] scrollbar-thin self-start overflow-y-auto p-1',
    'print:static print:max-h-none',
)

function GuidePageView() {
    const page = Route.useLoaderData()
    return (
        // The pane is the container, so the rail's width counts. The page list comes in when the pane holds it, its
        // gap, and the article's whole 48rem (62.5rem); On this page when it holds that and 12rem and a gap more
        // (76.5rem). A 1280px window gives the pane just over 62.5rem. The guide reads in Plex Sans under every
        // palette, an editor's mono one included (`guide-face`).
        <div className="@container guide-face" data-testid="guide">
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
 * measure, staying put as the page scrolls and scrolling on its own when it is taller than the window; short of that,
 * a toggle above the page that opens the same list.
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
                <CollapsibleContent className="border-t p-3">
                    <GuideTree page={page} />
                </CollapsibleContent>
            </Collapsible>
            <aside className={cn(BESIDE, 'hidden @min-[62.5rem]:block')}>
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
                                    ref={other.slug === page.slug ? showInList : undefined}
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

// Brings the page shown into view in the list of pages, which may be scrolled past it. The nearest edge, so a link
// already in view moves nothing, the page least of all.
function showInList(link: HTMLAnchorElement | null) {
    link?.scrollIntoView({ block: 'nearest' })
}

/**
 * The page's `##` headings, beside it once the pane has room for them too, staying put as the page scrolls, with the
 * section being read marked.
 */
function OnThisPage({ page }: { page: GuidePage }) {
    const hash = useLocation({ select: (location) => location.hash })
    const read = useSectionRead(page.headings.map((heading) => heading.id).join(' '), hash)
    if (page.headings.length === 0) {
        return null
    }
    return (
        <nav aria-label="On this page" className={cn(BESIDE, 'hidden flex-col gap-2 @min-[76.5rem]:flex')}>
            <h2 className="text-sm font-semibold">On this page</h2>
            <ul className="flex flex-col gap-1">
                {page.headings.map((heading) => (
                    <li key={heading.id}>
                        <Link
                            to="/guide/$page"
                            params={{ page: page.slug }}
                            hash={heading.id}
                            // Only the heading the address names is the link to where you are, not every one: they
                            // share a path. The mark follows the page instead, however far it has scrolled since.
                            activeOptions={{ includeHash: true }}
                            data-current={heading.id === read || undefined}
                            className={cn(
                                'block py-0.5 text-sm text-muted-foreground hover:text-foreground',
                                'data-current:text-accent',
                            )}
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
