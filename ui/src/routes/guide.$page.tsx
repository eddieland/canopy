import { createFileRoute, Link, notFound } from '@tanstack/react-router'

import { GuideLines, GuideText } from '@/components/guide-text'
import { PageHeader, Panel, PanelHeader } from '@/components/panel'
import { GUIDE, guidePage } from '@/lib/guide'
import type { GuidePage } from '@/lib/guide'
import { cn } from '@/lib/utils'

/**
 * A page of the guide (ui/DESIGN.md, "The guide"), beside the guide's pages and the headings on this one. A page the
 * guide has none of is the 404.
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
        <>
            <PageHeader root="Guide" title={page.title} tab={`${page.title} · Guide`}>
                <GuideLines lines={page.lead} />
            </PageHeader>
            <div className="grid items-start gap-6 lg:grid-cols-[minmax(0,1fr)_16rem]">
                <Panel className="p-5" data-testid="guide-page">
                    <GuideText blocks={page.body} />
                </Panel>
                <GuideNav page={page} />
            </div>
        </>
    )
}

/** Beside the page: the guide's pages, this one marked, and the headings on this one. */
function GuideNav({ page }: { page: GuidePage }) {
    return (
        <div className="flex flex-col gap-6 lg:sticky lg:top-6">
            {page.headings.length > 0 && (
                <Panel>
                    <PanelHeader label="On this page" />
                    <nav aria-label="On this page" className="flex flex-col p-1.5">
                        {page.headings.map((heading) => (
                            <Link
                                key={heading.id}
                                to="/guide/$page"
                                params={{ page: page.slug }}
                                hash={heading.id}
                                className="rounded-sm px-1.5 py-1 text-sm text-muted-foreground hover:bg-surface-raised"
                            >
                                {heading.text}
                            </Link>
                        ))}
                    </nav>
                </Panel>
            )}
            <Panel>
                <PanelHeader label="Guide">
                    <Link to="/guide" className="text-xs text-accent underline-offset-4 hover:underline">
                        all pages
                    </Link>
                </PanelHeader>
                <nav aria-label="Guide" className="flex flex-col p-1.5">
                    {GUIDE.map((other) => (
                        <Link
                            key={other.slug}
                            to="/guide/$page"
                            params={{ page: other.slug }}
                            activeOptions={{ includeHash: false }}
                            className={cn(
                                'rounded-sm px-1.5 py-1 text-sm text-muted-foreground hover:bg-surface-raised',
                                'data-[status=active]:bg-surface-raised data-[status=active]:text-foreground',
                            )}
                        >
                            {other.title}
                        </Link>
                    ))}
                </nav>
            </Panel>
        </div>
    )
}
