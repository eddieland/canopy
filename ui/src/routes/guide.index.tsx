import { createFileRoute, Link } from '@tanstack/react-router'

import { GuideLines } from '@/components/guide-text'
import { PageHeader, Panel, PanelHeader } from '@/components/panel'
import { GUIDE } from '@/lib/guide'

/** The guide's contents (ui/DESIGN.md, "The guide"): every page, in its order, each with what it covers. */
export const Route = createFileRoute('/guide/')({
    component: GuideIndex,
})

function GuideIndex() {
    return (
        <>
            <PageHeader root="Guide" title="Guide">
                How canopy&apos;s web UI works, a page each, bundled with this build, so it describes the canopy you are
                running.
            </PageHeader>
            <Panel>
                <PanelHeader label="Pages">
                    <span className="readout text-xs text-muted-foreground">{GUIDE.length}</span>
                </PanelHeader>
                <ul className="divide-y" data-testid="guide-pages">
                    {GUIDE.map((page) => (
                        <li key={page.slug} className="flex flex-col gap-0.5 px-3 py-2.5">
                            <Link
                                to="/guide/$page"
                                params={{ page: page.slug }}
                                className="self-start text-sm font-medium underline-offset-4 hover:underline"
                            >
                                {page.title}
                            </Link>
                            <p className="max-w-3xl text-sm text-muted-foreground">
                                <GuideLines lines={page.lead} />
                            </p>
                        </li>
                    ))}
                </ul>
            </Panel>
        </>
    )
}
