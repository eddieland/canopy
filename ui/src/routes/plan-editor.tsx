import { useQuery } from '@tanstack/react-query'
import { createFileRoute } from '@tanstack/react-router'
import { useState } from 'react'

import { metaQuery } from '@/api/queries'
import { Disclosure } from '@/components/disclosure'
import { Empty, PageHeader, Panel, PanelHeader, PanelSkeleton } from '@/components/panel'
import { PlanEditor } from '@/components/plan-editor'
import { Collapsible, CollapsibleContent } from '@/components/ui/collapsible'
import { SAMPLE_PLAN, SAMPLE_PREVIOUS, SAMPLE_THREADS } from '@/lib/plan-sample'

/**
 * The plan editor over a sample plan, on mock data alone: where the editor is tried and tested on its own
 * (docs/design/PLANNING.md §25). A ticket's own plan opens on its page. Nothing here is saved: what Ask for changes
 * would send the planner shows under the editor instead, with the plan's Markdown.
 */
export const Route = createFileRoute('/plan-editor')({
    component: PlanEditorPage,
})

function PlanEditorPage() {
    const meta = useQuery(metaQuery).data
    return (
        <>
            <PageHeader root="Plans" title="Plan editor">
                A sample plan to edit and comment on. A ticket&apos;s own plan opens like this on its page; nothing here
                is saved.
            </PageHeader>
            {meta === undefined && (
                <Panel>
                    <PanelSkeleton rows={4} className="min-h-72" />
                </Panel>
            )}
            {meta?.mock === false && (
                <Panel>
                    <Empty size="panel">no sample here: a ticket&apos;s plan opens on its page</Empty>
                </Panel>
            )}
            {meta?.mock === true && <Sample />}
        </>
    )
}

// A block of the page's own text, the planner's request or the plan's Markdown, as written.
const BLOCK = 'overflow-x-auto px-3 py-2.5 font-mono text-xs leading-relaxed whitespace-pre-wrap'

function Sample() {
    const [threads, setThreads] = useState(SAMPLE_THREADS)
    const [markdown, setMarkdown] = useState(SAMPLE_PLAN)
    const [asked, setAsked] = useState<string | undefined>(undefined)
    const [showMarkdown, setShowMarkdown] = useState(false)
    return (
        <>
            <PlanEditor
                markdown={SAMPLE_PLAN}
                threads={threads}
                onThreadsChange={setThreads}
                onChange={setMarkdown}
                onAskForChanges={setAsked}
                previous={{ label: 'plan 1', markdown: SAMPLE_PREVIOUS }}
            />
            <Panel>
                <PanelHeader label="What the planner reads" />
                {asked === undefined ? (
                    <Empty>no request yet: comment on the plan, then Ask for changes</Empty>
                ) : (
                    <pre aria-label="Change request" className={BLOCK}>
                        {asked}
                    </pre>
                )}
            </Panel>
            <Collapsible asChild open={showMarkdown} onOpenChange={setShowMarkdown}>
                <Panel>
                    <PanelHeader label="Markdown">
                        <Disclosure open={showMarkdown} what="Markdown" />
                    </PanelHeader>
                    <CollapsibleContent>
                        <pre aria-label="Plan Markdown" className={BLOCK}>
                            {markdown}
                        </pre>
                    </CollapsibleContent>
                </Panel>
            </Collapsible>
        </>
    )
}
